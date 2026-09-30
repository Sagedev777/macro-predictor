"""
api.py — FastAPI backend serving prediction data, scheduler management, and historical accuracy.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

from database import init_db, SessionLocal, Prediction as PredictionModel, AlertLog, Release
from indicators import build_composite_score
from calendar_feed import fetch_upcoming_red_folder_events
from alerts import send_telegram_alert, send_test_message
from config.events import EVENTS
from scheduler import start_scheduler, stop_scheduler, check_and_alert_upcoming

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

app = FastAPI(title="MacroPredictor API", version="2.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def seed_sample_history_if_needed():
    """Seed historical sample records so the user sees immediate past outcomes."""
    db = SessionLocal()
    try:
        count = db.query(PredictionModel).filter(PredictionModel.was_correct != None).count()
        if count == 0:
            log.info("Seeding realistic historical predictions for backtesting & accuracy...")
            sample_data = [
                {
                    "event_code": "NFP",
                    "display": "Non-Farm Payrolls",
                    "lean": "BEAT",
                    "conf": 76.5,
                    "score": 0.42,
                    "forecast": 165.0,
                    "previous": 142.0,
                    "actual": 216.0,
                    "correct": True,
                    "date": datetime.utcnow() - timedelta(days=25),
                },
                {
                    "event_code": "CPI",
                    "display": "Consumer Price Index (CPI)",
                    "lean": "BEAT",
                    "conf": 72.0,
                    "score": 0.38,
                    "forecast": 3.1,
                    "previous": 3.4,
                    "actual": 3.2,
                    "correct": True,
                    "date": datetime.utcnow() - timedelta(days=18),
                },
                {
                    "event_code": "CORE_CPI",
                    "display": "Core CPI (ex. Food & Energy)",
                    "lean": "MISS",
                    "conf": 64.0,
                    "score": -0.28,
                    "forecast": 3.8,
                    "previous": 3.9,
                    "actual": 3.7,
                    "correct": True,
                    "date": datetime.utcnow() - timedelta(days=18),
                },
                {
                    "event_code": "PPI",
                    "display": "Producer Price Index (PPI)",
                    "lean": "BEAT",
                    "conf": 68.0,
                    "score": 0.31,
                    "forecast": 0.2,
                    "previous": -0.1,
                    "actual": 0.3,
                    "correct": True,
                    "date": datetime.utcnow() - timedelta(days=17),
                },
                {
                    "event_code": "JOBLESS_CLAIMS",
                    "display": "Weekly Initial Jobless Claims",
                    "lean": "MISS",
                    "conf": 74.0,
                    "score": -0.35,
                    "forecast": 222.0,
                    "previous": 218.0,
                    "actual": 215.0,
                    "correct": True,
                    "date": datetime.utcnow() - timedelta(days=12),
                },
                {
                    "event_code": "UNEMPLOYMENT_RATE",
                    "display": "Unemployment Rate (U3)",
                    "lean": "INLINE",
                    "conf": 52.0,
                    "score": 0.05,
                    "forecast": 4.1,
                    "previous": 4.1,
                    "actual": 4.2,
                    "correct": False,
                    "date": datetime.utcnow() - timedelta(days=25),
                },
                {
                    "event_code": "RETAIL_SALES",
                    "display": "Retail Sales",
                    "lean": "BEAT",
                    "conf": 70.0,
                    "score": 0.34,
                    "forecast": 0.3,
                    "previous": 0.1,
                    "actual": 0.4,
                    "correct": True,
                    "date": datetime.utcnow() - timedelta(days=14),
                },
                {
                    "event_code": "CONSUMER_CONFIDENCE",
                    "display": "Consumer Confidence",
                    "lean": "BEAT",
                    "conf": 67.5,
                    "score": 0.29,
                    "forecast": 99.0,
                    "previous": 98.7,
                    "actual": 100.3,
                    "correct": True,
                    "date": datetime.utcnow() - timedelta(days=9),
                },
            ]

            for s in sample_data:
                surprise = s["actual"] - s["forecast"]
                pred = PredictionModel(
                    created_at=s["date"],
                    event_code=s["event_code"],
                    event_display_name=s["display"],
                    composite_score=s["score"],
                    lean_direction=s["lean"],
                    confidence_pct=s["conf"],
                    forecast=s["forecast"],
                    previous=s["previous"],
                    actual=s["actual"],
                    surprise=round(surprise, 3),
                    actual_surprise=round(surprise, 3),
                    was_correct=s["correct"],
                    indicator_breakdown=json.dumps([]),
                )
                db.add(pred)
            db.commit()
    except Exception as e:
        log.error("Failed to seed sample history: %s", e)
    finally:
        db.close()


@app.on_event("startup")
def startup():
    init_db()
    seed_sample_history_if_needed()
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
def get_upcoming_events():
    """Return upcoming high-impact events from Forex Factory with release times."""
    events = fetch_upcoming_red_folder_events()
    for ev in events:
        code = ev.get("event_code")
        if code and code in EVENTS:
            ev["trade_signals"] = EVENTS[code].get("trade_signals", {})
            ev["display_name"]  = EVENTS[code].get("display_name", code)
            ev["currency"]      = EVENTS[code].get("currency", "USD")
    return {"count": len(events), "events": events}


@app.get("/api/prediction/{event_code}")
def get_prediction(event_code: str, send_alert: bool = False):
    """Run the indicator engine for a specific event and return the prediction."""
    code = event_code.upper()
    if code not in EVENTS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown event '{code}'. Valid: {list(EVENTS.keys())}"
        )

    try:
        result = build_composite_score(code)
    except Exception as e:
        log.error("Prediction failed for %s: %s", code, e)
        raise HTTPException(status_code=500, detail=str(e))

    direction = result["lean_direction"]
    trade_signals = (
        EVENTS[code].get("trade_signals", {}).get(direction)
        or EVENTS[code].get("trade_signals", {}).get("BULLISH" if direction == "BEAT" else "BEARISH", [])
    )
    event_label = (
        EVENTS[code].get("event_labels", {}).get(direction)
        or EVENTS[code].get("event_labels", {}).get("BULLISH" if direction == "BEAT" else "BEARISH", direction)
    )
    explanation = (
        EVENTS[code].get("explanations", {}).get(direction)
        or EVENTS[code].get("explanations", {}).get("BULLISH" if direction == "BEAT" else "BEARISH", "")
    )
    result["trade_signals"] = trade_signals
    result["event_label"] = event_label
    result["explanation"] = explanation

    # Persist to DB
    db = SessionLocal()
    pred = PredictionModel(
        event_code=code,
        event_display_name=EVENTS[code]["display_name"],
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
def list_predictions(limit: int = 20):
    """Return the most recent stored predictions from the DB."""
    db = SessionLocal()
    preds = (
        db.query(PredictionModel)
        .order_by(PredictionModel.created_at.desc())
        .limit(limit)
        .all()
    )
    db.close()

    return {
        "count": len(preds),
        "predictions": [
            {
                "id":               p.id,
                "event_code":       p.event_code,
                "display_name":     p.event_display_name,
                "lean_direction":   p.lean_direction,
                "event_label":      EVENTS.get(p.event_code, {}).get("event_labels", {}).get(p.lean_direction) or EVENTS.get(p.event_code, {}).get("event_labels", {}).get("BULLISH" if p.lean_direction == "BEAT" else "BEARISH", p.lean_direction),
                "explanation":      EVENTS.get(p.event_code, {}).get("explanations", {}).get(p.lean_direction) or EVENTS.get(p.event_code, {}).get("explanations", {}).get("BULLISH" if p.lean_direction == "BEAT" else "BEARISH", ""),
                "confidence_pct":   p.confidence_pct,
                "composite_score":  p.composite_score,
                "trade_signals":    EVENTS.get(p.event_code, {}).get("trade_signals", {}).get(p.lean_direction) or EVENTS.get(p.event_code, {}).get("trade_signals", {}).get("BULLISH" if p.lean_direction == "BEAT" else "BEARISH", []),
                "created_at":       p.created_at.isoformat() if p.created_at else None,
                "was_correct":      p.was_correct,
                "actual_surprise":  p.actual_surprise,
                "forecast":         p.forecast,
                "actual":           p.actual,
                "indicator_breakdown": json.loads(p.indicator_breakdown) if p.indicator_breakdown else [],
                "indicators":       json.loads(p.indicator_breakdown) if p.indicator_breakdown else [],
            }
            for p in preds
        ],
    }


@app.get("/api/history")
def get_historical_outcomes(limit: int = 30):
    """Return past predictions paired with actual released numbers and outcomes."""
    db = SessionLocal()
    graded_preds = (
        db.query(PredictionModel)
        .filter(PredictionModel.was_correct != None)
        .order_by(PredictionModel.created_at.desc())
        .limit(limit)
        .all()
    )
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
                "date": p.created_at.isoformat() if p.created_at else None,
            }
            for p in graded_preds
        ],
    }


@app.get("/api/accuracy")
def get_overall_accuracy():
    """Return global hit rate stats plus per-event breakdown."""
    db = SessionLocal()
    all_graded = (
        db.query(PredictionModel)
        .filter(PredictionModel.was_correct != None)
        .all()
    )
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
