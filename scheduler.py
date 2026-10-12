"""
scheduler.py — Background scheduler for pre-release alerts, post-release grading,
               USD macro release capture, gold outcomes, and data refresh.

Schedule summary:
  Every 1 min   — check_and_alert_upcoming()   (pre-release + post-release grading)
  Every 12 hr   — refresh_sentiment_cycle()     (GDELT + RSS lexicon sentiment)
  Every 168 hr  — refresh_cot_cycle()           (CFTC COT, released Fridays)

Legacy non-gold pair-strength refreshes are no longer scheduled.
"""

import json
import logging
import os
from datetime import datetime, time as datetime_time, timedelta, timezone
from typing import Optional

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from alerts import (
    BOT_TOKEN,
    CHAT_ID,
    send_telegram_alert,
    send_gold_prediction_alert,
    send_gold_outcome_alert,
)
from calendar_feed import fetch_upcoming_red_folder_events
from config.events import get_event_config
from database import (
    AlertLog,
    GoldForecast,
    PeriodicJobRun,
    Prediction as PredictionModel,
    SessionLocal,
    check_is_late,
    is_pre_release_prediction,
)
from indicators import build_composite_score
from price_data import parse_release_utc, process_and_grade_event_price_reactions

load_dotenv()
log = logging.getLogger("scheduler")

scheduler: Optional[BackgroundScheduler] = None


def is_numeric_event(ev: dict) -> bool:
    """
    Check if an event is a numeric economic data release.
    Events without numeric forecast and actual (FOMC minutes, speeches, statements)
    must not have predictions created.
    """
    code = (ev.get("event_code") or "").upper()
    name = (ev.get("event_name") or "").lower()

    # Exclude speeches, statements, minutes, hearings
    non_numeric_terms = ["speaks", "speech", "minute", "statement", "testimony", "press conference"]
    if any(t in name for t in non_numeric_terms):
        return False
    if any(t in code.lower() for t in ["speaks", "speech", "minute", "statement"]):
        return False

    forecast = ev.get("forecast")
    actual   = ev.get("actual")
    if forecast is None and actual is None:
        from config.events import EVENTS
        cfg = EVENTS.get(code)
        if not cfg or not cfg.get("history_series"):
            return False
        if code in ("FOMC_MINUTES", "FOMC_MEETING_MINUTES"):
            return False

    return True


# ══════════════════════════════════════════════════════════════════════════════
# GRADING LOGIC — preserved verbatim from original
# ══════════════════════════════════════════════════════════════════════════════

# Inverse-indicator set for USD events
_INVERSE_EVENTS = {
    # USD
    "JOBLESS_CLAIMS",
    "INITIAL_JOBLESS_CLAIMS",
    "CONTINUING_JOBLESS_CLAIMS",
    "UNEMPLOYMENT_RATE",
}


def grade_prediction(
    event_code:     str,
    lean_direction: str,
    actual:         float,
    forecast:       float,
) -> tuple[bool, str]:
    """
    Strict mathematical evaluation of prediction outcome.
    Returns (was_correct: bool, explanation: str).

    *** GRADING MATH UNCHANGED FROM ORIGINAL ***
    Inverse events: lower actual = positive surprise (unemployment/claims).
    All other events: higher actual = positive surprise.
    """
    diff = round(actual - forecast, 4)
    lean = (lean_direction or "").upper()

    is_inverse = event_code in _INVERSE_EVENTS

    if abs(diff) < 0.001:
        market_outcome = "INLINE"
    elif is_inverse:
        market_outcome = "BULLISH" if diff < 0 else "BEARISH"
    else:
        market_outcome = "BULLISH" if diff > 0 else "BEARISH"

    if lean in ("BEAT", "BULLISH"):
        predicted_bias = "BULLISH"
    elif lean in ("MISS", "BEARISH"):
        predicted_bias = "BEARISH"
    else:
        predicted_bias = "INLINE"

    if predicted_bias == market_outcome:
        was_correct = True
        msg = (
            f"Model accurately predicted {predicted_bias}. "
            f"Actual ({actual}) matched leading indicator alignment vs forecast ({forecast})."
        )
    else:
        was_correct = False
        if market_outcome == "INLINE":
            msg = (
                f"Model predicted {predicted_bias}, but actual print matched forecast "
                f"exactly ({actual} vs {forecast}). Result: INCORRECT."
            )
        else:
            msg = (
                f"Market surprised model! Model predicted {predicted_bias}, but actual "
                f"({actual} vs {forecast}) resulted in {market_outcome} surprise. "
                f"Result: INCORRECT / MISSED."
            )

    return was_correct, msg


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM RELEASE ALERTS
# ══════════════════════════════════════════════════════════════════════════════
def _send_release_alert_once(db, event_code: str, release_time: str,
                             alert_type: str, message: str) -> bool:
    """Reserve an alert key before sending so concurrent processes cannot duplicate it."""
    from sqlalchemy.exc import IntegrityError

    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram is not configured; %s alert was not sent", alert_type)
        return False
    db.add(AlertLog(
        event_code=event_code,
        release_time_str=release_time,
        alert_type=alert_type,
    ))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception:
        db.query(AlertLog).filter_by(
            event_code=event_code,
            release_time_str=release_time,
            alert_type=alert_type,
        ).delete()
        db.commit()
        log.exception("Failed sending %s alert for %s/%s", alert_type, event_code, release_time)
        return False


def send_actual_posted_alert(db, pred, actual: float, forecast: float) -> bool:
    """Send one immediate actual-versus-forecast update with the stored pre-release call."""
    message = _format_actual_posted_message(pred, actual, forecast)
    return _send_release_alert_once(
        db, pred.event_code, pred.release_time_utc, "ACTUAL_POSTED", message
    )


def _format_actual_posted_message(pred, actual: float, forecast: float) -> str:
    surprise = actual - forecast
    sign = "+" if surprise > 0 else ""
    return (
        f"ACTUAL POSTED — {pred.event_display_name or pred.event_code}\n"
        f"Actual: {actual} | Forecast: {forecast} | Surprise: {sign}{surprise:.4f}\n"
        f"Pre-release call: {pred.lean_direction or 'UNAVAILABLE'} "
        f"({pred.confidence_pct or 0:.0f}%)\n"
        "Price reaction result will follow after grading."
    )


def send_price_result_alert(db, pred) -> bool:
    """Send the short price-only result after price grading has completed."""
    message = _format_price_result_message(pred)
    if message is None:
        return False
    return _send_release_alert_once(
        db, pred.event_code, pred.release_time_utc, "PRICE_RESULT", message
    )


def _format_price_result_message(pred) -> Optional[str]:
    labels = {
        "CORRECT": "correct",
        "INCORRECT": "incorrect",
        "NO_CLEAR_MOVE": "no clear move",
    }
    result = (pred.result_15m or "").upper()
    if result not in labels or pred.price_graded_at is None:
        return None
    move = pred.usd_move_15m or "UNAVAILABLE"
    return (
        f"USD price result — {pred.event_code}: {labels[result]} "
        f"({move}, 15m)."
    )


# ══════════════════════════════════════════════════════════════════════════════
# XAU/USD PRE-RELEASE FORECAST SCHEDULE & TELEGRAM HEADS-UP
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_GOLD_ALERT_MINUTES = [60, 30, 15, 10]


def parse_release_dt_utc(release_time_str: str) -> Optional[datetime]:
    """
    Parse an ISO release time string and return a timezone-aware UTC datetime.
    Rejects strings without a time component (tentative / all-day events)
    to strictly prevent assuming releases occur at midnight.
    """
    if not release_time_str or not isinstance(release_time_str, str):
        return None
    s = release_time_str.strip()
    # Check if purely a date (YYYY-MM-DD) without time
    if len(s) == 10 and s.count("-") == 2:
        return None
    if "T" not in s and " " not in s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def get_gold_alert_minutes() -> list[int]:
    """Return configured heads-up alert thresholds in descending order."""
    raw = os.getenv("GOLD_ALERT_MINUTES_BEFORE", "60,30,15,10")
    try:
        tiers = [int(m.strip()) for m in raw.split(",") if m.strip()]
        return sorted(tiers, reverse=True) if tiers else DEFAULT_GOLD_ALERT_MINUTES
    except Exception:
        return DEFAULT_GOLD_ALERT_MINUTES


def process_pre_release_gold_predictions(
    db,
    events: list[dict],
    now_utc: Optional[datetime] = None,
    sender_func = None,
) -> list[str]:
    """
    For every eligible scheduled USD economic release:
      1. Pre-generate and persist GoldForecast at 1hr (<=60 mins) before scheduled release.
      2. Repeatedly send 1hr, 30m, 15m, and 10m heads-up alerts to Telegram.
      3. Save forecast BEFORE attempting Telegram delivery.
      4. Idempotently track notification status, attempts, and errors in AlertLog.
      5. Strictly reject past/released events and tentative/unknown times.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    tiers = get_gold_alert_minutes()
    max_lead_min = max(tiers) if tiers else 60

    # Group eligible USD events by release_time_utc
    groups: dict[str, list[dict]] = {}
    for ev in events:
        currency = (ev.get("currency") or "USD").upper()
        if currency != "USD":
            continue
        impact = (ev.get("impact") or "").upper()
        if impact not in ("HIGH", "MEDIUM"):
            continue
        if not is_numeric_event(ev):
            continue
        rel_str = ev.get("release_time_utc")
        if not rel_str:
            continue
        groups.setdefault(rel_str, []).append(ev)

    processed_moments = []
    for rel_str, release_group in groups.items():
        rel_dt = parse_release_dt_utc(rel_str)
        if rel_dt is None:
            # Unknown or tentative time - do not invent a release time
            continue

        if rel_dt <= now_utc:
            # Event already occurred or is currently releasing - do not send pre-release prediction
            continue

        minutes_until = (rel_dt - now_utc).total_seconds() / 60.0

        # Only process if within the max pre-release window (e.g. 60 min)
        if not (0 < minutes_until <= max_lead_min):
            continue

        # 1. Generate & persist GoldForecast (persisted before Telegram delivery)
        existing_gf = (
            db.query(GoldForecast)
            .filter_by(release_time_utc=rel_str)
            .first()
        )
        if not existing_gf:
            try:
                from gold_model import create_gold_forecast
                create_gold_forecast(db, release_group, now=now_utc)
                existing_gf = (
                    db.query(GoldForecast)
                    .filter_by(release_time_utc=rel_str)
                    .first()
                )
            except Exception as e:
                log.error("Failed to generate GoldForecast for %s: %s", rel_str, e)
                continue

        if not existing_gf:
            continue

        # 2. Check and dispatch appropriate heads-up tier
        scheduled_time_str = f"{rel_dt.strftime('%Y-%m-%d %H:%M')} UTC"

        for i, tier in enumerate(tiers):
            lower_bound = tiers[i + 1] if i + 1 < len(tiers) else 0
            if lower_bound < minutes_until <= tier:
                ok, err = send_gold_prediction_alert(
                    db,
                    existing_gf,
                    stage_minutes=tier,
                    scheduled_time_str=scheduled_time_str,
                    sender_func=sender_func,
                )
                if ok:
                    processed_moments.append(f"{rel_str}:{tier}m")
                break

    return processed_moments


# ══════════════════════════════════════════════════════════════════════════════
# CORE SCHEDULER JOB — every 1 minute
# ══════════════════════════════════════════════════════════════════════════════

def check_and_alert_upcoming():
    """
    Every 1 minute:
      0. Pre-release XAU/USD gold prediction & multi-stage heads-up alerts (60m, 30m, 15m, 10m).
      1. Pre-release USD economic composite score check (0-10m).
      2. Post-release grading when actuals appear.
      3. Sweep and grade gold outcomes >= 35m post-release with Telegram outcome alerts.
    """
    from learning import (
        capture_prediction_features,
        save_prediction_feature_snapshot,
        train_release_moment,
        _registry,
    )

    try:
        hours_before = float(os.getenv("ALERT_HOURS_BEFORE", "2"))
    except ValueError:
        hours_before = 2.0  # noqa: F841 — read for health endpoint compatibility

    db = SessionLocal()
    try:
        events = fetch_upcoming_red_folder_events(force_refresh=False)
        now_aware = datetime.now(timezone.utc)
        now_utc = now_aware.replace(tzinfo=None)

        # ── 0. PRE-RELEASE GOLD PREDICTIONS & MULTI-TIER HEADS-UP ────────────
        try:
            process_pre_release_gold_predictions(db, events, now_utc=now_aware)
        except Exception as pge:
            log.error("process_pre_release_gold_predictions error: %s", pge)

        for ev in events:
            code     = ev.get("event_code")
            currency = ev.get("currency") or "USD"
            if not code:
                continue

            # ── Impact filter: only HIGH and MEDIUM events trigger alerts ────
            impact = ev.get("impact", "")
            if impact not in ("HIGH", "MEDIUM"):
                continue

            # ── Numeric filter: skip speeches, minutes, statements ───────────
            if not is_numeric_event(ev):
                continue

            rel_str = ev.get("release_time_utc")
            if not rel_str:
                continue

            # Parse release time
            try:
                event_dt  = datetime.fromisoformat(rel_str.replace("Z", "+00:00"))
                event_utc = event_dt.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                continue

            minutes_until = (event_utc - now_utc).total_seconds() / 60.0

            # ── 1. PRE-RELEASE ALERT — fires at 0–10 minutes before release ──
            if 0 < minutes_until <= 10:
                already_sent = db.query(AlertLog).filter(
                    AlertLog.event_code      == code,
                    AlertLog.release_time_str== rel_str,
                    AlertLog.alert_type      == "PRE_RELEASE",
                ).first()

                if not already_sent:
                    log.info(
                        "Pre-release alert for %s (%s) in %.1f minutes.",
                        code, currency, minutes_until,
                    )
                    try:
                        pred_result = build_composite_score(code)
                        event_cfg   = get_event_config(code)

                        existing = db.query(PredictionModel).filter(
                            PredictionModel.event_code       == code,
                            PredictionModel.release_time_utc == rel_str,
                        ).first()

                        if not existing:
                            direction = pred_result["lean_direction"]
                            is_late_flag = check_is_late(now_utc, rel_str)
                            prediction = PredictionModel(
                                created_at          = now_utc,
                                event_code          = code,
                                event_display_name  = event_cfg.get("display_name", code),
                                release_time_utc    = rel_str,
                                composite_score     = pred_result["composite_score"],
                                lean_direction      = direction,
                                confidence_pct      = pred_result["confidence_pct"],
                                indicator_breakdown = json.dumps(pred_result["indicator_breakdown"]),
                                forecast            = ev.get("forecast"),
                                previous            = ev.get("previous"),
                                currency            = currency,
                                model_version       = "river_arf_v1",
                                is_late             = is_late_flag,
                            )
                            db.add(prediction)
                            db.flush()
                            features = capture_prediction_features(
                                currency,
                                float(pred_result.get(
                                    "indicator_score",
                                    pred_result.get("composite_score") or 0.0,
                                )),
                            )
                            save_prediction_feature_snapshot(db, prediction, features)
                            db.commit()

                        try:
                            from gold_model import create_gold_forecast

                            release_group = [
                                item for item in events
                                if item.get("release_time_utc") == rel_str
                            ]
                            create_gold_forecast(
                                db,
                                release_group,
                                now=now_utc.replace(tzinfo=timezone.utc),
                            )
                        except Exception:
                            log.exception(
                                "Gold reaction forecast failed for %s at %s",
                                code,
                                rel_str,
                            )

                        # Pass forecast/previous through for the new template
                        pred_result.setdefault("forecast", ev.get("forecast"))
                        pred_result.setdefault("previous", ev.get("previous"))

                        send_telegram_alert(
                            pred_result,
                            release_time=f"{event_utc.strftime('%H:%M')} UTC (in {int(minutes_until)}m)",
                        )
                        db.add(AlertLog(
                            event_code       = code,
                            release_time_str = rel_str,
                            alert_type       = "PRE_RELEASE",
                        ))
                        db.commit()
                    except Exception as err:
                        db.rollback()
                        log.error("Pre-release alert failed for %s: %s", code, err)

            # ── 2. POST-RELEASE ACTUALS STORAGE (Data only) ──────────────────
            actual   = ev.get("actual")
            forecast = ev.get("forecast")
            if actual is not None and forecast is not None:
                recent_pred = (
                    db.query(PredictionModel)
                    .filter(
                        PredictionModel.event_code       == code,
                        PredictionModel.release_time_utc == rel_str,
                    )
                    .order_by(PredictionModel.created_at.desc())
                    .first()
                )
                if recent_pred:
                    surprise = round(actual - forecast, 4)
                    recent_pred.actual          = actual
                    recent_pred.forecast        = forecast
                    recent_pred.surprise        = surprise
                    recent_pred.actual_surprise = surprise
                    db.commit()
                    send_actual_posted_alert(db, recent_pred, actual, forecast)

            # ── 3. PRICE REACTION GRADING (>= 65 mins after release) ─────────
            if minutes_until <= -65:
                pending_preds = (
                    db.query(PredictionModel)
                    .filter(
                        PredictionModel.event_code       == code,
                        PredictionModel.release_time_utc == rel_str,
                        PredictionModel.result_15m.is_(None),
                    )
                    .all()
                )
                for pred in pending_preds:
                    process_and_grade_event_price_reactions(code, rel_str, pred_id=pred.id)
                    db.refresh(pred)

                    if not is_pre_release_prediction(pred):
                        log.info(
                            "Skipping River training for %s (id=%s): late prediction (is_late=%s)",
                            code, pred.id, pred.is_late
                        )
                        continue

                    stats = train_release_moment(rel_str)
                    if stats:
                        try:
                            pred.weight_shift = stats.get("weight_shift_str")
                            db.commit()
                        except Exception as le:
                            log.warning("Failed to persist release grading for %s/%s: %s", code, currency, le)
                    try:
                        from gold_model import train_gold_outcome
                        train_gold_outcome(rel_str)
                    except Exception as ge:
                        log.warning("Failed gold model training for %s: %s", rel_str, ge)
                    send_price_result_alert(db, pred)
                    if pred.result_15m == "NO_CLEAR_MOVE":
                        log.info(
                            "Event %s move was %s (no clear move) — excluded from accuracy and learning",
                            code, pred.usd_move_15m,
                        )

        # ── 4. SWEEP PENDING DATABASE PREDICTIONS (>= 65 mins after release) ─
        pending_db_preds = (
            db.query(PredictionModel)
            .filter(
                PredictionModel.result_15m.is_(None),
                PredictionModel.release_time_utc.isnot(None),
            )
            .all()
        )
        for sp in pending_db_preds:
            sp_rel = parse_release_utc(sp.release_time_utc)
            if sp_rel and (now_utc - sp_rel).total_seconds() >= 65 * 60:
                process_and_grade_event_price_reactions(sp.event_code, sp.release_time_utc, pred_id=sp.id)
                db.refresh(sp)
                send_price_result_alert(db, sp)
                if is_pre_release_prediction(sp):
                    train_release_moment(sp.release_time_utc)
                    try:
                        from gold_model import train_gold_outcome
                        train_gold_outcome(sp.release_time_utc)
                    except Exception as ge:
                        log.warning("Failed gold model training for %s: %s", sp.release_time_utc, ge)

        # ── 5. SWEEP PENDING GOLD FORECASTS (>= 35 mins after release) ────────
        try:
            process_and_grade_gold_outcomes(db)
        except Exception as ge:
            log.warning("process_and_grade_gold_outcomes error: %s", ge)

    except Exception as e:
        log.error("check_and_alert_upcoming error: %s", e)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# SENTIMENT REFRESH (every 12 hours)
# ══════════════════════════════════════════════════════════════════════════════

def refresh_sentiment_cycle():
    """
    Pull GDELT + RSS articles and score USD sentiment using a local lexicon.
    Runs every 12 hours.
    """
    try:
        from sentiment import refresh_all_sentiment
        results = refresh_all_sentiment(hours=48)
        log.info(
            "Sentiment refreshed: %s",
            {
                ccy: f"net={round(r.net_score, 3)} n={r.article_count}"
                for ccy, r in results.items()
            },
        )
    except Exception as e:
        log.error("Sentiment refresh failed: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# COT REFRESH (weekly — Fridays after CFTC release)
# ══════════════════════════════════════════════════════════════════════════════

def refresh_cot_cycle():
    """
    Download and parse latest CFTC COT report via cot_reports library.
    Runs every 168 hours (weekly).  CFTC publishes Fridays ~15:30 ET.
    """
    try:
        from sentiment import refresh_all_cot
        results = refresh_all_cot()
        log.info(
            "COT refreshed: %s",
            {ccy: r.positioning for ccy, r in results.items()},
        )
    except Exception as e:
        log.error("COT refresh failed: %s", e)


PERIODIC_JOB_CADENCES = {
    "auto_alert_job": "every minute",
    "sentiment_job": "daily at 00:30 and 12:30 UTC",
    "cot_job": "Friday at 16:00 UTC",
}


def run_cron_jobs(now: Optional[datetime] = None) -> list[str]:
    """Run each due scheduler job once and persist its successful run timestamp."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    if now.tzinfo is not None:
        now = now.astimezone(timezone.utc).replace(tzinfo=None)

    jobs = {
        "sentiment_job": refresh_sentiment_cycle,
        "cot_job": refresh_cot_cycle,
    }
    from database import SessionLocal

    db = SessionLocal()
    due_jobs = []
    try:
        rows = {
            row.job_name: row.last_run_at
            for row in db.query(PeriodicJobRun).all()
        }
        last_cycle = rows.get("auto_alert_job")
        if last_cycle is None or (now - last_cycle).total_seconds() >= 55:
            due_jobs.append(("auto_alert_job", check_and_alert_upcoming))

        slots = {
            "sentiment_job": [
                datetime.combine(now.date(), datetime_time(0, 30)),
                datetime.combine(now.date(), datetime_time(12, 30)),
            ],
            "cot_job": (
                [datetime.combine(now.date(), datetime_time(16, 0))]
                if now.weekday() == 4 else []
            ),
        }
        for job_name, run_at_values in slots.items():
            last_run = rows.get(job_name)
            if any(
                now >= run_at
                and (last_run is None or last_run < run_at)
                for run_at in run_at_values
            ):
                due_jobs.append((job_name, jobs[job_name]))
    finally:
        db.close()

    completed = []
    for job_name, job in due_jobs:
        job()
        db = SessionLocal()
        try:
            row = db.get(PeriodicJobRun, job_name)
            if row is None:
                row = PeriodicJobRun(job_name=job_name)
                db.add(row)
            row.last_run_at = now
            db.commit()
            completed.append(job_name)
        except Exception:
            db.rollback()
            log.exception("Failed to persist last_run_at for %s", job_name)
            raise
        finally:
            db.close()
    return completed


# ══════════════════════════════════════════════════════════════════════════════
# SEED CHECK — run once on startup if models are untrained
# ══════════════════════════════════════════════════════════════════════════════

def process_and_grade_gold_outcomes(db=None, sender_func=None) -> list[str]:
    """
    Sweep pending GoldForecast rows where release is >= 35 minutes ago,
    grade their outcome via fetch_and_record_gold_outcome, trigger
    incremental learning via train_gold_outcome(), and send an outcome
    verification alert to Telegram (confirming truth or failed).
    """
    from database import GoldForecast as GoldForecastModel, SessionLocal
    from gold_model import train_gold_outcome
    from price_data import fetch_and_record_gold_outcome, parse_release_utc
    from alerts import send_gold_outcome_alert

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    graded = []
    try:
        now_utc = datetime.utcnow()
        pending = (
            db.query(GoldForecastModel)
            .filter(
                GoldForecastModel.outcome_recorded_at.is_(None),
                GoldForecastModel.release_time_utc.isnot(None),
            )
            .all()
        )
        for gf in pending:
            rel_dt = parse_release_utc(gf.release_time_utc)
            if not rel_dt:
                continue
            if (now_utc - rel_dt).total_seconds() >= 35 * 60:
                fetch_and_record_gold_outcome(gf.release_time_utc, db=db)
                db.refresh(gf)
                if gf.outcome_recorded_at is not None:
                    train_gold_outcome(gf.release_time_utc)
                    try:
                        send_gold_outcome_alert(db, gf, sender_func=sender_func)
                    except Exception as ae:
                        log.warning("Failed to send gold outcome alert for %s: %s", gf.release_time_utc, ae)
                    graded.append(gf.release_time_utc)
    finally:
        if close_db:
            db.close()
    return graded


def _rebuild_models_from_history():
    """Rebuild River state from eligible, grouped, point-in-time outcomes."""
    from learning import rebuild_model_from_history
    summary = rebuild_model_from_history()
    log.info("River history rebuild complete: %s", summary)
    try:
        from gold_model import rebuild_gold_model_from_history
        gold_summary = rebuild_gold_model_from_history()
        log.info("Gold model history rebuild complete: %s", gold_summary)
    except Exception as ge:
        log.warning("Gold model rebuild failed: %s", ge)


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════

def start_scheduler():
    global scheduler
    if scheduler is not None and scheduler.running:
        return

    scheduler = BackgroundScheduler(daemon=True)

    # Every 1 minute — pre/post release alerts + River learn_one()
    scheduler.add_job(
        check_and_alert_upcoming,
        trigger="interval",
        minutes=1,
        id="auto_alert_job",
    )

    # Every 12 hours — sentiment (00:00 and 12:00 UTC)
    scheduler.add_job(
        refresh_sentiment_cycle,
        trigger="cron",
        hour="0,12", minute=30,
        id="sentiment_job",
    )

    # Every Friday at 16:00 UTC — COT (after CFTC ~15:30 ET release)
    scheduler.add_job(
        refresh_cot_cycle,
        trigger="cron",
        day_of_week="fri", hour=16, minute=0,
        id="cot_job",
    )

    _rebuild_models_from_history()
    scheduler.start()

    log.info(
        "Scheduler started: release check=1min | sentiment=00:30/12:30 UTC | "
        "COT=Fri 16:00 UTC"
    )


def stop_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown()
        log.info("Background scheduler stopped.")
