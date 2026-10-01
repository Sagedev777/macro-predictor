"""
api.py — FastAPI backend serving prediction data, scheduler management, and historical accuracy.
"""

import json
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv

from database import (
    init_db,
    is_pre_release_prediction,
    SessionLocal,
    Prediction as PredictionModel,
    AlertLog,
)
from indicators import build_composite_score
from calendar_feed import fetch_upcoming_red_folder_events, update_event_actual
from alerts import send_telegram_alert, send_test_message
from config.events import EVENTS, get_event_config
from scheduler import start_scheduler, stop_scheduler, check_and_alert_upcoming, grade_prediction, send_outcome_alert

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")
import time

_api_pred_cache: dict[str, tuple[float, dict]] = {}
_API_PRED_TTL = 600  # 10 minutes cache

app = FastAPI(title="MacroPredictor API", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    start_scheduler()
    log.info("MacroPredictor API started with automatic background scheduler active")


@app.on_event("shutdown")
def shutdown():
    stop_scheduler()


@app.get("/api/health")
def health():
    fred_key = os.getenv("FRED_API_KEY", "")
    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    tg_chat  = os.getenv("TELEGRAM_CHAT_ID", "")
    hours_before = os.getenv("ALERT_HOURS_BEFORE", "2")
    return {
        "status": "ok",
        "fred_configured":     bool(fred_key and fred_key != "your_fred_key_here"),
        "telegram_configured": bool(tg_token and tg_chat and tg_token != "your_telegram_bot_token_here"),
        "alert_hours_before":  hours_before,
        "supported_events":    list(EVENTS.keys()),
        "scheduler_running":   True,
    }


@app.get("/api/events")
def get_upcoming_events(force_refresh: bool = False):
    """
    Return upcoming high-impact events from Forex Factory with exact release times,
    simultaneous release annotations, and automatically computed model predictions.
    Set ?force_refresh=true to bypass cache and pull the live feed immediately.
    """
    events = fetch_upcoming_red_folder_events(force_refresh=force_refresh)
    return _get_events_body(events)


@app.post("/api/events/sync-actuals")
def sync_actuals_from_feed():
    """
    Force a live refresh of the Forex Factory feed to auto-detect newly published
    actual values. Any event that now has an actual print will be automatically
    graded against its pre-release model prediction. No manual input needed.
    """
    events = fetch_upcoming_red_folder_events(force_refresh=True)
    graded = []
    db = SessionLocal()
    try:
        for ev in events:
            code = ev.get("event_code")
            actual = ev.get("actual")
            forecast = ev.get("forecast")
            release_time_utc = ev.get("release_time_utc")

            if not code or actual is None or forecast is None or not release_time_utc:
                continue

            event_cfg = get_event_config(code)

            existing_graded = db.query(PredictionModel).filter(
                PredictionModel.event_code == code,
                PredictionModel.release_time_utc == release_time_utc,
                PredictionModel.was_correct != None,
            ).first()

            if existing_graded:
                continue

            pred = (
                db.query(PredictionModel)
                .filter(
                    PredictionModel.event_code == code,
                    PredictionModel.release_time_utc == release_time_utc,
                    PredictionModel.was_correct == None,
                )
                .order_by(PredictionModel.created_at.desc())
                .first()
            )
            if not pred or not is_pre_release_prediction(pred):
                continue

            # Grade it
            was_correct, verdict_msg = grade_prediction(code, pred.lean_direction, actual, forecast)
            surprise = round(actual - forecast, 4)

            pred.actual = actual
            pred.forecast = forecast
            pred.surprise = surprise
            pred.actual_surprise = surprise
            pred.was_correct = was_correct
            db.commit()

            # Send Telegram outcome alert (de-duplicated via AlertLog)
            try:
                rel_str = ev.get("release_time_utc", "")
                post_sent = db.query(AlertLog).filter(
                    AlertLog.event_code == code,
                    AlertLog.release_time_str == rel_str,
                    AlertLog.alert_type == "POST_RELEASE",
                ).first()
                if not post_sent:
                    send_outcome_alert(code, actual, forecast, was_correct, pred.lean_direction, verdict_explanation=verdict_msg)
                    db.add(AlertLog(event_code=code, release_time_str=rel_str, alert_type="POST_RELEASE"))
                    db.commit()
            except Exception as te:
                log.warning("Telegram outcome alert failed for %s: %s", code, te)

            graded.append({
                "event_code": code,
                "display_name": event_cfg.get("display_name", code),
                "actual": actual,
                "forecast": forecast,
                "surprise": surprise,
                "was_correct": was_correct,
            })
            log.info("Auto-graded %s: actual=%s forecast=%s correct=%s", code, actual, forecast, was_correct)

        return {
            "success": True,
            "synced_events": len(events),
            "newly_graded": len(graded),
            "graded": graded,
        }
    finally:
        db.close()


def _get_events_body(events: list) -> dict:
    """Shared logic: annotate events with simultaneous flags and predictions."""

    # Group by release_time_utc to identify simultaneous releases
    time_groups = {}
    for ev in events:
        t_str = ev.get("release_time_utc")
        if t_str:
            time_groups.setdefault(t_str, []).append(ev)

    for ev in events:
        code = ev.get("event_code")
        t_str = ev.get("release_time_utc")

        # Annotate simultaneous release info
        simultaneous = [e for e in time_groups.get(t_str, []) if e.get("event_code") != code]
        ev["is_simultaneous"] = len(simultaneous) > 0
        ev["simultaneous_event_codes"] = [e.get("event_code") for e in simultaneous]
        ev["simultaneous_event_names"] = [e.get("event_name") for e in simultaneous]

        if code:
            cfg = get_event_config(code)
            ev["display_name"] = cfg.get("display_name", ev.get("event_name", code))
            ev["currency"]     = cfg.get("currency", "USD")

            # Attach model prediction for this event (cached for 10 min)
            now_ts = time.time()
            if code in _api_pred_cache and (now_ts - _api_pred_cache[code][0]) < _API_PRED_TTL:
                ev["prediction"] = _api_pred_cache[code][1]
            else:
                try:
                    pred = build_composite_score(code)
                    direction = pred["lean_direction"]
                    dir_key = "BULLISH" if direction in ("BEAT", "BULLISH") else ("BEARISH" if direction in ("MISS", "BEARISH") else "INLINE")

                    pred_data = {
                        "lean_direction":  direction,
                        "confidence_pct":  pred["confidence_pct"],
                        "composite_score": pred["composite_score"],
                        "event_label":     cfg.get("event_labels", {}).get(dir_key, direction),
                        "explanation":     cfg.get("explanations", {}).get(dir_key, ""),
                        "trade_signals":   cfg.get("trade_signals", {}).get(dir_key, []),
                        "indicators":      pred["indicator_breakdown"],
                    }
                    _api_pred_cache[code] = (now_ts, pred_data)
                    ev["prediction"] = pred_data
                except Exception as e:
                    log.warning("Could not compute prediction for %s: %s", code, e)
                    ev["prediction"] = None

    return {"count": len(events), "events": events}


class RecordActualPayload(BaseModel):
    event_code: Optional[str] = None
    event_name: Optional[str] = None
    actual: float
    forecast: Optional[float] = None
    release_time_utc: Optional[str] = None


@app.post("/api/events/record-actual")
def record_actual_api(payload: RecordActualPayload):
    """
    Record an actual release print and grade only a linked pre-release forecast.
    """
    code = payload.event_code.upper() if payload.event_code else None

    # 1. Update calendar feed cache (in-memory and disk)
    update_event_actual(code, payload.actual, payload.event_name)

    if not code:
        return {
            "success": True,
            "event_code": code,
            "event_name": payload.event_name,
            "actual": payload.actual,
            "message": "Recorded actual print in calendar cache."
        }

    if not payload.release_time_utc:
        return {
            "success": True,
            "event_code": code,
            "actual": payload.actual,
            "graded": False,
            "message": "Actual recorded; no release time was supplied to match a saved forecast.",
        }

    db = SessionLocal()
    try:
        pred = (
            db.query(PredictionModel)
            .filter(
                PredictionModel.event_code == code,
                PredictionModel.release_time_utc == payload.release_time_utc,
                PredictionModel.was_correct == None
            )
            .order_by(PredictionModel.created_at.desc())
            .first()
        )

        if not pred or not is_pre_release_prediction(pred):
            return {
                "success": True,
                "event_code": code,
                "actual": payload.actual,
                "graded": False,
                "message": "Actual recorded; no saved pre-release forecast matches this release.",
            }

        # Use the forecast paired with this release, not another event's forecast.
        forecast = payload.forecast
        if forecast is None:
            for ev in fetch_upcoming_red_folder_events():
                if (
                    ev.get("event_code") == code
                    and ev.get("release_time_utc") == payload.release_time_utc
                    and ev.get("forecast") is not None
                ):
                    forecast = ev.get("forecast")
                    break
        if forecast is None:
            forecast = pred.forecast
        if forecast is None:
            return {
                "success": True,
                "event_code": code,
                "actual": payload.actual,
                "graded": False,
                "message": "Actual recorded; forecast data is unavailable, so this release was not graded.",
            }

        was_correct, verdict_msg = grade_prediction(code, pred.lean_direction, payload.actual, forecast)
        surprise = round(payload.actual - forecast, 4)

        pred.actual = payload.actual
        pred.forecast = forecast
        pred.surprise = surprise
        pred.actual_surprise = surprise
        pred.was_correct = was_correct
        db.commit()

        try:
            send_outcome_alert(code, payload.actual, forecast, was_correct, pred.lean_direction, verdict_explanation=verdict_msg)
        except Exception as te:
            log.warning("Could not send Telegram outcome alert: %s", te)

        return {
            "success": True,
            "event_code": code,
            "display_name": pred.event_display_name,
            "actual": payload.actual,
            "forecast": forecast,
            "surprise": surprise,
            "lean_direction": pred.lean_direction,
            "was_correct": was_correct,
            "graded": True,
            "verdict": verdict_msg,
        }
    finally:
        db.close()



@app.get("/api/prediction/{event_code}")
def get_prediction(event_code: str, send_alert: bool = False):
    """Run the indicator engine for a specific event and return the prediction."""
    code = event_code.upper()
    cfg = get_event_config(code)

    try:
        result = build_composite_score(code)
    except Exception as e:
        log.error("Prediction failed for %s: %s", code, e)
        raise HTTPException(status_code=500, detail=str(e))

    direction = result["lean_direction"]
    dir_key = "BULLISH" if direction in ("BEAT", "BULLISH") else ("BEARISH" if direction in ("MISS", "BEARISH") else "INLINE")
    trade_signals = (
        cfg.get("trade_signals", {}).get(direction)
        or cfg.get("trade_signals", {}).get(dir_key, [])
    )
    event_label = (
        cfg.get("event_labels", {}).get(direction)
        or cfg.get("event_labels", {}).get(dir_key, direction)
    )
    explanation = (
        cfg.get("explanations", {}).get(direction)
        or cfg.get("explanations", {}).get(dir_key, "")
    )
    result["trade_signals"] = trade_signals
    result["event_label"] = event_label
    result["explanation"] = explanation

    # Persist to DB
    db = SessionLocal()
    pred = PredictionModel(
        event_code=code,
        event_display_name=cfg.get("display_name", code),
        composite_score=result["composite_score"],
        lean_direction=result["lean_direction"],
        confidence_pct=result["confidence_pct"],
        indicator_breakdown=json.dumps(result["indicator_breakdown"]),
    )
    db.add(pred)
    db.commit()
    db.refresh(pred)
    pred_id = pred.id
    created_at = pred.created_at.isoformat() if pred.created_at else None
    db.close()

    if send_alert:
        send_telegram_alert(result)

    return {
        "id":                  pred_id,
        "event_code":          code,
        "display_name":        EVENTS[code]["display_name"],
        "lean_direction":      result["lean_direction"],
        "event_label":         event_label,
        "explanation":         explanation,
        "confidence_pct":      result["confidence_pct"],
        "composite_score":     result["composite_score"],
        "trade_signals":       trade_signals,
        "indicator_breakdown": result["indicator_breakdown"],
        "indicators":          result["indicator_breakdown"],
        "created_at":          created_at,
    }


@app.post("/api/run-all")
def run_all_predictions(send_alerts: bool = False):
    """Run predictions for all supported events at once."""
    results = []
    for code in EVENTS:
        try:
            res = get_prediction(code, send_alert=send_alerts)
            results.append(res)
        except Exception as e:
            results.append({"event_code": code, "error": str(e)})
    return {"results": results}


@app.get("/api/predictions")
def list_predictions(limit: int = 30):
    """Return the most recent stored predictions from the DB (one latest prediction per event)."""
    db = SessionLocal()
    all_preds = (
        db.query(PredictionModel)
        .filter(PredictionModel.is_sample.is_(False))
        .order_by(PredictionModel.created_at.desc())
        .all()
    )
    db.close()

    seen_codes = set()
    preds = []
    for p in all_preds:
        if p.event_code not in seen_codes:
            seen_codes.add(p.event_code)
            preds.append(p)
            if len(preds) >= limit:
                break

    predictions_data = []
    for p in preds:
        cfg = get_event_config(p.event_code)
        dir_key = "BULLISH" if p.lean_direction in ("BEAT", "BULLISH") else ("BEARISH" if p.lean_direction in ("MISS", "BEARISH") else "INLINE")
        predictions_data.append({
            "id":               p.id,
            "event_code":       p.event_code,
            "display_name":     p.event_display_name or cfg.get("display_name", p.event_code),
            "lean_direction":   p.lean_direction,
            "event_label":      cfg.get("event_labels", {}).get(p.lean_direction) or cfg.get("event_labels", {}).get(dir_key, p.lean_direction),
            "explanation":      cfg.get("explanations", {}).get(p.lean_direction) or cfg.get("explanations", {}).get(dir_key, ""),
            "confidence_pct":   p.confidence_pct,
            "composite_score":  p.composite_score,
            "trade_signals":    cfg.get("trade_signals", {}).get(p.lean_direction) or cfg.get("trade_signals", {}).get(dir_key, []),
            "created_at":       p.created_at.isoformat() if p.created_at else None,
            "was_correct":      p.was_correct,
            "actual_surprise":  p.actual_surprise,
            "forecast":         p.forecast,
            "actual":           p.actual,
            "indicator_breakdown": json.loads(p.indicator_breakdown) if p.indicator_breakdown else [],
            "indicators":       json.loads(p.indicator_breakdown) if p.indicator_breakdown else [],
        })

    return {
        "count": len(predictions_data),
        "predictions": predictions_data,
    }


@app.get("/api/history")
def get_historical_outcomes(limit: int = 30):
    """Return outcomes for forecasts saved before their scheduled release."""
    db = SessionLocal()
    candidates = (
        db.query(PredictionModel)
        .filter(
            PredictionModel.was_correct != None,
            PredictionModel.is_sample.is_(False),
        )
        .order_by(PredictionModel.created_at.desc())
        .all()
    )
    graded_preds = [
        prediction for prediction in candidates
        if is_pre_release_prediction(prediction)
    ][:max(0, limit)]
    db.close()

    total = len(graded_preds)
    wins = sum(1 for p in graded_preds if p.was_correct is True)
    losses = sum(1 for p in graded_preds if p.was_correct is False)
    hit_rate = round((wins / total * 100), 1) if total > 0 else 0.0

    return {
        "total_graded": total,
        "wins": wins,
        "losses": losses,
        "hit_rate_pct": hit_rate,
        "history": [
            {
                "id": p.id,
                "event_code": p.event_code,
                "display_name": p.event_display_name,
                "lean_direction": p.lean_direction,
                "confidence_pct": p.confidence_pct,
                "composite_score": p.composite_score,
                "forecast": p.forecast,
                "actual": p.actual,
                "surprise": p.surprise,
                "was_correct": p.was_correct,
                "trade_signals": EVENTS.get(p.event_code, {}).get("trade_signals", {}).get(p.lean_direction, []),
                "date": p.release_time_utc,
            }
            for p in graded_preds
        ],
    }


@app.get("/api/accuracy")
def get_overall_accuracy():
    """Return accuracy for non-sample forecasts saved before their release."""
    db = SessionLocal()
    candidates = (
        db.query(PredictionModel)
        .filter(
            PredictionModel.was_correct != None,
            PredictionModel.is_sample.is_(False),
        )
        .all()
    )
    all_graded = [
        prediction for prediction in candidates
        if is_pre_release_prediction(prediction)
    ]
    db.close()

    total = len(all_graded)
    wins = sum(1 for p in all_graded if p.was_correct)
    hit_rate = round((wins / total * 100), 1) if total > 0 else 0.0

    # Group by event_code
    breakdown = {}
    for p in all_graded:
        code = p.event_code
        if code not in breakdown:
            breakdown[code] = {"total": 0, "wins": 0, "name": p.event_display_name}
        breakdown[code]["total"] += 1
        if p.was_correct:
            breakdown[code]["wins"] += 1

    event_stats = []
    for code, stats in breakdown.items():
        event_stats.append({
            "event_code": code,
            "display_name": stats["name"],
            "total": stats["total"],
            "wins": stats["wins"],
            "hit_rate_pct": round((stats["wins"] / stats["total"] * 100), 1) if stats["total"] > 0 else 0.0,
        })

    return {
        "total_predictions": total,
        "wins": wins,
        "losses": total - wins,
        "overall_hit_rate": hit_rate,
        "event_stats": sorted(event_stats, key=lambda x: x["hit_rate_pct"], reverse=True),
    }


@app.post("/api/scheduler/check-now")
def trigger_scheduler_check():
    """Force an immediate check for upcoming releases and Telegram alerts."""
    check_and_alert_upcoming()
    return {"status": "ok", "message": "Alert check triggered successfully"}


@app.post("/api/prediction/{event_code}/telegram")
def send_event_telegram(event_code: str):
    """Trigger a Telegram alert for a specific event."""
    code = event_code.upper()
    if code not in EVENTS:
        raise HTTPException(status_code=404, detail=f"Unknown event '{code}'")

    result = build_composite_score(code)
    direction = result["lean_direction"]
    # Normalize BEAT→BULLISH, MISS→BEARISH to match EVENTS config keys
    dir_key = "BULLISH" if direction in ("BEAT", "BULLISH") else ("BEARISH" if direction in ("MISS", "BEARISH") else "INLINE")
    trade_signals = EVENTS[code].get("trade_signals", {}).get(dir_key, [])
    result["trade_signals"] = trade_signals
    ok = send_telegram_alert(result)
    return {"success": ok, "event_code": code}


@app.post("/api/telegram/broadcast-all")
def broadcast_all_to_telegram():
    """Broadcast all event predictions to Telegram."""
    results = []
    for code in EVENTS:
        try:
            pred = build_composite_score(code)
            direction = pred["lean_direction"]
            # Normalize BEAT→BULLISH, MISS→BEARISH to match EVENTS config keys
            dir_key = "BULLISH" if direction in ("BEAT", "BULLISH") else ("BEARISH" if direction in ("MISS", "BEARISH") else "INLINE")
            trade_signals = EVENTS[code].get("trade_signals", {}).get(dir_key, [])
            pred["trade_signals"] = trade_signals
            ok = send_telegram_alert(pred)
            results.append({"event_code": code, "success": ok})
        except Exception as e:
            results.append({"event_code": code, "error": str(e), "success": False})
    return {"broadcast": results}


@app.post("/api/telegram/test")
def test_telegram():
    ok = send_test_message()
    return {"success": ok}


# ── Serve React frontend (MUST be last — catches all non-API routes) ──────────
_dist = os.path.join(os.path.dirname(__file__), "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
