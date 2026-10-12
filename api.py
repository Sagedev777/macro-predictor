"""
api.py — FastAPI backend for MacroPredictor.

The public interface is limited to U.S. macroeconomic releases and XAU/USD
reaction forecasts. Legacy pair-strength and order-suggestion routes have
been removed.
"""

import json
import logging
import os
import time
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from datetime import datetime, timezone

from alerts import send_telegram_alert, send_test_message
from calendar_feed import fetch_upcoming_red_folder_events, update_event_actual
from config.events import CURRENCIES, EVENTS, get_event_config
from database import (
    GoldForecast as GoldForecastModel,
    Prediction as PredictionModel,
    PriceReaction,
    SessionLocal,
    check_is_late,
    init_db,
    is_pre_release_prediction,
)
from indicators import (
    build_composite_score,
)
from learning import (
    get_grouped_release_moments,
)
from price_data import parse_release_utc, process_and_grade_event_price_reactions
from scheduler import (
    check_and_alert_upcoming,
    is_numeric_event,
    send_actual_posted_alert,
    send_price_result_alert,
    start_scheduler,
    stop_scheduler,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

# ── In-process caches ─────────────────────────────────────────────────────────
_api_pred_cache:    dict[str, tuple[float, dict]] = {}
_API_PRED_TTL  = 600    # 10 minutes — event prediction cache

app = FastAPI(title="MacroPredictor API", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# LIFECYCLE
# ══════════════════════════════════════════════════════════════════════════════

@app.on_event("startup")
def startup():
    init_db()
    if os.getenv("ENABLE_BACKGROUND_SCHEDULER", "true").strip().lower() in {
        "1", "true", "yes", "on",
    }:
        start_scheduler()
    else:
        log.info("In-process scheduler disabled; use run_tick.py cron runner.")
    log.info("MacroPredictor API v4 started — USD and XAU/USD mode active.")


@app.on_event("shutdown")
def shutdown():
    stop_scheduler()


# ══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
def health():
    fred_key    = os.getenv("FRED_API_KEY",          "")
    tg_token    = os.getenv("TELEGRAM_BOT_TOKEN",    "")
    tg_chat     = os.getenv("TELEGRAM_CHAT_ID",      "")
    td_key      = os.getenv("TWELVE_DATA_API_KEY",   "")
    hours_before= os.getenv("ALERT_HOURS_BEFORE",    "2")
    return {
        "status":                "ok",
        "version":               "4.0.0",
        "fred_configured":       bool(fred_key and fred_key != "your_fred_key_here"),
        "telegram_configured":   bool(tg_token and tg_chat),
        "twelve_data_configured":bool(td_key and td_key != "your_twelve_data_api_key_here"),
        "alert_hours_before":    hours_before,
        "supported_events":      list(EVENTS.keys()),
        "tracked_currencies":    CURRENCIES,
        "markets":               ["USD", "XAU/USD"],
        "scheduler_running": os.getenv(
            "ENABLE_BACKGROUND_SCHEDULER", "true"
        ).strip().lower() in {"1", "true", "yes", "on"},
    }


# ══════════════════════════════════════════════════════════════════════════════
# CALENDAR / EVENTS  (original endpoints — signatures unchanged)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/events")
def get_upcoming_events(force_refresh: bool = False):
    """
    Return upcoming red+orange folder events from Forex Factory.
    Predictions are NOT computed inline here — they are attached lazily
    only when already cached (TTL 10 min).  This keeps the response fast
    even with 30+ multi-currency events in the feed.
    """
    events = fetch_upcoming_red_folder_events(force_refresh=force_refresh)
    return _get_events_body(events)


@app.post("/api/events/sync-actuals")
def sync_actuals_from_feed():
    """
    Force a live Forex Factory refresh, auto-detect newly published actuals,
    store actual/forecast data for matching pre-release predictions.
    """
    from learning import train_release_moment

    events = fetch_upcoming_red_folder_events(force_refresh=True)
    recorded = []
    db     = SessionLocal()
    try:
        for ev in events:
            code             = ev.get("event_code")
            actual           = ev.get("actual")
            forecast         = ev.get("forecast")
            release_time_utc = ev.get("release_time_utc")
            currency         = ev.get("currency", "USD")

            if not code or actual is None or forecast is None or not release_time_utc:
                continue

            event_cfg = get_event_config(code)

            pred = (
                db.query(PredictionModel)
                .filter(
                    PredictionModel.event_code == code,
                    PredictionModel.release_time_utc == release_time_utc,
                )
                .order_by(PredictionModel.created_at.desc())
                .first()
            )
            if not pred:
                continue

            if not is_pre_release_prediction(pred):
                log.info(
                    "Skipping actual storage for %s (id=%s): late prediction (is_late=%s)",
                    code, pred.id, pred.is_late,
                )
                continue

            surprise = round(actual - forecast, 4)
            pred.actual          = actual
            pred.forecast        = forecast
            pred.surprise        = surprise
            pred.actual_surprise = surprise
            db.commit()
            send_actual_posted_alert(db, pred, actual, forecast)

            # If release was >= 65 mins ago, trigger price reaction grading
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            rel_dt = parse_release_utc(release_time_utc)
            if rel_dt and (now_utc - rel_dt).total_seconds() >= 65 * 60:
                process_and_grade_event_price_reactions(code, release_time_utc, pred_id=pred.id)
                db.refresh(pred)

                if is_pre_release_prediction(pred):
                    try:
                        train_release_moment(release_time_utc)
                    except Exception as le:
                        log.error("River release training failed for %s: %s", release_time_utc, le)

            send_price_result_alert(db, pred)

            recorded.append({
                "event_code":   code,
                "display_name": event_cfg.get("display_name", code),
                "currency":     currency,
                "actual":       actual,
                "forecast":     forecast,
                "surprise":     surprise,
            })

        return {
            "success":       True,
            "synced_events": len(events),
            "actuals_recorded": len(recorded),
            "recorded":      recorded,
        }
    finally:
        db.close()


def _get_events_body(events: list) -> dict:
    """
    Annotate calendar events with simultaneous flags and any ALREADY-CACHED
    predictions.  Does NOT call build_composite_score() inline — that would
    make a FRED API call per event and block the response for 30+ seconds
    with a full multi-currency calendar.

    Predictions are attached only when already present in _api_pred_cache
    (populated by /api/prediction/{event_code} or the scheduler).
    The frontend fetches predictions separately per event as needed.
    """
    time_groups: dict[str, list] = {}
    release_times = set()
    for ev in events:
        t_str = ev.get("release_time_utc")
        if t_str:
            time_groups.setdefault(t_str, []).append(ev)
            release_times.add(t_str)

    gold_by_release = {}
    if release_times:
        db = SessionLocal()
        try:
            from gold_model import _performance_summary, serialize_gold_forecast

            performance = _performance_summary(db)
            rows = (
                db.query(GoldForecastModel)
                .filter(GoldForecastModel.release_time_utc.in_(release_times))
                .all()
            )
            gold_by_release = {
                row.release_time_utc: serialize_gold_forecast(row)
                for row in rows
            }
            for forecast in gold_by_release.values():
                forecast["out_of_sample_performance"] = performance
        except Exception:
            log.exception("Could not attach stored gold reaction forecasts")
        finally:
            db.close()

    now_ts = time.time()

    for ev in events:
        code  = ev.get("event_code")
        t_str = ev.get("release_time_utc")
        ev["gold_forecast"] = gold_by_release.get(t_str)

        # Simultaneous release annotation
        simultaneous = [
            e for e in time_groups.get(t_str, [])
            if e.get("event_code") != code
        ]
        ev["is_simultaneous"]          = len(simultaneous) > 0
        ev["simultaneous_event_codes"] = [e.get("event_code") for e in simultaneous]
        ev["simultaneous_event_names"] = [e.get("event_name")  for e in simultaneous]

        if code:
            cfg = get_event_config(code)
            ev["display_name"] = cfg.get("display_name", ev.get("event_name", code))
            ev["currency"]     = ev.get("currency") or cfg.get("currency", "USD")

            # Attach prediction only if already cached — never compute inline
            cached = _api_pred_cache.get(code)
            if cached and (now_ts - cached[0]) < _API_PRED_TTL:
                ev["prediction"] = cached[1]
                if ev["gold_forecast"] is not None:
                    ev["prediction"]["gold_forecast"] = ev["gold_forecast"]
            else:
                ev["prediction"] = None   # frontend requests on-demand

    log.info("_get_events_body: returning %d events (%d with cached predictions)",
             len(events), sum(1 for e in events if e.get("prediction")))
    return {"count": len(events), "events": events}


def _create_gold_forecast(events: list, release_time_utc: str):
    from gold_model import create_gold_forecast

    release_events = [
        event for event in events
        if event.get("release_time_utc") == release_time_utc
    ]
    db = SessionLocal()
    try:
        return create_gold_forecast(db, release_events)
    except Exception:
        log.exception("Gold reaction forecast failed for %s", release_time_utc)
        return {
            "status": "unavailable",
            "direction": None,
            "probabilities": None,
            "expected_move_pct": None,
            "horizon_minutes": 5,
            "n_trained": 0,
            "validation_note": "Gold forecast generation failed; see server log.",
        }
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# RECORD ACTUAL  (original signature unchanged)
# ══════════════════════════════════════════════════════════════════════════════

class RecordActualPayload(BaseModel):
    event_code:       Optional[str]   = None
    event_name:       Optional[str]   = None
    actual:           float
    forecast:         Optional[float] = None
    release_time_utc: Optional[str]   = None
    currency:         Optional[str]   = None


@app.post("/api/events/record-actual")
def record_actual_api(payload: RecordActualPayload):
    """Record actual/forecast data; only price reaction determines prediction outcome."""
    from learning import train_release_moment

    code     = payload.event_code.upper() if payload.event_code else None
    currency = payload.currency.upper() if payload.currency else "USD"

    update_event_actual(code, payload.actual, payload.event_name)

    if not code:
        return {
            "success": True, "event_code": code,
            "event_name": payload.event_name, "actual": payload.actual,
            "message": "Recorded actual print in calendar cache.",
        }

    if not payload.release_time_utc:
        return {
            "success": True, "event_code": code, "actual": payload.actual,
            "graded": False,
            "message": "Actual recorded; no release time supplied to match a saved forecast.",
        }

    db = SessionLocal()
    try:
        pred = (
            db.query(PredictionModel)
            .filter(
                PredictionModel.event_code == code,
                PredictionModel.release_time_utc == payload.release_time_utc,
            )
            .order_by(PredictionModel.created_at.desc())
            .first()
        )
        if not pred or not is_pre_release_prediction(pred):
            return {
                "success": True, "event_code": code, "actual": payload.actual,
                "graded": False,
                "message": "Actual recorded; no saved pre-release forecast matches.",
            }

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
        pred.actual = payload.actual
        surprise = None
        if forecast is not None:
            surprise = round(payload.actual - forecast, 4)
            pred.forecast = forecast
            pred.surprise = surprise
            pred.actual_surprise = surprise
        db.commit()
        if forecast is not None:
            send_actual_posted_alert(db, pred, payload.actual, forecast)

        # If release was >= 65 mins ago, trigger price reaction grading
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        rel_dt = parse_release_utc(pred.release_time_utc)
        if rel_dt and (now_utc - rel_dt).total_seconds() >= 65 * 60:
            process_and_grade_event_price_reactions(code, pred.release_time_utc, pred_id=pred.id)
            db.refresh(pred)
            send_price_result_alert(db, pred)

            if is_pre_release_prediction(pred):
                try:
                    train_release_moment(pred.release_time_utc)
                except Exception as le:
                    log.error("River release training failed for %s: %s", pred.release_time_utc, le)

        return {
            "success":        True,
            "event_code":     code,
            "display_name":   pred.event_display_name,
            "actual":         payload.actual,
            "forecast":       forecast,
            "surprise":       surprise,
            "lean_direction": pred.lean_direction,
            "result_15m":     pred.result_15m,
            "actual_recorded": True,
            "price_graded":   pred.result_15m in ("CORRECT", "INCORRECT"),
        }
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# SINGLE-EVENT PREDICTION  (original signature unchanged, extended output)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/prediction/{event_code}")
def get_prediction(event_code: str, send_alert: bool = False):
    """Run the indicator engine for a specific event and return the prediction."""
    code = event_code.upper()
    cfg  = get_event_config(code)
    currency = cfg.get("currency", "USD")

    try:
        result = build_composite_score(code)
    except Exception as e:
        log.error("Prediction failed for %s: %s", code, e)
        raise HTTPException(status_code=500, detail=str(e))

    direction = result["lean_direction"]
    dir_key   = (
        "BULLISH" if direction in ("BEAT",  "BULLISH") else
        "BEARISH" if direction in ("MISS",  "BEARISH") else
        "INLINE"
    )
    event_label = (
        cfg.get("event_labels", {}).get(direction)
        or cfg.get("event_labels", {}).get(dir_key, direction)
    )
    explanation = ""
    # Pull calendar data for release time / forecast
    events           = fetch_upcoming_red_folder_events()
    release_time_utc = None
    forecast         = None
    for ev in events:
        if ev.get("event_code") == code:
            release_time_utc = ev.get("release_time_utc")
            forecast         = ev.get("forecast")
            break

    # Requirement 5: Do not create predictions for events with no numeric forecast and actual
    if not is_numeric_event({"event_code": code, "event_name": cfg.get("display_name", code), "forecast": forecast}):
        return {
            "event_code":   code,
            "display_name": cfg.get("display_name", code),
            "message":      "Predictions are disabled for non-numeric events (FOMC minutes, speeches, statements).",
        }

    # Persist to DB
    now_utc      = datetime.now(timezone.utc).replace(tzinfo=None)
    is_late_flag = check_is_late(now_utc, release_time_utc)
    from learning import capture_prediction_features, save_prediction_feature_snapshot
    point_in_time_features = capture_prediction_features(
        currency,
        float(result.get("indicator_score", result.get("composite_score") or 0.0)),
    )

    db   = SessionLocal()
    pred = PredictionModel(
        created_at          = now_utc,
        event_code          = code,
        event_display_name  = cfg.get("display_name", code),
        release_time_utc    = release_time_utc,
        forecast            = forecast,
        composite_score     = result["composite_score"],
        lean_direction      = result["lean_direction"],
        confidence_pct      = result["confidence_pct"],
        indicator_breakdown = json.dumps(result["indicator_breakdown"]),
        currency            = currency,
        model_version       = "river_arf_v1",
        is_late             = is_late_flag,
    )
    db.add(pred)
    db.flush()
    save_prediction_feature_snapshot(db, pred, point_in_time_features)
    db.commit()
    db.refresh(pred)
    pred_id    = pred.id
    created_at = pred.created_at.isoformat() if pred.created_at else None
    db.close()
    gold_forecast = _create_gold_forecast(events, release_time_utc)

    if send_alert:
        send_telegram_alert(result)

    return {
        "id":               pred_id,
        "event_code":       code,
        "display_name":     cfg.get("display_name", code),
        "currency":         currency,
        "lean_direction":   result["lean_direction"],
        "event_label":      event_label,
        "explanation":      explanation,
        "confidence_pct":   result["confidence_pct"],
        "composite_score":  result["composite_score"],
        "indicator_score":  result.get("indicator_score", 0.0),
        "indicator_breakdown": result["indicator_breakdown"],
        "indicators":       result["indicator_breakdown"],
        "gold_forecast":    gold_forecast,
        "created_at":       created_at,
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


# ══════════════════════════════════════════════════════════════════════════════
# PREDICTIONS LIST / HISTORY / ACCURACY  (original signatures unchanged)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/predictions")
def list_predictions(limit: int = 30):
    """Return the most recent stored predictions (one latest per event)."""
    db       = SessionLocal()
    all_preds = (
        db.query(PredictionModel)
        .filter(PredictionModel.is_sample.is_(False))
        .order_by(PredictionModel.created_at.desc())
        .all()
    )
    db.close()

    seen_codes: set[str] = set()
    preds: list = []
    for p in all_preds:
        if p.event_code not in seen_codes:
            seen_codes.add(p.event_code)
            preds.append(p)
            if len(preds) >= limit:
                break

    predictions_data = []
    for p in preds:
        cfg     = get_event_config(p.event_code)
        dir_key = (
            "BULLISH" if p.lean_direction in ("BEAT",  "BULLISH") else
            "BEARISH" if p.lean_direction in ("MISS",  "BEARISH") else
            "INLINE"
        )
        predictions_data.append({
            "id":               p.id,
            "event_code":       p.event_code,
            "display_name":     p.event_display_name or cfg.get("display_name", p.event_code),
            "currency":         p.currency or cfg.get("currency", "USD"),
            "lean_direction":   p.lean_direction,
            "event_label":      (
                cfg.get("event_labels", {}).get(p.lean_direction)
                or cfg.get("event_labels", {}).get(dir_key, p.lean_direction)
            ),
            "explanation":      "",
            "confidence_pct":   p.confidence_pct,
            "composite_score":  p.composite_score,
            "created_at":       p.created_at.isoformat() if p.created_at else None,
            "was_correct":      p.was_correct,
            "result_15m":       p.result_15m,
            "usd_move_15m":     p.usd_move_15m,
            "result_5m":        p.result_5m,
            "usd_move_5m":      p.usd_move_5m,
            "result_60m":       p.result_60m,
            "usd_move_60m":     p.usd_move_60m,
            "actual_surprise":  p.actual_surprise,
            "forecast":         p.forecast,
            "actual":           p.actual,
            "indicator_breakdown": (
                json.loads(p.indicator_breakdown) if p.indicator_breakdown else []
            ),
            "indicators": (
                json.loads(p.indicator_breakdown) if p.indicator_breakdown else []
            ),
        })

    return {"count": len(predictions_data), "predictions": predictions_data}


@app.get("/api/price-reactions")
def get_price_reactions(event_code: Optional[str] = None):
    """Return stored price reaction rows."""
    db = SessionLocal()
    try:
        q = db.query(PriceReaction).order_by(PriceReaction.fetched_at.desc())
        if event_code:
            release_times = [
                release_time for (release_time,) in db.query(
                    PredictionModel.release_time_utc
                ).filter(
                    PredictionModel.event_code == event_code,
                    PredictionModel.release_time_utc.isnot(None),
                ).distinct().all()
            ]
            if release_times:
                q = q.filter(PriceReaction.release_time_utc.in_(release_times))
            else:
                q = q.filter(PriceReaction.event_code == event_code)
        rows = q.limit(100).all()
        return [
            {
                "id":               r.id,
                "event_code":       event_code or r.event_code,
                "release_time_utc": r.release_time_utc,
                "symbol":           r.symbol,
                "price_at_release": r.price_at_release,
                "price_5m":         r.price_5m,
                "price_15m":        r.price_15m,
                "price_60m":        r.price_60m,
                "pct_change_5m":    r.pct_change_5m,
                "pct_change_15m":   r.pct_change_15m,
                "pct_change_60m":   r.pct_change_60m,
                "atr_15m":          r.atr_15m,
                "status":           r.status,
                "fetched_at":       r.fetched_at.isoformat() if r.fetched_at else None,
            }
            for r in rows
        ]
    finally:
        db.close()


@app.get("/api/history")
def get_historical_outcomes(limit: int = 30):
    """Return outcomes for forecasts saved before their scheduled release."""
    db         = SessionLocal()
    candidates = (
        db.query(PredictionModel)
        .filter(
            (PredictionModel.was_correct.isnot(None) | PredictionModel.result_15m.isnot(None)),
            PredictionModel.is_sample.is_(False),
            PredictionModel.is_late.is_(False),
        )
        .order_by(PredictionModel.created_at.desc())
        .all()
    )
    graded = [p for p in candidates if is_pre_release_prediction(p)][:max(0, limit)]
    db.close()

    evaluated_moments = [
        moment for moment in get_grouped_release_moments()
        if moment["hit"] is not None
    ]
    total     = len(evaluated_moments)
    wins      = sum(1 for moment in evaluated_moments if moment["hit"] is True)
    losses    = sum(1 for moment in evaluated_moments if moment["hit"] is False)
    hit_rate  = round((wins / total * 100), 1) if total > 0 else 0.0

    return {
        "total_graded":  total,
        "wins":          wins,
        "losses":        losses,
        "hit_rate_pct":  hit_rate,
        "history": [
            {
                "id":              p.id,
                "event_code":      p.event_code,
                "display_name":    p.event_display_name,
                "currency":        p.currency or "USD",
                "lean_direction":  p.lean_direction,
                "confidence_pct":  p.confidence_pct,
                "composite_score": p.composite_score,
                "forecast":        p.forecast,
                "actual":          p.actual,
                "surprise":        p.surprise,
                "was_correct":     p.was_correct,
                "result_15m":      p.result_15m or ("CORRECT" if p.was_correct is True else "INCORRECT" if p.was_correct is False else "NO_CLEAR_MOVE"),
                "usd_move_15m":    p.usd_move_15m,
                "result_5m":       p.result_5m,
                "usd_move_5m":     p.usd_move_5m,
                "result_60m":      p.result_60m,
                "usd_move_60m":    p.usd_move_60m,
                "status":          "no clear move" if p.result_15m == "NO_CLEAR_MOVE" else ("CORRECT" if p.was_correct is True else "INCORRECT" if p.was_correct is False else "PENDING"),
                "date":            p.release_time_utc,
                "is_late":         p.is_late,
                "weight_shift":    p.weight_shift,
            }
            for p in graded
        ],
    }


@app.get("/api/accuracy")
def get_overall_accuracy():
    """Return accuracy stats with each clear price-graded release counted once."""
    evaluated = [
        moment for moment in get_grouped_release_moments()
        if moment["hit"] is not None
    ]
    total     = len(evaluated)
    wins      = sum(1 for moment in evaluated if moment["hit"] is True)
    hit_rate  = round((wins / total * 100), 1) if total > 0 else 0.0

    # Group simultaneous event codes together so a release is still one observation.
    breakdown:          dict[str, dict]  = {}
    confidence_buckets: dict[str, dict]  = {
        "<60%":   {"total": 0, "wins": 0},
        "60-70%": {"total": 0, "wins": 0},
        "70-80%": {"total": 0, "wins": 0},
        ">80%":   {"total": 0, "wins": 0},
    }
    currency_breakdown: dict[str, dict] = {}

    for moment in evaluated:
        predictions = moment["predictions"]
        codes = moment["event_codes"]
        code_key = " + ".join(codes)
        names = sorted({
            p.event_display_name or p.event_code for p in predictions
        })
        breakdown.setdefault(
            code_key, {"total": 0, "wins": 0, "name": " + ".join(names)}
        )
        breakdown[code_key]["total"] += 1
        if moment["hit"] is True:
            breakdown[code_key]["wins"] += 1

        ccy = "USD"
        currency_breakdown.setdefault(ccy, {"total": 0, "wins": 0})
        currency_breakdown[ccy]["total"] += 1
        if moment["hit"] is True:
            currency_breakdown[ccy]["wins"] += 1

        confidence = moment["confidence_pct"]
        bucket = (
            "<60%"   if confidence < 60 else
            "60-70%" if confidence < 70 else
            "70-80%" if confidence < 80 else
            ">80%"
        )
        confidence_buckets[bucket]["total"] += 1
        if moment["hit"] is True:
            confidence_buckets[bucket]["wins"] += 1

    event_stats = [
        {
            "event_code":   code,
            "display_name": stats["name"],
            "total":        stats["total"],
            "wins":         stats["wins"],
            "hit_rate_pct": round(stats["wins"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0.0,
        }
        for code, stats in breakdown.items()
    ]
    currency_stats = [
        {
            "currency":     ccy,
            "total":        stats["total"],
            "wins":         stats["wins"],
            "hit_rate_pct": round(stats["wins"] / stats["total"] * 100, 1) if stats["total"] > 0 else 0.0,
        }
        for ccy, stats in currency_breakdown.items()
    ]
    confidence_stats = [
        {
            "bucket":       bucket,
            "total":        stats["total"],
            "wins":         stats["wins"],
            "hit_rate_pct": round(stats["wins"] / stats["total"] * 100, 1),
        }
        for bucket, stats in confidence_buckets.items()
        if stats["total"] > 0
    ]

    return {
        "total_predictions":  total,
        "total_release_moments": total,
        "wins":               wins,
        "losses":             total - wins,
        "overall_hit_rate":   hit_rate,
        "event_stats":        sorted(event_stats,    key=lambda x: x["hit_rate_pct"], reverse=True),
        "currency_stats":     sorted(currency_stats, key=lambda x: x["hit_rate_pct"], reverse=True),
        "confidence_stats":   confidence_stats,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER / TELEGRAM  (original signatures unchanged)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/model-status")
def get_model_status():
    """
    Per-currency River model status.
    Returns n_trained, live_accuracy, feature_weights, and rebuild provenance.
    """
    from database import SessionLocal, RiverModelState
    from learning import get_last_rebuild_summary
    db = SessionLocal()
    try:
        rows = {r.currency: r for r in db.query(RiverModelState).all()}
    finally:
        db.close()

    result = []
    for ccy in CURRENCIES:
        row = rows.get(ccy)
        import json as _json
        fw = {}
        if row and row.feature_weights:
            try: fw = _json.loads(row.feature_weights)
            except Exception: pass
        result.append({
            "currency":        ccy,
            "n_trained":       row.n_trained      if row else 0,
            "n_real":          row.n_trained      if row else 0,
            "live_accuracy":   row.live_accuracy  if row else None,
            "feature_weights": fw,
            "last_updated":    row.updated_at.isoformat() if row and row.updated_at else None,
            "status":          ("learning" if row and (row.n_trained or 0) > 0 else "untrained"),
        })
    return {
        "currencies": result,
        "training_rebuild": get_last_rebuild_summary(),
    }


@app.get("/api/gold/forecasts")
def list_gold_forecasts(
    limit: int = 50,
    offset: int = 0,
    event_family: Optional[str] = None,
    status: Optional[str] = None,
    direction: Optional[str] = None,
    search: Optional[str] = None,
):
    """List stored XAU/USD release-moment forecasts and evaluated outcomes with pagination and filtering."""
    if limit < 1 or limit > 200:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 200")
    if offset < 0:
        raise HTTPException(status_code=422, detail="offset must be >= 0")
    from gold_model import serialize_gold_forecast

    db = SessionLocal()
    try:
        query = db.query(GoldForecastModel)
        if event_family:
            query = query.filter(GoldForecastModel.event_family == event_family.lower())
        if status:
            if status == "graded":
                query = query.filter(GoldForecastModel.outcome_recorded_at.isnot(None), GoldForecastModel.outcome_status == "ok")
            elif status == "pending":
                query = query.filter(GoldForecastModel.outcome_recorded_at.is_(None), GoldForecastModel.outcome_status == "pending")
            elif status == "unavailable":
                query = query.filter(GoldForecastModel.outcome_status == "unavailable")
        if direction:
            query = query.filter(GoldForecastModel.forecast_direction == direction.upper())
        if search:
            s = f"%{search.strip().lower()}%"
            query = query.filter(
                (GoldForecastModel.release_moment_id.ilike(s))
                | (GoldForecastModel.event_codes_json.ilike(s))
                | (GoldForecastModel.event_names_json.ilike(s))
                | (GoldForecastModel.release_time_utc.ilike(s))
            )
        total = query.count()
        rows = (
            query.order_by(GoldForecastModel.release_time_utc.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "count": len(rows),
            "total": total,
            "offset": offset,
            "limit": limit,
            "forecasts": [serialize_gold_forecast(row, db) for row in rows],
        }
    finally:
        db.close()


@app.get("/api/gold/forecast/{release_id}")
def get_gold_forecast_detail(release_id: str):
    """Get complete, immutable point-in-time record for a specific release moment."""
    from database import GoldForecast as GF, GoldModelTraining as GMT, Prediction as P
    from gold_model import serialize_gold_forecast

    db = SessionLocal()
    try:
        row = db.query(GF).filter(
            (GF.release_moment_id == release_id) | (GF.release_time_utc == release_id)
        ).first()
        if not row:
            raise HTTPException(status_code=404, detail="Gold forecast not found")

        serialized = serialize_gold_forecast(row, db)

        training_row = db.get(GMT, row.release_time_utc)
        serialized["training_ledger"] = {
            "is_trained": bool(training_row and training_row.trained_at is not None),
            "claimed_at": training_row.claimed_at.isoformat() if training_row and training_row.claimed_at else None,
            "trained_at": training_row.trained_at.isoformat() if training_row and training_row.trained_at else None,
        }

        usd_preds = db.query(P).filter(P.release_time_utc == row.release_time_utc).all()
        serialized["linked_usd_predictions"] = [
            {
                "id": p.id,
                "event_code": p.event_code,
                "event_display_name": p.event_display_name,
                "lean_direction": p.lean_direction,
                "forecast": p.forecast,
                "previous": p.previous,
                "actual": p.actual,
                "surprise": p.surprise,
                "was_correct": p.was_correct,
                "result_15m": p.result_15m,
                "usd_move_15m": p.usd_move_15m,
                "confidence_pct": p.confidence_pct,
            }
            for p in usd_preds
        ]
        return serialized
    finally:
        db.close()


@app.get("/api/gold/evaluation")
def get_gold_evaluation():
    """Chronological walk-forward evaluation metrics (Brier, baseline, by family)."""
    from gold_model import get_walkforward_evaluation
    return get_walkforward_evaluation()


@app.get("/api/gold/insights")
def get_gold_insights():
    """Evidence-based historical reaction findings grouped by event family and surprise category."""
    from database import GoldForecast as GF
    import numpy as np

    db = SessionLocal()
    try:
        rows = (
            db.query(GF)
            .filter(
                GF.outcome_recorded_at.isnot(None),
                GF.gold_change_5m_pct.isnot(None),
            )
            .order_by(GF.release_time_utc.asc())
            .all()
        )
        if len(rows) < 3:
            return {
                "has_sufficient_data": False,
                "sample_size": len(rows),
                "message": "Insufficient data to compute evidence-based empirical insights. At least 3 graded outcomes are required.",
                "by_family": {},
                "return_distribution": {},
                "direction_frequencies": {},
            }

        returns_5m = [float(r.gold_change_5m_pct) for r in rows]
        returns_5m_sorted = sorted(returns_5m)
        n = len(returns_5m_sorted)

        median_ret = float(np.median(returns_5m))
        p25 = float(np.percentile(returns_5m, 25))
        p75 = float(np.percentile(returns_5m, 75))
        min_ret = returns_5m_sorted[0]
        max_ret = returns_5m_sorted[-1]

        labels = [r.outcome_label or "NEUTRAL" for r in rows]
        direction_counts = {
            "BULLISH": labels.count("BULLISH"),
            "BEARISH": labels.count("BEARISH"),
            "NEUTRAL": labels.count("NEUTRAL"),
        }
        direction_pcts = {
            k: round(v / n * 100, 1) for k, v in direction_counts.items()
        }

        by_family = {}
        families = set(r.event_family for r in rows)
        for fam in sorted(families):
            fam_rows = [r for r in rows if r.event_family == fam]
            fam_returns = [float(r.gold_change_5m_pct) for r in fam_rows]
            fam_labels = [r.outcome_label or "NEUTRAL" for r in fam_rows]
            by_family[fam] = {
                "count": len(fam_rows),
                "median_return_5m_pct": round(float(np.median(fam_returns)), 3),
                "avg_abs_move_pct": round(float(np.mean([abs(x) for x in fam_returns])), 3),
                "bullish_count": fam_labels.count("BULLISH"),
                "bearish_count": fam_labels.count("BEARISH"),
                "neutral_count": fam_labels.count("NEUTRAL"),
            }

        by_surprise = {"beat": [], "miss": [], "inline": []}
        for r in rows:
            surprises = []
            try:
                releases = json.loads(r.actual_release_json or "[]")
                for rel in releases:
                    if rel.get("actual") is not None and rel.get("forecast") is not None:
                        surprises.append(rel["actual"] - rel["forecast"])
            except Exception:
                pass
            if surprises:
                mean_surp = sum(surprises) / len(surprises)
                if mean_surp > 0.05:
                    by_surprise["beat"].append(r.gold_change_5m_pct)
                elif mean_surp < -0.05:
                    by_surprise["miss"].append(r.gold_change_5m_pct)
                else:
                    by_surprise["inline"].append(r.gold_change_5m_pct)

        surprise_summary = {
            k: {
                "count": len(v),
                "median_return_pct": round(float(np.median(v)), 3) if v else None,
                "avg_abs_move_pct": round(float(np.mean([abs(x) for x in v])), 3) if v else None,
            }
            for k, v in by_surprise.items()
        }

        return {
            "has_sufficient_data": True,
            "sample_size": n,
            "date_range": {
                "from": rows[0].release_time_utc,
                "to": rows[-1].release_time_utc,
            },
            "return_distribution": {
                "min": round(min_ret, 3),
                "p25": round(p25, 3),
                "median": round(median_ret, 3),
                "p75": round(p75, 3),
                "max": round(max_ret, 3),
            },
            "direction_frequencies": {
                "counts": direction_counts,
                "percentages": direction_pcts,
            },
            "by_family": by_family,
            "by_surprise": surprise_summary,
            "disclaimer": "Descriptive historical findings based exclusively on persisted release observations. Small-sample patterns are not predictive trading rules.",
        }
    finally:
        db.close()


@app.get("/api/gold/activity")
def get_gold_activity(limit: int = 40):
    """Timestamped model lifecycle activity: forecast creation, grading, training, alerts."""
    from database import GoldForecast as GF, GoldModelTraining as GMT, AlertLog as AL, PeriodicJobRun as PJR

    db = SessionLocal()
    try:
        events = []
        for f in db.query(GF).order_by(GF.created_at.desc()).limit(limit).all():
            events.append({
                "timestamp": f.created_at.isoformat() if f.created_at else None,
                "type": "forecast_created",
                "title": f"Forecast Generated: {f.event_family.upper()}",
                "description": f"Predicted {f.forecast_direction or 'NEUTRAL'} for {f.release_time_utc}",
                "moment_id": f.release_moment_id,
                "status": f.forecast_status,
            })
            if f.outcome_recorded_at:
                events.append({
                    "timestamp": f.outcome_recorded_at.isoformat(),
                    "type": "outcome_graded",
                    "title": f"Outcome Graded: {f.outcome_label or 'UNKNOWN'}",
                    "description": f"XAU/USD 5m change: {f.gold_change_5m_pct:.2f}% (Status: {f.outcome_status})",
                    "moment_id": f.release_moment_id,
                    "status": f.outcome_status,
                })
        for t in db.query(GMT).order_by(GMT.claimed_at.desc()).limit(limit).all():
            if t.trained_at:
                events.append({
                    "timestamp": t.trained_at.isoformat(),
                    "type": "model_trained",
                    "title": "Incremental Learning Committed",
                    "description": f"Trained observation for release moment {t.release_time_utc}",
                    "moment_id": t.release_time_utc,
                    "status": "trained",
                })
        for a in db.query(AL).order_by(AL.sent_at.desc()).limit(limit).all():
            events.append({
                "timestamp": a.sent_at.isoformat() if a.sent_at else None,
                "type": "alert_sent",
                "title": f"Telegram Alert: {a.alert_type}",
                "description": f"Sent alert for {a.event_code} ({a.release_time_str or ''})",
                "moment_id": a.release_time_str,
                "status": "sent",
            })

        events.sort(key=lambda x: x["timestamp"] or "", reverse=True)
        return {"activity": events[:limit]}
    finally:
        db.close()


@app.get("/api/sources/status")
def get_sources_status():
    """Authoritative status, freshness, and availability of all data sources."""
    from database import CotSnapshot, SentimentSnapshot, PriceReaction

    db = SessionLocal()
    try:
        cot = db.query(CotSnapshot).filter(CotSnapshot.currency == "XAU").order_by(CotSnapshot.captured_at.desc()).first()
        sent = db.query(SentimentSnapshot).order_by(SentimentSnapshot.recorded_at.desc()).first()
        px = db.query(PriceReaction).filter(PriceReaction.symbol == "XAUUSD").order_by(PriceReaction.fetched_at.desc()).first()

        td_key = bool(os.getenv("TWELVE_DATA_API_KEY", "").strip())
        fred_key = bool(os.getenv("FRED_API_KEY", "").strip())

        return {
            "sources": [
                {
                    "name": "Twelve Data (XAU/USD)",
                    "type": "Market Price Candles",
                    "status": "configured" if td_key else "missing_api_key",
                    "last_fetch": px.fetched_at.isoformat() if px and px.fetched_at else None,
                    "coverage": "1-minute OHLC, 15-minute ATR(14)",
                    "latency": "Real-time / 1-minute close",
                    "is_integrated": True,
                    "model_usage": "Target outcome label generation, excursion tracking, and returns",
                },
                {
                    "name": "Forex Factory",
                    "type": "Economic Calendar & Consensus",
                    "status": "configured",
                    "last_fetch": datetime.now(timezone.utc).isoformat(),
                    "coverage": "USD High/Medium impact events, previous, forecast, actual",
                    "latency": "10-minute cache TTL, live sync on demand",
                    "is_integrated": True,
                    "model_usage": "Event triggers, consensus snapshots, surprise features",
                },
                {
                    "name": "Federal Reserve Economic Data (FRED)",
                    "type": "Treasury Yields & Spreads",
                    "status": "configured" if fred_key else "missing_api_key",
                    "last_fetch": datetime.now(timezone.utc).isoformat() if fred_key else None,
                    "coverage": "DGS2 (2-Year Treasury), DFII10 (10-Year TIPS Real Yield)",
                    "latency": "Daily close",
                    "is_integrated": True,
                    "model_usage": "Macro regime and yield context features",
                },
                {
                    "name": "News & Lexicon Sentiment",
                    "type": "GDELT & RSS News Feed",
                    "status": "configured",
                    "last_fetch": sent.recorded_at.isoformat() if sent and sent.recorded_at else None,
                    "coverage": "48-hour rolling window, local USD financial dictionary",
                    "latency": "Refreshed every 12 hours (00:30 & 12:30 UTC)",
                    "is_integrated": True,
                    "model_usage": "Pre-release USD market sentiment score",
                },
                {
                    "name": "CFTC COMEX Gold COT",
                    "type": "Futures Positioning",
                    "status": "configured" if cot else "pending_first_cycle",
                    "last_fetch": cot.captured_at.isoformat() if cot and cot.captured_at else None,
                    "coverage": "Report date: " + (cot.report_date if cot else "N/A"),
                    "publication_time": cot.published_at.isoformat() if cot and cot.published_at else "Unavailable",
                    "latency": "Weekly release (Fridays ~15:30 ET / 16:00 UTC job)",
                    "is_integrated": True,
                    "model_usage": "Institutional positioning and net-long percentage",
                },
                {
                    "name": "CME FedWatch",
                    "type": "Fed Rate Probabilities",
                    "status": "provider_not_integrated",
                    "last_fetch": None,
                    "coverage": "None (values explicitly withheld)",
                    "latency": "N/A",
                    "is_integrated": False,
                    "model_usage": "Marked explicitly unavailable — not synthesized or zeroed",
                },
                {
                    "name": "CME Gold Options Implied Volatility",
                    "type": "Options Volatility Surface",
                    "status": "provider_not_integrated",
                    "last_fetch": None,
                    "coverage": "None (values explicitly withheld)",
                    "latency": "N/A",
                    "is_integrated": False,
                    "model_usage": "Marked explicitly unavailable — not synthesized or zeroed",
                },
            ]
        }
    finally:
        db.close()


@app.get("/api/system/status")
def get_system_status():
    """System health, scheduler jobs, database metrics, and alert logs."""
    from database import GoldForecast as GF, Prediction as P, GoldModelTraining as GMT, AlertLog as AL, PeriodicJobRun as PJR

    db = SessionLocal()
    try:
        forecast_count = db.query(GF).count()
        prediction_count = db.query(P).count()
        gold_trained_count = db.query(GMT).filter(GMT.trained_at.isnot(None)).count()

        job_runs = {
            r.job_name: r.last_run_at.isoformat() if r.last_run_at else None
            for r in db.query(PJR).all()
        }

        recent_alerts = [
            {
                "id": a.id,
                "sent_at": a.sent_at.isoformat() if a.sent_at else None,
                "event_code": a.event_code,
                "release_time": a.release_time_str,
                "alert_type": a.alert_type,
            }
            for a in db.query(AL).order_by(AL.sent_at.desc()).limit(15).all()
        ]

        db_path = os.getenv("MACRO_PREDICTOR_DATABASE_URL", "sqlite:///macro_predictor.db").replace("sqlite:///", "")
        db_size_kb = round(os.path.getsize(db_path) / 1024, 1) if os.path.exists(db_path) else 0

        scheduler_enabled = os.getenv("ENABLE_BACKGROUND_SCHEDULER", "true").strip().lower() in {"1", "true", "yes", "on"}

        return {
            "backend": {
                "version": "4.0.0",
                "mode": "USD & XAU/USD Only",
                "uptime": "Healthy",
                "utc_time": datetime.now(timezone.utc).isoformat(),
            },
            "database": {
                "engine": "SQLite",
                "file_path": db_path,
                "size_kb": db_size_kb,
                "gold_forecasts": forecast_count,
                "usd_predictions": prediction_count,
                "gold_trained_moments": gold_trained_count,
            },
            "scheduler": {
                "is_running": scheduler_enabled,
                "jobs": [
                    {
                        "name": "auto_alert_job",
                        "cadence": "Every 1 minute",
                        "purpose": "Pre-release (0-10m) forecasts, post-release price grading, gold training sweep",
                        "last_run": job_runs.get("auto_alert_job"),
                    },
                    {
                        "name": "sentiment_job",
                        "cadence": "Daily at 00:30 & 12:30 UTC",
                        "purpose": "GDELT & RSS news sentiment aggregation",
                        "last_run": job_runs.get("sentiment_job"),
                    },
                    {
                        "name": "cot_job",
                        "cadence": "Friday at 16:00 UTC",
                        "purpose": "CFTC COT positioning report sync",
                        "last_run": job_runs.get("cot_job"),
                    },
                ],
            },
            "recent_alerts": recent_alerts,
        }
    finally:
        db.close()


@app.get("/api/gold/model-status")
def get_gold_model_status():
    """Report gold-model training sufficiency and honest validation status."""
    from gold_model import get_model_status as get_status

    db = SessionLocal()
    try:
        return get_status(db)
    finally:
        db.close()


@app.get("/api/data-quality")
def get_data_quality():
    """Summarize point-in-time feature coverage and missing gold outcomes."""
    from gold_model import get_data_quality_summary

    db = SessionLocal()
    try:
        return {
            "markets": ["USD", "XAU/USD"],
            "gold": get_data_quality_summary(db),
        }
    finally:
        db.close()


@app.get("/api/accuracy-trend")
def get_accuracy_trend():
    """
    Rolling accuracy over windows of 10 release moments.
    USD-only — simultaneous predictions count as one observation.
    """
    all_graded = [
        moment for moment in get_grouped_release_moments()
        if moment["hit"] is not None
    ]
    all_graded.sort(key=lambda moment: moment["release_time_utc"])

    trend_data = []
    WINDOW = 10

    windows = []
    for i in range(0, len(all_graded), WINDOW):
        chunk = all_graded[i: i + WINDOW]
        if len(chunk) < 2:
            break
        wins     = sum(1 for moment in chunk if moment["hit"] is True)
        hit_rate = round(wins / len(chunk) * 100, 1)
        windows.append({
            "window_start": i + 1,
            "window_end":   i + len(chunk),
            "predictions":  len(chunk),
            "release_moments": len(chunk),
            "wins":         wins,
            "hit_rate_pct": hit_rate,
            "date_from":    chunk[0]["release_time_utc"],
            "date_to":      chunk[-1]["release_time_utc"],
        })

    trend_data.append({
        "currency":       "USD",
        "total_graded":   len(all_graded),
        "release_moments": len(all_graded),
        "windows":        windows,
        "improving":      (len(windows) >= 2 and
                           windows[-1]["hit_rate_pct"] > windows[0]["hit_rate_pct"]),
    })

    return {"trend": trend_data}


@app.get("/api/calibration")
def get_calibration(currency: Optional[str] = None):
    """
    Calibration check: for each confidence bucket, compare stated confidence
    (midpoint) against the actual real-world win rate of predictions in that bucket.

    GET /api/calibration?currency=USD  (currency param is optional)

    Response format:
      [
        {"bucket": "<60%",   "stated_midpoint": 55, "actual_win_rate": 0.48, "count": 12, "flagged": true},
        {"bucket": "60-70%", "stated_midpoint": 65, "actual_win_rate": 0.63, "count": 8,  "flagged": false},
        ...
      ]
    flagged = True when |actual_win_rate - stated_midpoint/100| > 0.10
    Only buckets with count > 0 are returned.
    """
    moments = [
        moment for moment in get_grouped_release_moments()
        if moment["hit"] is not None
        and (currency is None or currency.upper() == "USD")
    ]

    buckets = [
        {"bucket": "<60%",   "stated_midpoint": 55, "total": 0, "wins": 0},
        {"bucket": "60-70%", "stated_midpoint": 65, "total": 0, "wins": 0},
        {"bucket": "70-80%", "stated_midpoint": 75, "total": 0, "wins": 0},
        {"bucket": ">80%",   "stated_midpoint": 85, "total": 0, "wins": 0},
    ]

    for moment in moments:
        conf = moment["confidence_pct"]
        if conf < 60:
            idx = 0
        elif conf < 70:
            idx = 1
        elif conf < 80:
            idx = 2
        else:
            idx = 3
        buckets[idx]["total"] += 1
        if moment["hit"] is True:
            buckets[idx]["wins"] += 1

    result = []
    for b in buckets:
        total = b["total"]
        if total == 0:
            continue
        wins             = b["wins"]
        actual_win_rate  = wins / total
        stated_midpoint  = b["stated_midpoint"]
        # Minimum 10 graded predictions per bucket before flagging
        flagged          = (total >= 10) and (abs(actual_win_rate - stated_midpoint / 100) > 0.10)
        result.append({
            "bucket":          b["bucket"],
            "stated_midpoint": stated_midpoint,
            "actual_win_rate": round(actual_win_rate, 4),
            "count":           total,
            "flagged":         flagged,
        })

    return result


@app.post("/api/scheduler/check-now")
def trigger_scheduler_check():
    check_and_alert_upcoming()
    return {"status": "ok", "message": "Alert check triggered successfully"}


@app.post("/api/predictions/warmup")
def warmup_predictions(background_tasks=None):
    """
    Generate predictions for all HIGH-impact upcoming events that don't have
    a cached prediction yet.  Called automatically by the frontend on first load.
    Runs synchronously but is fast because it only processes events with no
    existing cached prediction — typically 3-8 events on a fresh start.
    Returns immediately with the list of event codes that were processed.
    """
    import threading

    events = fetch_upcoming_red_folder_events()
    high_events = [
        e for e in events
        if e.get("impact") in ("HIGH", "MEDIUM") and e.get("event_code") and is_numeric_event(e)
    ]

    now_ts = time.time()
    to_run = [
        e for e in high_events
        if not (_api_pred_cache.get(e["event_code"]) and
                (now_ts - _api_pred_cache[e["event_code"]][0]) < _API_PRED_TTL)
    ]

    triggered: list[str] = [e["event_code"] for e in to_run]

    def _run_predictions():
        from learning import capture_prediction_features, save_prediction_feature_snapshot

        for ev in to_run:
            code = ev["event_code"]
            try:
                cfg      = get_event_config(code)
                currency = ev.get("currency") or cfg.get("currency", "USD")
                result   = build_composite_score(code)
                direction = result["lean_direction"]
                dir_key   = (
                    "BULLISH" if direction in ("BEAT", "BULLISH") else
                    "BEARISH" if direction in ("MISS", "BEARISH") else
                    "INLINE"
                )
                pred_data = {
                    "lean_direction":    direction,
                    "confidence_pct":    result["confidence_pct"],
                    "composite_score":   result["composite_score"],
                    "indicator_score":   result.get("indicator_score", 0.0),
                    "event_label":       cfg.get("event_labels",  {}).get(dir_key, direction),
                    "explanation":       "",
                    "indicators":        result["indicator_breakdown"],
                }
                # Persist to DB
                db = SessionLocal()
                try:
                    release_time_utc = ev.get("release_time_utc")
                    existing = db.query(PredictionModel).filter(
                        PredictionModel.event_code == code,
                        PredictionModel.release_time_utc == release_time_utc,
                    ).first()
                    if not existing:
                        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
                        is_late_flag = check_is_late(now_utc, release_time_utc)
                        point_in_time_features = capture_prediction_features(
                            currency,
                            float(result.get(
                                "indicator_score",
                                result.get("composite_score") or 0.0,
                            )),
                        )
                        prediction = PredictionModel(
                            created_at          = now_utc,
                            event_code          = code,
                            event_display_name  = cfg.get("display_name", code),
                            release_time_utc    = release_time_utc,
                            forecast            = ev.get("forecast"),
                            composite_score     = result["composite_score"],
                            lean_direction      = result["lean_direction"],
                            confidence_pct      = result["confidence_pct"],
                            indicator_breakdown = json.dumps(result["indicator_breakdown"]),
                            currency            = currency,
                            model_version       = "river_arf_v1",
                            is_late             = is_late_flag,
                        )
                        db.add(prediction)
                        db.flush()
                        save_prediction_feature_snapshot(
                            db, prediction, point_in_time_features
                        )
                        db.commit()
                finally:
                    db.close()

                gold_forecast = _create_gold_forecast(
                    events, ev.get("release_time_utc")
                )
                pred_data["gold_forecast"] = gold_forecast
                _api_pred_cache[code] = (time.time(), pred_data)
                log.info("Warmup prediction: %s → %s (%.0f%%)", code, direction, result["confidence_pct"])
            except Exception as e:
                log.warning("Warmup failed for %s: %s", code, e)

    # Run in background thread so the response returns immediately
    t = threading.Thread(target=_run_predictions, daemon=True)
    t.start()

    to_run_codes = [e["event_code"] for e in to_run]
    return {
        "status":    "started",
        "triggered": to_run_codes,
        "skipped":   [e["event_code"] for e in high_events if e["event_code"] not in to_run_codes],
    }


@app.post("/api/prediction/{event_code}/telegram")
def send_event_telegram(event_code: str):
    code = event_code.upper()
    result       = build_composite_score(code)
    ok = send_telegram_alert(result)
    return {"success": ok, "event_code": code}


@app.post("/api/telegram/broadcast-all")
def broadcast_all_to_telegram():
    results = []
    for code in EVENTS:
        try:
            pred      = build_composite_score(code)
            ok = send_telegram_alert(pred)
            results.append({"event_code": code, "success": ok})
        except Exception as e:
            results.append({"event_code": code, "error": str(e), "success": False})
    return {"broadcast": results}


@app.post("/api/telegram/test")
def test_telegram():
    ok = send_test_message()
    return {"success": ok}


# ── Serve React frontend (must be last) ──────────────────────────────────────
_dist = os.path.join(os.path.dirname(__file__), "frontend", "dist")
if not os.path.isdir(_dist):
    _dist = os.path.join(os.path.dirname(__file__), "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
