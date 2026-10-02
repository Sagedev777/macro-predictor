"""
api.py — FastAPI backend for MacroPredictor.

Original endpoints preserved with identical signatures.
New endpoints added for the multi-currency architecture:
  GET  /api/currency-strengths          — all 8 currency strength scores
  GET  /api/currency-strengths/{ccy}    — single currency detail
  GET  /api/pair-bias/{pair}            — directional bias for a pair
  GET  /api/pair-biases                 — all canonical pairs
  GET  /api/order-suggestion/{event}    — ATR-based pending-order levels
  GET  /api/feature-drift               — River feature importance per currency
  POST /api/run-full-cycle              — trigger full indicator+sentiment+prediction cycle
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

from alerts import send_telegram_alert, send_test_message
from calendar_feed import fetch_upcoming_red_folder_events, update_event_actual
from config.events import CANONICAL_PAIRS, CURRENCIES, EVENTS, get_event_config
from database import (
    AlertLog,
    Prediction as PredictionModel,
    SessionLocal,
    init_db,
    is_pre_release_prediction,
)
from indicators import (
    build_composite_score,
    get_latest_currency_strengths,
    persist_currency_strength,
)
from learning import (
    build_features,
    compute_all_pair_biases,
    compute_pair_bias,
    get_all_strengths,
    get_feature_importance_drift,
    predict_strength,
)
from price_data import build_all_order_suggestions, get_latest_suggestions
from scheduler import (
    check_and_alert_upcoming,
    grade_prediction,
    send_outcome_alert,
    start_scheduler,
    stop_scheduler,
)

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

# ── In-process caches ─────────────────────────────────────────────────────────
_api_pred_cache:    dict[str, tuple[float, dict]] = {}
_API_PRED_TTL  = 600    # 10 minutes — event prediction cache
_strength_cache: dict[str, tuple[float, dict]]   = {}
_STRENGTH_TTL  = 300    # 5 minutes — currency strength cache

app = FastAPI(title="MacroPredictor API", version="3.0.0")

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
    start_scheduler()
    log.info("MacroPredictor API v3 started — multi-currency mode active.")


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
        "version":               "3.0.0",
        "fred_configured":       bool(fred_key and fred_key != "your_fred_key_here"),
        "telegram_configured":   bool(tg_token and tg_chat),
        "twelve_data_configured":bool(td_key and td_key != "your_twelve_data_api_key_here"),
        "alert_hours_before":    hours_before,
        "supported_events":      list(EVENTS.keys()),
        "tracked_currencies":    CURRENCIES,
        "canonical_pairs":       CANONICAL_PAIRS,
        "scheduler_running":     True,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CALENDAR / EVENTS  (original endpoints — signatures unchanged)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/events")
def get_upcoming_events(force_refresh: bool = False):
    """
    Return upcoming red+orange folder events from Forex Factory with predictions.
    Now covers all 8 currencies; impact field = "HIGH"|"MEDIUM".
    """
    events = fetch_upcoming_red_folder_events(force_refresh=force_refresh)
    return _get_events_body(events)


@app.post("/api/events/sync-actuals")
def sync_actuals_from_feed():
    """
    Force a live Forex Factory refresh, auto-detect newly published actuals,
    grade matching pre-release predictions, and trigger River learn_one().
    """
    from learning import learn_one, lean_to_outcome
    from data_sources import get_rate_differential, rate_diff_to_score
    from sentiment import get_latest_cot, get_latest_sentiment, cot_to_score, sentiment_to_score

    events = fetch_upcoming_red_folder_events(force_refresh=True)
    graded = []
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

            existing_graded = db.query(PredictionModel).filter(
                PredictionModel.event_code == code,
                PredictionModel.release_time_utc == release_time_utc,
                PredictionModel.was_correct.isnot(None),
            ).first()
            if existing_graded:
                continue

            pred = (
                db.query(PredictionModel)
                .filter(
                    PredictionModel.event_code == code,
                    PredictionModel.release_time_utc == release_time_utc,
                    PredictionModel.was_correct.is_(None),
                )
                .order_by(PredictionModel.created_at.desc())
                .first()
            )
            if not pred or not is_pre_release_prediction(pred):
                continue

            was_correct, verdict_msg = grade_prediction(
                code, pred.lean_direction, actual, forecast
            )
            surprise = round(actual - forecast, 4)

            pred.actual          = actual
            pred.forecast        = forecast
            pred.surprise        = surprise
            pred.actual_surprise = surprise
            pred.was_correct     = was_correct
            db.commit()

            # ── River learn_one() after grading ───────────────────────────────
            try:
                rd   = get_rate_differential(currency)
                cot  = get_latest_cot(currency)
                sent = get_latest_sentiment(currency)

                indicator_score = pred.composite_score or 0.0
                features = build_features(
                    indicator_score = float(indicator_score),
                    rate_diff_score = rate_diff_to_score(rd),
                    cot_score       = cot_to_score(cot),
                    sentiment_score = sentiment_to_score(sent),
                )
                outcome = lean_to_outcome(pred.lean_direction, was_correct)
                learn_one(currency, features, outcome)
            except Exception as le:
                log.warning("River learn_one failed for %s: %s", code, le)

            # ── Telegram outcome alert ─────────────────────────────────────────
            try:
                rel_str   = ev.get("release_time_utc", "")
                post_sent = db.query(AlertLog).filter(
                    AlertLog.event_code == code,
                    AlertLog.release_time_str == rel_str,
                    AlertLog.alert_type == "POST_RELEASE",
                ).first()
                if not post_sent:
                    send_outcome_alert(
                        code, actual, forecast, was_correct,
                        pred.lean_direction, verdict_explanation=verdict_msg,
                    )
                    db.add(AlertLog(
                        event_code=code, release_time_str=rel_str,
                        alert_type="POST_RELEASE",
                    ))
                    db.commit()
            except Exception as te:
                log.warning("Telegram outcome alert failed for %s: %s", code, te)

            graded.append({
                "event_code":   code,
                "display_name": event_cfg.get("display_name", code),
                "currency":     currency,
                "actual":       actual,
                "forecast":     forecast,
                "surprise":     surprise,
                "was_correct":  was_correct,
            })

        return {
            "success":       True,
            "synced_events": len(events),
            "newly_graded":  len(graded),
            "graded":        graded,
        }
    finally:
        db.close()


def _get_events_body(events: list) -> dict:
    """
    Annotate calendar events with simultaneous flags, predictions, and pair signals.
    Used by /api/events and related endpoints.
    """
    time_groups: dict[str, list] = {}
    for ev in events:
        t_str = ev.get("release_time_utc")
        if t_str:
            time_groups.setdefault(t_str, []).append(ev)

    for ev in events:
        code  = ev.get("event_code")
        t_str = ev.get("release_time_utc")

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

            now_ts = time.time()
            cached = _api_pred_cache.get(code)
            if cached and (now_ts - cached[0]) < _API_PRED_TTL:
                ev["prediction"] = cached[1]
            else:
                try:
                    result    = build_composite_score(code)
                    direction = result["lean_direction"]
                    dir_key   = (
                        "BULLISH" if direction in ("BEAT",  "BULLISH") else
                        "BEARISH" if direction in ("MISS",  "BEARISH") else
                        "INLINE"
                    )
                    pred_data = {
                        "lean_direction":   direction,
                        "confidence_pct":   result["confidence_pct"],
                        "composite_score":  result["composite_score"],
                        "indicator_score":  result.get("indicator_score", 0.0),
                        "event_label":      cfg.get("event_labels",  {}).get(dir_key, direction),
                        "explanation":      cfg.get("explanations",  {}).get(dir_key, ""),
                        "trade_signals":    cfg.get("trade_signals", {}).get(dir_key, []),
                        "indicators":       result["indicator_breakdown"],
                        "pair_signals":     _get_pair_signals_for_event(code, ev.get("currency", "USD"), result),
                        "order_suggestions":get_latest_suggestions(code),
                    }
                    _api_pred_cache[code] = (now_ts, pred_data)
                    ev["prediction"] = pred_data
                except Exception as e:
                    log.warning("Prediction failed for %s: %s", code, e)
                    ev["prediction"] = None

    return {"count": len(events), "events": events}


def _get_pair_signals_for_event(
    event_code: str,
    currency:   str,
    composite:  dict,
) -> list[dict]:
    """
    Build per-pair buy/sell signals for a single event using the current
    currency strength scores from the DB (or the fresh composite if available).
    Returns a list of {pair, direction, confidence_pct, bias} dicts.
    """
    try:
        strengths   = _get_cached_strengths()
        pair_biases = compute_all_pair_biases(strengths)
        ccy = currency.upper()
        results = []
        for pair, pb in pair_biases.items():
            if pb.base == ccy or pb.quote == ccy:
                results.append({
                    "pair":           pair,
                    "direction":      pb.direction,
                    "bias":           pb.bias,
                    "confidence_pct": pb.confidence_pct,
                })
        return sorted(results, key=lambda x: abs(x["bias"]), reverse=True)
    except Exception as e:
        log.warning("Pair signal computation failed for %s: %s", event_code, e)
        return []


def _get_cached_strengths() -> dict:
    """Return currency strengths from cache or DB."""
    now_ts = time.time()
    cached = _strength_cache.get("all")
    if cached and (now_ts - cached[0]) < _STRENGTH_TTL:
        return cached[1]

    # Build feature map from latest DB snapshots
    from data_sources import rate_diff_to_score, get_all_rate_differentials
    from sentiment import get_latest_cot, get_latest_sentiment, cot_to_score, sentiment_to_score

    db_strengths = get_latest_currency_strengths()
    feature_map: dict[str, dict] = {}

    for ccy in CURRENCIES:
        row = db_strengths.get(ccy, {})
        feature_map[ccy] = build_features(
            indicator_score = float(row.get("indicator_score") or 0.0),
            rate_diff_score = float(row.get("rate_diff_score") or 0.0),
            cot_score       = float(row.get("cot_score")       or 0.0),
            sentiment_score = float(row.get("sentiment_score") or 0.0),
        )

    strengths = get_all_strengths(feature_map)
    _strength_cache["all"] = (now_ts, strengths)
    return strengths


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
    """Record an actual release print and grade a linked pre-release forecast."""
    from learning import learn_one, lean_to_outcome
    from data_sources import get_rate_differential, rate_diff_to_score
    from sentiment import get_latest_cot, get_latest_sentiment, cot_to_score, sentiment_to_score

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
                PredictionModel.was_correct.is_(None),
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
        if forecast is None:
            return {
                "success": True, "event_code": code, "actual": payload.actual,
                "graded": False, "message": "Actual recorded; forecast unavailable for grading.",
            }

        was_correct, verdict_msg = grade_prediction(
            code, pred.lean_direction, payload.actual, forecast
        )
        surprise = round(payload.actual - forecast, 4)

        pred.actual = payload.actual; pred.forecast = forecast
        pred.surprise = surprise; pred.actual_surprise = surprise
        pred.was_correct = was_correct
        db.commit()

        # River learn_one
        try:
            rd   = get_rate_differential(currency)
            cot  = get_latest_cot(currency)
            sent = get_latest_sentiment(currency)
            features = build_features(
                indicator_score = float(pred.composite_score or 0.0),
                rate_diff_score = rate_diff_to_score(rd),
                cot_score       = cot_to_score(cot),
                sentiment_score = sentiment_to_score(sent),
            )
            outcome = lean_to_outcome(pred.lean_direction, was_correct)
            learn_one(currency, features, outcome)
        except Exception as le:
            log.warning("River learn_one failed for %s: %s", code, le)

        try:
            send_outcome_alert(
                code, payload.actual, forecast, was_correct,
                pred.lean_direction, verdict_explanation=verdict_msg,
            )
        except Exception as te:
            log.warning("Telegram alert failed: %s", te)

        return {
            "success":        True,
            "event_code":     code,
            "display_name":   pred.event_display_name,
            "actual":         payload.actual,
            "forecast":       forecast,
            "surprise":       surprise,
            "lean_direction": pred.lean_direction,
            "was_correct":    was_correct,
            "graded":         True,
            "verdict":        verdict_msg,
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

    # Pull calendar data for release time / forecast
    events           = fetch_upcoming_red_folder_events()
    release_time_utc = None
    forecast         = None
    for ev in events:
        if ev.get("event_code") == code:
            release_time_utc = ev.get("release_time_utc")
            forecast         = ev.get("forecast")
            break

    # Build pair signals and order suggestions
    pair_signals       = _get_pair_signals_for_event(code, currency, result)
    order_suggestions  = get_latest_suggestions(code)

    # Persist to DB
    db   = SessionLocal()
    pred = PredictionModel(
        event_code          = code,
        event_display_name  = cfg.get("display_name", code),
        release_time_utc    = release_time_utc,
        forecast            = forecast,
        composite_score     = result["composite_score"],
        lean_direction      = result["lean_direction"],
        confidence_pct      = result["confidence_pct"],
        indicator_breakdown = json.dumps(result["indicator_breakdown"]),
        currency            = currency,
        pair_signals        = json.dumps(pair_signals),
        model_version       = "river_arf_v1",
    )
    db.add(pred)
    db.commit()
    db.refresh(pred)
    pred_id    = pred.id
    created_at = pred.created_at.isoformat() if pred.created_at else None
    db.close()

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
        "trade_signals":    trade_signals,
        "pair_signals":     pair_signals,
        "order_suggestions":order_suggestions,
        "indicator_breakdown": result["indicator_breakdown"],
        "indicators":       result["indicator_breakdown"],
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
        pair_signals = []
        if p.pair_signals:
            try:
                pair_signals = json.loads(p.pair_signals)
            except Exception:
                pass

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
            "explanation":      (
                cfg.get("explanations", {}).get(p.lean_direction)
                or cfg.get("explanations", {}).get(dir_key, "")
            ),
            "confidence_pct":   p.confidence_pct,
            "composite_score":  p.composite_score,
            "trade_signals":    (
                cfg.get("trade_signals", {}).get(p.lean_direction)
                or cfg.get("trade_signals", {}).get(dir_key, [])
            ),
            "pair_signals":     pair_signals,
            "created_at":       p.created_at.isoformat() if p.created_at else None,
            "was_correct":      p.was_correct,
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


@app.get("/api/history")
def get_historical_outcomes(limit: int = 30):
    """Return outcomes for forecasts saved before their scheduled release."""
    db         = SessionLocal()
    candidates = (
        db.query(PredictionModel)
        .filter(
            PredictionModel.was_correct.isnot(None),
            PredictionModel.is_sample.is_(False),
        )
        .order_by(PredictionModel.created_at.desc())
        .all()
    )
    graded = [p for p in candidates if is_pre_release_prediction(p)][:max(0, limit)]
    db.close()

    total    = len(graded)
    wins     = sum(1 for p in graded if p.was_correct is True)
    losses   = sum(1 for p in graded if p.was_correct is False)
    hit_rate = round((wins / total * 100), 1) if total > 0 else 0.0

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
                "trade_signals":   (
                    EVENTS.get(p.event_code, {})
                    .get("trade_signals", {})
                    .get(p.lean_direction, [])
                ),
                "date":            p.release_time_utc,
            }
            for p in graded
        ],
    }


@app.get("/api/accuracy")
def get_overall_accuracy():
    """Return accuracy stats for non-sample pre-release forecasts."""
    db         = SessionLocal()
    candidates = (
        db.query(PredictionModel)
        .filter(
            PredictionModel.was_correct.isnot(None),
            PredictionModel.is_sample.is_(False),
        )
        .all()
    )
    all_graded = [p for p in candidates if is_pre_release_prediction(p)]
    db.close()

    total    = len(all_graded)
    wins     = sum(1 for p in all_graded if p.was_correct)
    hit_rate = round((wins / total * 100), 1) if total > 0 else 0.0

    # Per-event breakdown
    breakdown:          dict[str, dict]  = {}
    confidence_buckets: dict[str, dict]  = {
        "<60%":   {"total": 0, "wins": 0},
        "60-70%": {"total": 0, "wins": 0},
        "70-80%": {"total": 0, "wins": 0},
        ">80%":   {"total": 0, "wins": 0},
    }
    # Per-currency breakdown (new)
    currency_breakdown: dict[str, dict] = {}

    for p in all_graded:
        code = p.event_code
        ccy  = p.currency or "USD"

        breakdown.setdefault(code, {"total": 0, "wins": 0, "name": p.event_display_name})
        breakdown[code]["total"] += 1
        if p.was_correct:
            breakdown[code]["wins"] += 1

        currency_breakdown.setdefault(ccy, {"total": 0, "wins": 0})
        currency_breakdown[ccy]["total"] += 1
        if p.was_correct:
            currency_breakdown[ccy]["wins"] += 1

        bucket = (
            "<60%"   if (p.confidence_pct or 0) < 60 else
            "60-70%" if (p.confidence_pct or 0) < 70 else
            "70-80%" if (p.confidence_pct or 0) < 80 else
            ">80%"
        )
        confidence_buckets[bucket]["total"] += 1
        if p.was_correct:
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
        "wins":               wins,
        "losses":             total - wins,
        "overall_hit_rate":   hit_rate,
        "event_stats":        sorted(event_stats,    key=lambda x: x["hit_rate_pct"], reverse=True),
        "currency_stats":     sorted(currency_stats, key=lambda x: x["hit_rate_pct"], reverse=True),
        "confidence_stats":   confidence_stats,
    }


# ══════════════════════════════════════════════════════════════════════════════
# NEW: CURRENCY STRENGTH ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/currency-strengths")
def get_currency_strengths():
    """
    Return the latest strength score for all 8 currencies.
    Scores are in [-1, +1] — positive = bullish, negative = bearish.
    """
    strengths   = _get_cached_strengths()
    db_snapshot = get_latest_currency_strengths()

    result = []
    for ccy in CURRENCIES:
        pred = strengths.get(ccy)
        snap = db_snapshot.get(ccy, {})
        result.append({
            "currency":       ccy,
            "strength_score": pred.strength_score   if pred else 0.0,
            "confidence_pct": pred.confidence_pct   if pred else 30.0,
            "n_trained":      pred.n_trained         if pred else 0,
            "indicator_score":snap.get("indicator_score"),
            "rate_diff_score":snap.get("rate_diff_score"),
            "cot_score":      snap.get("cot_score"),
            "sentiment_score":snap.get("sentiment_score"),
            "recorded_at":    snap.get("recorded_at"),
        })

    return {"count": len(result), "currency_strengths": result}


@app.get("/api/currency-strengths/{currency}")
def get_single_currency_strength(currency: str):
    """Return the full strength detail for a single currency."""
    ccy = currency.upper()
    if ccy not in CURRENCIES:
        raise HTTPException(status_code=404, detail=f"Unknown currency '{ccy}'")

    from data_sources import get_rate_differential
    from sentiment import get_latest_cot, get_latest_sentiment

    strengths  = _get_cached_strengths()
    pred       = strengths.get(ccy)
    snap       = get_latest_currency_strengths().get(ccy, {})
    rd         = get_rate_differential(ccy)
    cot        = get_latest_sentiment(ccy)    # read from DB
    sent       = get_latest_sentiment(ccy)    # same table, most recent

    return {
        "currency":         ccy,
        "strength_score":   pred.strength_score  if pred else 0.0,
        "confidence_pct":   pred.confidence_pct  if pred else 30.0,
        "n_trained":        pred.n_trained        if pred else 0,
        "model_version":    pred.model_version    if pred else "river_arf_v1",
        "feature_inputs":   pred.feature_inputs   if pred else {},
        "indicator_score":  snap.get("indicator_score"),
        "rate_diff": {
            "spread_pct":       rd.spread_pct       if rd else None,
            "spread_3m_avg":    rd.spread_3m_avg    if rd else None,
            "trend_direction":  rd.trend_direction  if rd else "UNKNOWN",
            "local_yield_pct":  rd.local_yield_pct  if rd else None,
            "us_yield_pct":     rd.us_yield_pct     if rd else None,
        },
        "sentiment": {
            "net_score":     sent.net_score     if sent else None,
            "bullish_pct":   sent.bullish_pct   if sent else None,
            "bearish_pct":   sent.bearish_pct   if sent else None,
            "article_count": sent.article_count if sent else 0,
        },
        "recorded_at": snap.get("recorded_at"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# NEW: PAIR BIAS ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/pair-biases")
def get_all_pair_biases():
    """Return directional bias for all canonical pairs."""
    strengths   = _get_cached_strengths()
    pair_biases = compute_all_pair_biases(strengths)

    result = [
        {
            "pair":           pb.pair,
            "base":           pb.base,
            "quote":          pb.quote,
            "base_strength":  pb.base_strength,
            "quote_strength": pb.quote_strength,
            "bias":           pb.bias,
            "direction":      pb.direction,
            "confidence_pct": pb.confidence_pct,
        }
        for pb in pair_biases.values()
    ]
    result.sort(key=lambda x: abs(x["bias"]), reverse=True)
    return {"count": len(result), "pair_biases": result}


@app.get("/api/pair-bias/{pair}")
def get_single_pair_bias(pair: str):
    """Return directional bias for a single pair (e.g. EURUSD, XAUUSD)."""
    p = pair.upper()
    if len(p) < 6:
        raise HTTPException(status_code=400, detail="Pair must be 6+ characters, e.g. EURUSD")

    base  = "XAU" if p == "XAUUSD" else p[:3]
    quote = p[3:]

    strengths = _get_cached_strengths()
    pb        = compute_pair_bias(base, quote, strengths)

    return {
        "pair":           pb.pair,
        "base":           pb.base,
        "quote":          pb.quote,
        "base_strength":  pb.base_strength,
        "quote_strength": pb.quote_strength,
        "bias":           pb.bias,
        "direction":      pb.direction,
        "confidence_pct": pb.confidence_pct,
    }


# ══════════════════════════════════════════════════════════════════════════════
# NEW: ORDER SUGGESTION ENDPOINT
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/order-suggestion/{event_code}")
def get_order_suggestions(event_code: str):
    """
    Return ATR-based pending-order suggestions for all affected pairs
    for a given upcoming event.  Levels are is_reference_only=True.
    """
    code = event_code.upper()
    # Try DB first (avoids re-running Twelve Data calls on every request)
    suggestions = get_latest_suggestions(code)
    if suggestions:
        return {
            "event_code":     code,
            "is_reference_only": True,
            "suggestions":    suggestions,
        }

    # Not in DB yet — compute fresh
    cfg              = get_event_config(code)
    currency         = cfg.get("currency", "USD")
    events           = fetch_upcoming_red_folder_events()
    release_time_utc = None
    for ev in events:
        if ev.get("event_code") == code:
            release_time_utc = ev.get("release_time_utc")
            break

    strengths        = _get_cached_strengths()
    pair_biases_dict = compute_all_pair_biases(strengths)
    new_suggestions  = build_all_order_suggestions(code, release_time_utc, pair_biases_dict)

    return {
        "event_code":        code,
        "is_reference_only": True,
        "suggestions": [
            {
                "pair":             s.pair,
                "bias":             s.bias,
                "current_price":    s.current_price,
                "atr_14":           s.atr_14,
                "suggested_entry":  s.suggested_entry,
                "suggested_sl":     s.suggested_sl,
                "suggested_tp":     s.suggested_tp,
                "confidence_pct":   s.confidence_pct,
                "event_code":       s.event_code,
                "release_time_utc": s.release_time_utc,
                "is_reference_only":True,
                "note":             s.note,
            }
            for s in new_suggestions
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# NEW: FEATURE IMPORTANCE DRIFT
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/feature-drift")
def get_feature_drift():
    """
    Return River ARF feature importance weights per currency.
    Shows which signal type (indicator, rate_diff, cot, sentiment) is
    currently most predictive for each currency model.
    """
    drift = get_feature_importance_drift()
    return {
        "currencies": [
            {"currency": ccy, "feature_weights": weights}
            for ccy, weights in drift.items()
        ]
    }


# ══════════════════════════════════════════════════════════════════════════════
# SCHEDULER / TELEGRAM  (original signatures unchanged)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/scheduler/check-now")
def trigger_scheduler_check():
    check_and_alert_upcoming()
    return {"status": "ok", "message": "Alert check triggered successfully"}


@app.post("/api/run-full-cycle")
def run_full_cycle():
    """
    Trigger a full indicator + rate-differential + currency-strength cycle.
    Useful for manual refresh without waiting for the scheduler.
    """
    from data_sources import compute_rate_differentials, rate_diff_to_score
    from sentiment import get_latest_cot, get_latest_sentiment, cot_to_score, sentiment_to_score
    from indicators import get_indicator_scores_all_currencies

    try:
        rate_diffs      = compute_rate_differentials()
        indicator_scores= get_indicator_scores_all_currencies()

        for ccy in CURRENCIES:
            rd   = rate_diffs.get(ccy)
            cot  = get_latest_cot(ccy)
            sent = get_latest_sentiment(ccy)

            ind_score = indicator_scores.get(ccy, 0.0)
            rd_score  = rate_diff_to_score(rd)
            c_score   = cot_to_score(cot)
            s_score   = sentiment_to_score(sent)

            features = build_features(ind_score, rd_score, c_score, s_score)
            pred     = predict_strength(ccy, features)

            persist_currency_strength(
                currency=ccy,
                strength_score=pred.strength_score,
                indicator_score=ind_score,
                rate_diff_score=rd_score,
                cot_score=c_score,
                sentiment_score=s_score,
                confidence_pct=pred.confidence_pct,
            )

        _strength_cache.clear()   # bust cache so next request gets fresh data
        return {"status": "ok", "message": "Full prediction cycle complete.", "currencies": CURRENCIES}
    except Exception as e:
        log.error("Full cycle failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/prediction/{event_code}/telegram")
def send_event_telegram(event_code: str):
    code = event_code.upper()
    cfg  = get_event_config(code)
    result       = build_composite_score(code)
    direction    = result["lean_direction"]
    dir_key      = (
        "BULLISH" if direction in ("BEAT",  "BULLISH") else
        "BEARISH" if direction in ("MISS",  "BEARISH") else "INLINE"
    )
    result["trade_signals"] = cfg.get("trade_signals", {}).get(dir_key, [])
    ok = send_telegram_alert(result)
    return {"success": ok, "event_code": code}


@app.post("/api/telegram/broadcast-all")
def broadcast_all_to_telegram():
    results = []
    for code in EVENTS:
        try:
            cfg       = get_event_config(code)
            pred      = build_composite_score(code)
            direction = pred["lean_direction"]
            dir_key   = (
                "BULLISH" if direction in ("BEAT", "BULLISH") else
                "BEARISH" if direction in ("MISS", "BEARISH") else "INLINE"
            )
            pred["trade_signals"] = cfg.get("trade_signals", {}).get(dir_key, [])
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
_dist = os.path.join(os.path.dirname(__file__), "dist")
if os.path.isdir(_dist):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="static")
