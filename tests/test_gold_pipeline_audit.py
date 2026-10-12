"""
Comprehensive audit tests for MacroPredictor v4 gold reaction pipeline:
1. Full trace: process_and_grade_gold_outcomes -> fetch_and_record_gold_outcome -> record_gold_outcome -> train_gold_outcome
2. Database writes: status, recorded_at, 1m/5m/15m/30m returns, 5m excursion, outcome label
3. Incomplete candles & retry behavior on delayed data
4. Duplicate sweep & idempotency protection
5. Training failure rollback & recovery
6. Label independence (XAU/USD return vs USD forecast)
7. Point-in-time COT published_at filtering
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base, GoldForecast, GoldModelTraining, CotSnapshot
import gold_model
import scheduler


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    db = TestingSession()
    yield db, TestingSession
    db.close()


def _make_mock_candles(release_dt: datetime, base_price: float = 2000.0, trend_pct: float = 0.5):
    """
    Generate synthetic 1-minute OHLC candles covering release - 5m through release + 35m.
    trend_pct specifies 5-minute move percent.
    """
    rows = []
    start = release_dt - timedelta(minutes=5)
    end = release_dt + timedelta(minutes=35)
    curr = start
    price = base_price

    while curr <= end:
        if curr < release_dt:
            c = base_price
            h = base_price + 0.2
            l = base_price - 0.2
        elif curr <= release_dt + timedelta(minutes=5):
            step = (curr - release_dt).total_seconds() / 300.0
            c = base_price * (1.0 + (trend_pct / 100.0) * step)
            h = c + 0.5
            l = min(base_price, c) - 0.1
        else:
            c = base_price * (1.0 + (trend_pct / 100.0))
            h = c + 0.3
            l = c - 0.3

        rows.append({
            "datetime": curr.strftime("%Y-%m-%d %H:%M:%S"),
            "open": str(price),
            "high": str(h),
            "low": str(l),
            "close": str(c),
            "volume": "100",
        })
        price = c
        curr += timedelta(minutes=1)

    return rows


# ── 1. Full Pipeline Trace & Database Writes ──────────────────────────

def test_full_pipeline_trace_and_db_writes(test_db, monkeypatch):
    db, SessionLocal = test_db
    monkeypatch.setattr("database.SessionLocal", SessionLocal)
    monkeypatch.setattr("scheduler.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model._gold_trained_moments", set())

    # Seed an earlier prior release for the same family so threshold can be derived
    prior_time = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
    prior_forecast = GoldForecast(
        release_moment_id="moment-audit-prior",
        release_time_utc=prior_time,
        event_family="employment",
        event_codes_json=json.dumps(["NFP"]),
        event_names_json=json.dumps(["Nonfarm Payrolls"]),
        feature_snapshot=json.dumps({}),
        model_features=json.dumps({}),
        forecast_status="ready",
        outcome_status="ok",
        gold_change_5m_pct=0.30,
        outcome_label="BULLISH",
        outcome_recorded_at=datetime.utcnow() - timedelta(days=29),
    )
    db.add(prior_forecast)

    # Current release: 40 minutes ago (>= 35 min threshold)
    rel_dt = datetime.utcnow() - timedelta(minutes=40)
    rel_time_utc = rel_dt.isoformat() + "Z"

    features = {
        "available_consensus_nfp_forecast": 1.0,
        "nfp_forecast": 250.0,
        "family_threshold_pct": 0.15,
    }

    forecast = GoldForecast(
        release_moment_id="moment-audit-1",
        release_time_utc=rel_time_utc,
        event_family="employment",
        event_codes_json=json.dumps(["NFP"]),
        event_names_json=json.dumps(["Nonfarm Payrolls"]),
        created_at=rel_dt - timedelta(minutes=5),
        horizon_minutes=5,
        feature_snapshot=json.dumps(features),
        model_features=json.dumps(features),
        forecast_status="ready",
        forecast_direction="BEARISH",
        outcome_status="pending",
    )
    db.add(forecast)
    db.commit()

    # Mock Twelve Data HTTP response for XAU/USD 1-min candles (+0.6% rally -> BULLISH)
    mock_candles_data = _make_mock_candles(rel_dt, base_price=2600.0, trend_pct=0.6)

    def mock_requests_get(url, params=None, timeout=None):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "status": "ok",
            "values": mock_candles_data,
        }
        return mock_resp

    monkeypatch.setattr("requests.get", mock_requests_get)

    # Run scheduler gold sweep
    graded = scheduler.process_and_grade_gold_outcomes(db=db)

    assert rel_time_utc in graded

    # Verify database record
    db.refresh(forecast)
    assert forecast.outcome_status == "ok"
    assert forecast.outcome_recorded_at is not None
    assert forecast.gold_price_at_release is not None
    assert abs(forecast.gold_price_at_release - 2600.0) < 1.0
    assert forecast.gold_change_1m_pct is not None
    assert forecast.gold_change_5m_pct is not None
    assert forecast.gold_change_15m_pct is not None
    assert forecast.gold_change_30m_pct is not None
    assert forecast.max_up_5m_pct is not None
    assert forecast.max_down_5m_pct is not None
    assert forecast.outcome_label == "BULLISH"
    assert forecast.outcome_data_quality_json is not None
    quality = json.loads(forecast.outcome_data_quality_json)
    assert quality["status"] == "ok"
    assert quality["source"] == "Twelve Data"

    # Verify GoldModelTraining table
    marker = db.get(GoldModelTraining, rel_time_utc)
    assert marker is not None
    assert marker.trained_at is not None


# ── 2. Incomplete Candles, Delayed Data, and Retry ─────────────────────

def test_incomplete_candles_retry_on_subsequent_sweep(test_db, monkeypatch):
    db, SessionLocal = test_db
    monkeypatch.setattr("database.SessionLocal", SessionLocal)
    monkeypatch.setattr("scheduler.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model._gold_trained_moments", set())

    # Seed prior release
    prior_time = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
    prior_forecast = GoldForecast(
        release_moment_id="moment-audit-prior-2",
        release_time_utc=prior_time,
        event_family="inflation",
        event_codes_json=json.dumps(["CPI"]),
        event_names_json=json.dumps(["CPI"]),
        feature_snapshot=json.dumps({}),
        model_features=json.dumps({}),
        forecast_status="ready",
        outcome_status="ok",
        gold_change_5m_pct=0.25,
        outcome_label="BULLISH",
        outcome_recorded_at=datetime.utcnow() - timedelta(days=29),
    )
    db.add(prior_forecast)

    rel_dt = datetime.utcnow() - timedelta(minutes=40)
    rel_time_utc = rel_dt.isoformat() + "Z"

    forecast = GoldForecast(
        release_moment_id="moment-audit-retry",
        release_time_utc=rel_time_utc,
        event_family="inflation",
        event_codes_json=json.dumps(["CPI"]),
        event_names_json=json.dumps(["Consumer Price Index"]),
        feature_snapshot=json.dumps({"f": 1}),
        model_features=json.dumps({"f": 1}),
        forecast_status="ready",
        forecast_direction="BULLISH",
        outcome_status="pending",
    )
    db.add(forecast)
    db.commit()

    # Step A: First fetch returns only 3 minutes of candles (incomplete)
    incomplete_candles = _make_mock_candles(rel_dt, base_price=2600.0, trend_pct=0.4)[:8]

    def mock_get_incomplete(url, params=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"status": "ok", "values": incomplete_candles}
        return resp

    monkeypatch.setattr("requests.get", mock_get_incomplete)

    # First sweep runs
    graded_first = scheduler.process_and_grade_gold_outcomes(db=db)
    assert graded_first == []

    db.refresh(forecast)
    # Status is marked unavailable, but recorded_at is STILL None (retryable)
    assert forecast.outcome_status == "unavailable"
    assert forecast.outcome_recorded_at is None

    # Step B: Full candles arrive on subsequent sweep
    full_candles = _make_mock_candles(rel_dt, base_price=2600.0, trend_pct=0.4)

    def mock_get_full(url, params=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"status": "ok", "values": full_candles}
        return resp

    monkeypatch.setattr("requests.get", mock_get_full)

    # Second sweep retries and succeeds!
    graded_second = scheduler.process_and_grade_gold_outcomes(db=db)
    assert rel_time_utc in graded_second

    db.refresh(forecast)
    assert forecast.outcome_status == "ok"
    assert forecast.outcome_recorded_at is not None
    assert forecast.outcome_label == "BULLISH"


# ── 3. Duplicate Sweep Safety & Exactly-Once Training ─────────────────

def test_duplicate_sweep_and_exact_once_training(test_db, monkeypatch):
    db, SessionLocal = test_db
    monkeypatch.setattr("database.SessionLocal", SessionLocal)
    monkeypatch.setattr("scheduler.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model._gold_trained_moments", set())

    # Seed prior
    prior_time = (datetime.utcnow() - timedelta(days=30)).isoformat() + "Z"
    prior_forecast = GoldForecast(
        release_moment_id="moment-audit-prior-3",
        release_time_utc=prior_time,
        event_family="retail",
        event_codes_json=json.dumps(["RETAIL"]),
        event_names_json=json.dumps(["Retail"]),
        feature_snapshot=json.dumps({}),
        model_features=json.dumps({}),
        forecast_status="ready",
        outcome_status="ok",
        gold_change_5m_pct=-0.35,
        outcome_label="BEARISH",
        outcome_recorded_at=datetime.utcnow() - timedelta(days=29),
    )
    db.add(prior_forecast)

    rel_dt = datetime.utcnow() - timedelta(minutes=50)
    rel_time_utc = rel_dt.isoformat() + "Z"

    forecast = GoldForecast(
        release_moment_id="moment-audit-dedup",
        release_time_utc=rel_time_utc,
        event_family="retail",
        event_codes_json=json.dumps(["RETAIL"]),
        event_names_json=json.dumps(["Retail Sales"]),
        feature_snapshot=json.dumps({"f": 1}),
        model_features=json.dumps({"f": 1}),
        forecast_status="ready",
        forecast_direction="BEARISH",
        outcome_status="pending",
    )
    db.add(forecast)
    db.commit()

    candles = _make_mock_candles(rel_dt, base_price=2600.0, trend_pct=-0.5)

    def mock_get(url, params=None, timeout=None):
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"status": "ok", "values": candles}
        return resp

    monkeypatch.setattr("requests.get", mock_get)

    # First sweep
    res1 = scheduler.process_and_grade_gold_outcomes(db=db)
    assert rel_time_utc in res1

    # Second sweep immediately after
    res2 = scheduler.process_and_grade_gold_outcomes(db=db)
    assert res2 == []

    # Third manual call to train_gold_outcome
    train_res = gold_model.train_gold_outcome(rel_time_utc)
    assert train_res == {}  # Already trained, returns empty


# ── 4. Training Failure Rollback & Retry ───────────────────────────────

def test_training_failure_rolls_back_claim_for_clean_retry(test_db, monkeypatch):
    db, SessionLocal = test_db
    monkeypatch.setattr("database.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model._gold_trained_moments", set())

    rel_time_utc = "2026-04-10T12:30:00Z"
    forecast = GoldForecast(
        release_moment_id="moment-rollback-test",
        release_time_utc=rel_time_utc,
        event_family="employment",
        event_codes_json=json.dumps(["NFP"]),
        event_names_json=json.dumps(["NFP"]),
        feature_snapshot=json.dumps({"x": 1}),
        model_features=json.dumps({"x": 1}),
        forecast_status="ready",
        outcome_status="ok",
        outcome_label="BULLISH",
        gold_change_5m_pct=0.45,
        outcome_recorded_at=datetime.utcnow(),
    )
    db.add(forecast)
    db.commit()

    def broken_upsert(*args, **kwargs):
        raise RuntimeError("Disk full / serialization failure")

    monkeypatch.setattr("gold_model.upsert_river_model", broken_upsert)

    failed_res = gold_model.train_gold_outcome(rel_time_utc)
    assert failed_res == {}

    # Verify claim was rolled back so it's not stuck
    marker = db.get(GoldModelTraining, rel_time_utc)
    assert marker is None

    # Now restore normal upsert and retry
    monkeypatch.setattr("gold_model.upsert_river_model", lambda *args, **kwargs: None)
    success_res = gold_model.train_gold_outcome(rel_time_utc)
    assert success_res.get("was_trained") is True

    marker = db.get(GoldModelTraining, rel_time_utc)
    assert marker is not None
    assert marker.trained_at is not None


# ── 5. Label Independence from USD Economic Forecast ──────────────────

def test_gold_training_label_independent_of_usd_forecast_correctness(test_db, monkeypatch):
    db, SessionLocal = test_db
    monkeypatch.setattr("database.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model.SessionLocal", SessionLocal)
    monkeypatch.setattr("gold_model._gold_trained_moments", set())

    rel_time_utc = "2026-05-15T12:30:00Z"
    forecast = GoldForecast(
        release_moment_id="moment-label-independence",
        release_time_utc=rel_time_utc,
        event_family="employment",
        event_codes_json=json.dumps(["NFP"]),
        event_names_json=json.dumps(["NFP"]),
        feature_snapshot=json.dumps({"x": 1}),
        model_features=json.dumps({"x": 1}),
        forecast_direction="BEARISH",
        outcome_status="ok",
        outcome_label="BULLISH",
        gold_change_5m_pct=0.55,
        outcome_recorded_at=datetime.utcnow(),
    )
    db.add(forecast)
    db.commit()

    learned_labels = []

    class MockModel:
        def learn_one(self, feats, label):
            learned_labels.append(label)

    monkeypatch.setattr("gold_model._get_or_load_gold_model", lambda: (MockModel(), 0))
    monkeypatch.setattr("gold_model.upsert_river_model", lambda *a, **kw: None)

    res = gold_model.train_gold_outcome(rel_time_utc)
    assert res.get("was_trained") is True
    assert learned_labels == ["BULLISH"]


# ── 6. Point-in-Time COT Published_At Filtering ───────────────────────

def test_cot_point_in_time_filtering_with_published_at(test_db):
    db, _ = test_db
    as_of = datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc)  # Wednesday 14:00 UTC

    # Report date Tuesday June 9, published Friday June 12 19:30 UTC (Future)
    not_yet_published = CotSnapshot(
        report_date="2026-06-09",
        captured_at=datetime(2026, 6, 10, 12, 0),
        published_at=datetime(2026, 6, 12, 19, 30),
        currency="XAU",
        net_long=200,
        open_interest=1000,
        net_long_pct=0.2,
        positioning="LONG",
    )
    # Prior week report: Tuesday June 2, published Friday June 5 19:30 UTC (Past)
    prior_published = CotSnapshot(
        report_date="2026-06-02",
        captured_at=datetime(2026, 6, 5, 20, 0),
        published_at=datetime(2026, 6, 5, 19, 30),
        currency="XAU",
        net_long=150,
        open_interest=1000,
        net_long_pct=0.15,
        positioning="LONG",
    )
    db.add_all([not_yet_published, prior_published])
    db.commit()

    selected = gold_model._latest_cot(db, "XAU", as_of)
    assert selected is not None
    assert selected.id == prior_published.id
