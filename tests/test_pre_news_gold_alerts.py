"""
Tests for automatic pre-news XAU/USD gold predictions and Telegram alert lifecycle.

Covers:
  1. 15-minute pre-release forecast creation and Telegram delivery.
  2. Events crossing midnight UTC or DST transitions.
  3. Safe recovery upon app restart before release.
  4. Missed scheduling run catch-up.
  5. Duplicate scheduler sweeps idempotency (no duplicate forecasts or messages).
  6. Telegram delivery failure, preservation of forecast, and retry.
  7. No pre-release notification after event has already occurred.
  8. Missing or tentative event timestamps (no invented midnight time).
  9. Prevention of post-release data leakage.
  10. Post-release outcome verification alert (truth vs failed).
"""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from alerts import (
    format_gold_outcome_message,
    format_gold_prediction_message,
    send_gold_outcome_alert,
    send_gold_prediction_alert,
)
from database import (
    AlertLog,
    Base,
    GoldForecast,
)
import scheduler
from scheduler import (
    get_gold_alert_minutes,
    parse_release_dt_utc,
    process_and_grade_gold_outcomes,
    process_pre_release_gold_predictions,
)


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()
    yield db, TestingSessionLocal
    db.close()


# ─── 1. Prediction scheduled 15 minutes before release ─────────────────────────

def test_prediction_scheduled_15_minutes_before_release(test_db):
    db, _ = test_db
    now_utc = datetime(2026, 10, 14, 12, 15, 0, tzinfo=timezone.utc)
    rel_dt = now_utc + timedelta(minutes=14, seconds=50)  # ~14.8m -> 15m tier
    rel_str = rel_dt.isoformat().replace("+00:00", "Z")

    events = [
        {
            "event_code": "CPI_MM",
            "event_name": "CPI m/m",
            "currency": "USD",
            "impact": "HIGH",
            "release_time_utc": rel_str,
            "forecast": 0.3,
            "previous": 0.2,
        }
    ]

    sent_messages = []

    def mock_sender(msg):
        sent_messages.append(msg)

    with patch("gold_model.create_gold_forecast") as mock_create:
        def side_effect(sess, ev_group, now=None):
            gf = GoldForecast(
                release_moment_id="moment-cpi-15m",
                release_time_utc=rel_str,
                event_family="cpi",
                event_codes_json=json.dumps(["CPI_MM"]),
                event_names_json=json.dumps(["Consumer Price Index"]),
                created_at=now_utc.replace(tzinfo=None),
                horizon_minutes=5,
                feature_snapshot=json.dumps({"core_cpi": {"value": 0.2, "status": "available"}}),
                model_features=json.dumps({"is_cpi": 1.0}),
                forecast_status="provisional",
                forecast_direction="BEARISH",
                probabilities_json=json.dumps({"bullish": 0.25, "bearish": 0.65, "neutral": 0.10}),
                n_trained=12,
            )
            sess.add(gf)
            sess.commit()
            return {"release_time_utc": rel_str}

        mock_create.side_effect = side_effect

        processed = process_pre_release_gold_predictions(
            db, events, now_utc=now_utc, sender_func=mock_sender
        )

    assert len(processed) == 1
    assert "15m" in processed[0]

    # Verify forecast was saved
    saved_gf = db.query(GoldForecast).filter_by(release_time_utc=rel_str).first()
    assert saved_gf is not None
    assert saved_gf.forecast_direction == "BEARISH"

    # Verify Telegram message content
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    assert "UPCOMING XAU/USD FORECAST" in msg
    assert "Consumer Price Index" in msg
    assert "in 15m" in msg
    assert "5-minute reaction window" in msg
    assert "BEARISH" in msg
    assert "65.0%" in msg  # Bearish probability
    assert "Probabilistic macroeconomic model" in msg

    # Verify AlertLog row
    log_row = db.query(AlertLog).filter_by(alert_type="GOLD_PRE_15M").first()
    assert log_row is not None
    assert log_row.status == "sent"
    assert log_row.delivery_attempts == 1


# ─── 2. Release crossing midnight UTC or DST transition ───────────────────────

def test_release_scheduled_time_crosses_midnight_or_dst():
    # Case A: Event in New York at 20:30 EDT (-04:00) -> 00:30 UTC next day
    dt_ny = parse_release_dt_utc("2026-10-14T20:30:00-04:00")
    assert dt_ny is not None
    assert dt_ny.year == 2026
    assert dt_ny.month == 10
    assert dt_ny.day == 15  # Crosses midnight into the 15th
    assert dt_ny.hour == 0
    assert dt_ny.minute == 30
    assert dt_ny.tzinfo == timezone.utc

    # Case B: Event in London / GMT
    dt_z = parse_release_dt_utc("2026-10-14T12:30:00Z")
    assert dt_z is not None
    assert dt_z.day == 14
    assert dt_z.hour == 12
    assert dt_z.minute == 30

    # Case C: Winter time DST transition (-05:00)
    dt_est = parse_release_dt_utc("2026-12-10T08:30:00-05:00")
    assert dt_est is not None
    assert dt_est.hour == 13
    assert dt_est.minute == 30


# ─── 3. Restart before release ────────────────────────────────────────────────

def test_restart_before_release(test_db):
    db, _ = test_db
    # App starts up at T - 25m
    now_utc = datetime(2026, 10, 14, 12, 5, 0, tzinfo=timezone.utc)
    rel_dt = now_utc + timedelta(minutes=25)  # Event at 12:30
    rel_str = rel_dt.isoformat().replace("+00:00", "Z")

    events = [
        {
            "event_code": "NFP",
            "event_name": "Non-Farm Employment Change",
            "currency": "USD",
            "impact": "HIGH",
            "release_time_utc": rel_str,
            "forecast": 180.0,
            "previous": 160.0,
        }
    ]

    sent_messages = []

    def mock_sender(msg):
        sent_messages.append(msg)

    with patch("gold_model.create_gold_forecast") as mock_create:
        def side_effect(sess, ev_group, now=None):
            gf = GoldForecast(
                release_moment_id="moment-nfp-restart",
                release_time_utc=rel_str,
                event_family="employment",
                event_codes_json=json.dumps(["NFP"]),
                event_names_json=json.dumps(["Nonfarm Payrolls"]),
                created_at=now_utc.replace(tzinfo=None),
                horizon_minutes=5,
                feature_snapshot="{}",
                model_features="{}",
                forecast_status="warming_up",
                forecast_direction=None,
                n_trained=3,
            )
            sess.add(gf)
            sess.commit()
            return {"release_time_utc": rel_str}

        mock_create.side_effect = side_effect

        # First run after restart: falls into 30m tier (15 < 25 <= 30)
        processed = process_pre_release_gold_predictions(
            db, events, now_utc=now_utc, sender_func=mock_sender
        )

    assert len(processed) == 1
    assert "30m" in processed[0]
    assert len(sent_messages) == 1
    assert "in 30m" in sent_messages[0]

    # Verify 60m tier was NOT sent since 60m had already passed
    assert db.query(AlertLog).filter_by(alert_type="GOLD_PRE_60M").first() is None
    assert db.query(AlertLog).filter_by(alert_type="GOLD_PRE_30M").first() is not None


# ─── 4. Missed scheduling run and safe recovery ────────────────────────────────

def test_missed_scheduling_run_and_safe_recovery(test_db):
    db, _ = test_db
    # Missed 60m, 30m, 15m. Scheduler runs at T - 8m (10m tier)
    now_utc = datetime(2026, 10, 14, 12, 22, 0, tzinfo=timezone.utc)
    rel_dt = now_utc + timedelta(minutes=8)
    rel_str = rel_dt.isoformat().replace("+00:00", "Z")

    events = [
        {
            "event_code": "RETAIL_SALES",
            "event_name": "Retail Sales m/m",
            "currency": "USD",
            "impact": "HIGH",
            "release_time_utc": rel_str,
            "forecast": 0.4,
            "previous": 0.1,
        }
    ]

    sent = []
    with patch("gold_model.create_gold_forecast") as mock_create:
        def side_effect(sess, ev_group, now=None):
            gf = GoldForecast(
                release_moment_id="moment-retail-recovery",
                release_time_utc=rel_str,
                event_family="retail",
                event_codes_json=json.dumps(["RETAIL_SALES"]),
                event_names_json=json.dumps(["Retail Sales"]),
                created_at=now_utc.replace(tzinfo=None),
                horizon_minutes=5,
                feature_snapshot="{}",
                model_features="{}",
                forecast_status="provisional",
                forecast_direction="BULLISH",
                probabilities_json=json.dumps({"bullish": 0.70, "bearish": 0.20, "neutral": 0.10}),
                n_trained=10,
            )
            sess.add(gf)
            sess.commit()
            return {"release_time_utc": rel_str}

        mock_create.side_effect = side_effect
        processed = process_pre_release_gold_predictions(
            db, events, now_utc=now_utc, sender_func=lambda m: sent.append(m)
        )

    assert len(processed) == 1
    assert "10m" in processed[0]
    assert len(sent) == 1
    assert "in 10m" in sent[0]
    assert "BULLISH" in sent[0]


# ─── 5. Duplicate scheduler sweeps idempotency ────────────────────────────────

def test_duplicate_scheduler_sweeps_prevent_duplicate_messages_and_predictions(test_db):
    db, _ = test_db
    now_utc = datetime(2026, 10, 14, 12, 14, 0, tzinfo=timezone.utc)
    rel_dt = now_utc + timedelta(minutes=14)
    rel_str = rel_dt.isoformat().replace("+00:00", "Z")

    events = [
        {
            "event_code": "PPI",
            "event_name": "PPI m/m",
            "currency": "USD",
            "impact": "HIGH",
            "release_time_utc": rel_str,
            "forecast": 0.2,
            "previous": 0.0,
        }
    ]

    sent_messages = []

    def mock_sender(msg):
        sent_messages.append(msg)

    with patch("gold_model.create_gold_forecast") as mock_create:
        def side_effect(sess, ev_group, now=None):
            gf = GoldForecast(
                release_moment_id="moment-ppi-dedup",
                release_time_utc=rel_str,
                event_family="ppi",
                event_codes_json=json.dumps(["PPI"]),
                event_names_json=json.dumps(["Producer Price Index"]),
                created_at=now_utc.replace(tzinfo=None),
                horizon_minutes=5,
                feature_snapshot="{}",
                model_features="{}",
                forecast_status="warming_up",
                forecast_direction=None,
                n_trained=2,
            )
            sess.add(gf)
            sess.commit()
            return {"release_time_utc": rel_str}

        mock_create.side_effect = side_effect

        # Sweep 1
        processed_1 = process_pre_release_gold_predictions(
            db, events, now_utc=now_utc, sender_func=mock_sender
        )
        # Sweep 2 (10 seconds later, same 15m window)
        processed_2 = process_pre_release_gold_predictions(
            db, events, now_utc=now_utc + timedelta(seconds=10), sender_func=mock_sender
        )

    # Sweep 1 sent the alert
    assert len(processed_1) == 1
    # Sweep 2 safely skipped sending duplicate
    assert len(processed_2) == 0

    # Exactly 1 message sent
    assert len(sent_messages) == 1

    # Exactly 1 GoldForecast in DB
    forecast_count = db.query(GoldForecast).filter_by(release_time_utc=rel_str).count()
    assert forecast_count == 1


# ─── 6. Telegram delivery failure and retry ───────────────────────────────────

def test_telegram_delivery_failure_and_retry(test_db):
    db, _ = test_db
    now_utc = datetime(2026, 10, 14, 12, 14, 0, tzinfo=timezone.utc)
    rel_dt = now_utc + timedelta(minutes=14)
    rel_str = rel_dt.isoformat().replace("+00:00", "Z")

    events = [
        {
            "event_code": "CPI_MM",
            "event_name": "CPI m/m",
            "currency": "USD",
            "impact": "HIGH",
            "release_time_utc": rel_str,
            "forecast": 0.3,
            "previous": 0.2,
        }
    ]

    gf = GoldForecast(
        release_moment_id="moment-cpi-retry",
        release_time_utc=rel_str,
        event_family="cpi",
        event_codes_json=json.dumps(["CPI_MM"]),
        event_names_json=json.dumps(["Consumer Price Index"]),
        created_at=now_utc.replace(tzinfo=None),
        horizon_minutes=5,
        feature_snapshot="{}",
        model_features="{}",
        forecast_status="provisional",
        forecast_direction="BEARISH",
        n_trained=15,
    )
    db.add(gf)
    db.commit()

    # Attempt 1: Fails with network error
    fail_sender = MagicMock(side_effect=ConnectionError("Telegram network timeout"))
    process_pre_release_gold_predictions(
        db, events, now_utc=now_utc, sender_func=fail_sender
    )

    # Forecast row MUST remain intact in database!
    reloaded_gf = db.query(GoldForecast).filter_by(release_time_utc=rel_str).first()
    assert reloaded_gf is not None

    # AlertLog must record failure
    log_row = db.query(AlertLog).filter_by(idempotency_key="gold_pre|moment-cpi-retry|15m").first()
    assert log_row is not None
    assert log_row.status == "failed"
    assert "network timeout" in log_row.error_message.lower()
    assert log_row.delivery_attempts == 1

    # Attempt 2: Succeeds
    success_sender = MagicMock()
    process_pre_release_gold_predictions(
        db, events, now_utc=now_utc + timedelta(seconds=30), sender_func=success_sender
    )

    db.refresh(log_row)
    assert log_row.status == "sent"
    assert log_row.delivery_attempts == 2
    assert log_row.error_message is None
    assert success_sender.call_count == 1


# ─── 7. No pre-release notification after event has occurred ──────────────────

def test_no_pre_release_notification_after_event_already_occurred(test_db):
    db, _ = test_db
    # Event released 5 minutes ago
    now_utc = datetime(2026, 10, 14, 12, 35, 0, tzinfo=timezone.utc)
    rel_dt = now_utc - timedelta(minutes=5)
    rel_str = rel_dt.isoformat().replace("+00:00", "Z")

    events = [
        {
            "event_code": "NFP",
            "event_name": "Nonfarm Payrolls",
            "currency": "USD",
            "impact": "HIGH",
            "release_time_utc": rel_str,
            "forecast": 150.0,
            "previous": 140.0,
            "actual": 175.0,
        }
    ]

    sender = MagicMock()
    processed = process_pre_release_gold_predictions(
        db, events, now_utc=now_utc, sender_func=sender
    )

    assert len(processed) == 0
    assert sender.call_count == 0
    assert db.query(AlertLog).count() == 0


# ─── 8. Missing or tentative event timestamps ──────────────────────────────────

def test_missing_or_tentative_event_timestamps(test_db):
    # Pure dates without times (tentative or all-day)
    assert parse_release_dt_utc("2026-10-14") is None
    assert parse_release_dt_utc("Tentative") is None
    assert parse_release_dt_utc("") is None
    assert parse_release_dt_utc(None) is None

    db, _ = test_db
    events = [
        {
            "event_code": "FOMC_TENTATIVE",
            "event_name": "FOMC Meeting",
            "currency": "USD",
            "impact": "HIGH",
            "release_time_utc": "2026-10-14",  # Tentative, no time component
            "forecast": None,
            "previous": None,
        }
    ]

    sender = MagicMock()
    processed = process_pre_release_gold_predictions(
        db, events, now_utc=datetime.now(timezone.utc), sender_func=sender
    )
    assert len(processed) == 0
    assert sender.call_count == 0


# ─── 9. Prevention of post-release data leakage ───────────────────────────────

def test_prevention_of_post_release_data_leakage(test_db):
    db, _ = test_db
    from gold_model import create_gold_forecast

    past_rel = "2026-10-14T12:30:00Z"
    # Called AFTER the event release time
    called_at = datetime(2026, 10, 14, 12, 35, 0, tzinfo=timezone.utc)

    events = [
        {
            "event_code": "CPI_MM",
            "currency": "USD",
            "release_time_utc": past_rel,
            "forecast": 0.3,
            "previous": 0.2,
        }
    ]

    result = create_gold_forecast(db, events, now=called_at)
    # Strictly returns None when captured_at >= release_time
    assert result is None
    assert db.query(GoldForecast).filter_by(release_time_utc=past_rel).first() is None


# ─── 10. Post-release outcome verification alert (truth vs failed) ────────────

def test_post_release_outcome_alert_truth_vs_failed(test_db):
    db, _ = test_db

    # Case A: Model predicted BEARISH, actual outcome was BEARISH -> TRUTH
    gf_truth = GoldForecast(
        release_moment_id="moment-truth",
        release_time_utc="2026-09-10T12:30:00Z",
        event_family="cpi",
        event_codes_json=json.dumps(["CPI_MM"]),
        event_names_json=json.dumps(["Consumer Price Index"]),
        created_at=datetime(2026, 9, 10, 12, 0),
        horizon_minutes=5,
        feature_snapshot="{}",
        model_features="{}",
        forecast_status="provisional",
        forecast_direction="BEARISH",
        gold_price_at_release=4330.50,
        gold_change_5m_pct=-0.4403,
        outcome_label="BEARISH",
        outcome_status="ok",
        outcome_recorded_at=datetime(2026, 9, 10, 13, 10),
    )
    msg_truth = format_gold_outcome_message(gf_truth)
    assert "OUTCOME & VERIFICATION" in msg_truth
    assert "PREDICTION CONFIRMED (TRUTH)" in msg_truth
    assert "BEARISH" in msg_truth

    # Case B: Model predicted BULLISH, actual outcome was BEARISH -> FAILED
    gf_failed = GoldForecast(
        release_moment_id="moment-failed",
        release_time_utc="2026-09-11T12:30:00Z",
        event_family="ppi",
        event_codes_json=json.dumps(["PPI"]),
        event_names_json=json.dumps(["Producer Price Index"]),
        created_at=datetime(2026, 9, 11, 12, 0),
        horizon_minutes=5,
        feature_snapshot="{}",
        model_features="{}",
        forecast_status="provisional",
        forecast_direction="BULLISH",
        gold_price_at_release=4340.00,
        gold_change_5m_pct=-0.2500,
        outcome_label="BEARISH",
        outcome_status="ok",
        outcome_recorded_at=datetime(2026, 9, 11, 13, 10),
    )
    msg_failed = format_gold_outcome_message(gf_failed)
    assert "PREDICTION MISSED (FAILED)" in msg_failed

    # Case C: Delivery through send_gold_outcome_alert and AlertLog tracking
    db.add(gf_truth)
    db.commit()

    sent_outcomes = []
    ok, err = send_gold_outcome_alert(
        db, gf_truth, sender_func=lambda m: sent_outcomes.append(m)
    )
    assert ok is True
    assert len(sent_outcomes) == 1
    assert "PREDICTION CONFIRMED (TRUTH)" in sent_outcomes[0]

    # Verify idempotency key prevents duplicate outcome alert
    ok_dup, err_dup = send_gold_outcome_alert(
        db, gf_truth, sender_func=lambda m: sent_outcomes.append(m)
    )
    assert ok_dup is False
    assert err_dup == "already_sent"
    assert len(sent_outcomes) == 1  # No duplicate sent
