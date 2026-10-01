"""
scheduler.py — Automatic background scheduler for pre-release alerts and post-release grading.
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

import json
from database import (
    SessionLocal,
    Prediction as PredictionModel,
    AlertLog,
    is_pre_release_prediction,
)
from config.events import get_event_config
from indicators import build_composite_score
from calendar_feed import fetch_upcoming_red_folder_events
from alerts import send_telegram_alert, BOT_TOKEN, CHAT_ID
import requests

load_dotenv()
log = logging.getLogger("scheduler")

scheduler: Optional[BackgroundScheduler] = None


def grade_prediction(event_code: str, lean_direction: str, actual: float, forecast: float) -> tuple[bool, str]:
    """
    Strict mathematical evaluation of prediction outcome.
    Returns (was_correct: bool, explanation: str).
    Zero bias, zero falsification:
      - Standard events (NFP, CPI, Core CPI, PPI, Retail Sales, PMI, GDP):
          Higher actual = Positive economic surprise / Bullish USD
      - Inverse events (Jobless Claims, Unemployment Rate):
          Lower actual = Positive economic surprise / Bullish USD (fewer unemployed)
    """
    diff = round(actual - forecast, 4)
    lean = (lean_direction or "").upper()

    # Inverse indicators where lower print = economic strength / USD bullish
    is_inverse = event_code in ("JOBLESS_CLAIMS", "UNEMPLOYMENT_RATE")

    # Determine what actually happened
    if abs(diff) < 0.001:
        market_outcome = "INLINE"
    elif is_inverse:
        market_outcome = "BULLISH" if diff < 0 else "BEARISH"
    else:
        market_outcome = "BULLISH" if diff > 0 else "BEARISH"

    # Normalize lean
    if lean in ("BEAT", "BULLISH"):
        predicted_bias = "BULLISH"
    elif lean in ("MISS", "BEARISH"):
        predicted_bias = "BEARISH"
    else:
        predicted_bias = "INLINE"

    # Honest grading
    if predicted_bias == market_outcome:
        was_correct = True
        msg = f"Model accurately predicted {predicted_bias}. Actual ({actual}) matched leading indicator alignment vs forecast ({forecast})."
    else:
        was_correct = False
        if market_outcome == "INLINE":
            msg = f"Model predicted {predicted_bias}, but actual print matched forecast exactly ({actual} vs {forecast}). Result: INCORRECT."
        else:
            msg = f"Market surprised model! Model predicted {predicted_bias}, but actual print ({actual} vs {forecast}) resulted in {market_outcome} surprise. Result: INCORRECT / MISSED."

    return was_correct, msg


def send_outcome_alert(event_code: str, actual: float, forecast: float, was_correct: bool, lean_direction: str, verdict_explanation: str = ""):
    """Send outcome grading alert to Telegram after release with honest verdict."""
    if not BOT_TOKEN or not CHAT_ID:
        return

    verdict_tag = "🎯 PREDICTION WON (CORRECT)" if was_correct else "❌ PREDICTION MISSED (INCORRECT)"
    status_color = "🟢" if was_correct else "🔴"
    diff = actual - forecast
    diff_sign = "+" if diff > 0 else ""

    text = (
        f"{status_color} *REAL OUTCOME REPORT — {event_code}*\n\n"
        f"Result: *{verdict_tag}*\n"
        f"─────────────────────\n"
        f"Pre-Release Lean: `{lean_direction}`\n"
        f"Actual: `{actual}` | Forecast: `{forecast}` (Surprise: `{diff_sign}{diff:.2f}`)\n\n"
        f"📝 *Verdict:* _{verdict_explanation}_\n"
        f"─────────────────────\n"
        f"📊 Recorded directly into your historical hit-rate ledger (transparent & unedited)."
    )

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id":    CHAT_ID,
            "text":       text,
            "parse_mode": "Markdown",
        }, timeout=10)
    except Exception as e:
        log.error("Failed to send outcome alert: %s", e)


def check_and_alert_upcoming():
    """
    Called every 5 minutes by the background scheduler.
    1. Checks if any red-folder event is within ALERT_HOURS_BEFORE (default 2 hrs).
    2. Sends pre-release prediction if not already sent.
    3. Checks if any recent event has actual numbers published and grades accuracy.
    """
    try:
        hours_before = float(os.getenv("ALERT_HOURS_BEFORE", "2"))
    except ValueError:
        hours_before = 2.0

    db = SessionLocal()
    try:
        # Force-refresh so we pick up newly published actual values immediately
        events = fetch_upcoming_red_folder_events(force_refresh=True)
        now_utc = datetime.utcnow()

        for ev in events:
            code = ev.get("event_code")
            if not code:
                continue

            rel_str = ev.get("release_time_utc")
            if not rel_str:
                continue

            # Parse event release time
            try:
                # Forex Factory ISO format: 2026-09-30T08:30:00-04:00 or similar
                clean_time = rel_str.replace("Z", "+00:00")
                event_dt = datetime.fromisoformat(clean_time)
                # convert to naive UTC for comparison
                event_utc = event_dt.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception:
                continue

            time_diff = event_utc - now_utc
            hours_until = time_diff.total_seconds() / 3600.0

            # ── 1. PRE-RELEASE CHECK ──
            # If release is within the alert window (e.g. between 0 and 2.5 hours)
            if 0 < hours_until <= (hours_before + 0.5):
                already_sent = db.query(AlertLog).filter(
                    AlertLog.event_code == code,
                    AlertLog.release_time_str == rel_str,
                    AlertLog.alert_type == "PRE_RELEASE"
                ).first()

                if not already_sent:
                    log.info("Triggering automatic pre-release alert for %s (in %.1f hours)", code, hours_until)
                    try:
                        pred_result = build_composite_score(code)
                        existing_prediction = db.query(PredictionModel).filter(
                            PredictionModel.event_code == code,
                            PredictionModel.release_time_utc == rel_str,
                        ).first()
                        if not existing_prediction:
                            event_cfg = get_event_config(code)
                            db.add(PredictionModel(
                                created_at=now_utc,
                                event_code=code,
                                event_display_name=event_cfg.get("display_name", code),
                                release_time_utc=rel_str,
                                composite_score=pred_result["composite_score"],
                                lean_direction=pred_result["lean_direction"],
                                confidence_pct=pred_result["confidence_pct"],
                                indicator_breakdown=json.dumps(pred_result["indicator_breakdown"]),
                                forecast=ev.get("forecast"),
                                previous=ev.get("previous"),
                            ))
                            db.commit()

                        # send telegram
                        send_telegram_alert(pred_result, release_time=f"{event_utc.strftime('%H:%M')} UTC (in {int(hours_until * 60)}m)")
                        # log
                        alert_entry = AlertLog(
                            event_code=code,
                            release_time_str=rel_str,
                            alert_type="PRE_RELEASE"
                        )
                        db.add(alert_entry)
                        db.commit()
                    except Exception as err:
                        log.error("Error generating auto alert for %s: %s", code, err)

            # ── 2. POST-RELEASE GRADING CHECK ──
            # If actual number is now available
            actual = ev.get("actual")
            forecast = ev.get("forecast")
            if actual is not None and forecast is not None:
                recent_pred = db.query(PredictionModel).filter(
                    PredictionModel.event_code == code,
                    PredictionModel.release_time_utc == rel_str,
                    PredictionModel.was_correct == None
                ).order_by(PredictionModel.created_at.desc()).first()

                if recent_pred and is_pre_release_prediction(recent_pred):
                    surprise = round(actual - forecast, 4)
                    lean = recent_pred.lean_direction
                    was_correct, verdict_msg = grade_prediction(code, lean, actual, forecast)

                    recent_pred.was_correct = was_correct
                    recent_pred.actual = actual
                    recent_pred.forecast = forecast
                    recent_pred.surprise = surprise
                    recent_pred.actual_surprise = surprise
                    db.commit()

                    # Send outcome alert if not sent yet
                    post_alert_sent = db.query(AlertLog).filter(
                        AlertLog.event_code == code,
                        AlertLog.release_time_str == rel_str,
                        AlertLog.alert_type == "POST_RELEASE"
                    ).first()

                    if not post_alert_sent:
                        send_outcome_alert(code, actual, forecast, was_correct, lean, verdict_explanation=verdict_msg)
                        db.add(AlertLog(
                            event_code=code,
                            release_time_str=rel_str,
                            alert_type="POST_RELEASE"
                        ))
                        db.commit()

    except Exception as e:
        log.error("Scheduler run error: %s", e)
    finally:
        db.close()


def start_scheduler():
    global scheduler
    if scheduler is None or not scheduler.running:
        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(check_and_alert_upcoming, "interval", minutes=5, id="auto_alert_job")
        scheduler.start()
        log.info("Background alert scheduler started (running every 5 min)")


def stop_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown()
        log.info("Background alert scheduler stopped")
