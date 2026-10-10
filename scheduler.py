"""
scheduler.py — Background scheduler for pre-release alerts, post-release grading,
               River learn_one() calls, daily rate-differential refresh, and
               48-hour sentiment refresh cycle.

Schedule summary:
  Every 1 min   — check_and_alert_upcoming()   (pre-release + post-release grading)
  Every 24 hr   — refresh_rate_differentials()  (USD yield spread)
  Every 12 hr   — refresh_sentiment_cycle()     (GDELT + RSS + FinBERT for USD)
  Every 168 hr  — refresh_cot_cycle()           (CFTC COT, released Fridays)
  Every 24 hr   — refresh_currency_strengths()  (full feature vector + River predict)

River learn_one() is called inline inside check_and_alert_upcoming() immediately
after a prediction is graded — not on a separate schedule.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

from alerts import BOT_TOKEN, CHAT_ID, send_telegram_alert, send_post_release_alert
from calendar_feed import fetch_upcoming_red_folder_events
from config.events import CURRENCIES, get_event_config
from database import (
    AlertLog,
    Prediction as PredictionModel,
    SessionLocal,
    check_is_late,
    is_pre_release_prediction,
)
from indicators import build_composite_score

load_dotenv()
log = logging.getLogger("scheduler")

scheduler: Optional[BackgroundScheduler] = None


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
# TELEGRAM ALERTS — unchanged from original
# ══════════════════════════════════════════════════════════════════════════════

def send_outcome_alert(
    event_code:          str,
    actual:              float,
    forecast:            float,
    was_correct:         bool,
    lean_direction:      str,
    verdict_explanation: str = "",
):
    """Send outcome grading alert to Telegram after release."""
    if not BOT_TOKEN or not CHAT_ID:
        return

    verdict_tag  = "🎯 PREDICTION WON (CORRECT)" if was_correct else "❌ PREDICTION MISSED (INCORRECT)"
    status_color = "🟢" if was_correct else "🔴"
    diff         = actual - forecast
    diff_sign    = "+" if diff > 0 else ""

    text = (
        f"{status_color} *REAL OUTCOME REPORT — {event_code}*\n\n"
        f"Result: *{verdict_tag}*\n"
        f"─────────────────────\n"
        f"Pre-Release Lean: `{lean_direction}`\n"
        f"Actual: `{actual}` | Forecast: `{forecast}` "
        f"(Surprise: `{diff_sign}{diff:.2f}`)\n\n"
        f"📝 *Verdict:* _{verdict_explanation}_\n"
        f"─────────────────────\n"
        f"📊 Recorded into historical hit-rate ledger (transparent & unedited)."
    )
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}, timeout=10)
    except Exception as e:
        log.error("Failed to send outcome alert: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# CORE SCHEDULER JOB — every 1 minute
# ══════════════════════════════════════════════════════════════════════════════

def check_and_alert_upcoming():
    """
    Every 1 minute:
      1. Pre-release check — send Telegram alert if event within 10-minute window.
         Only fires for HIGH or MEDIUM impact events.
      2. Post-release grading — grade predictions when actuals appear.
      3. River learn_one() — called immediately after grading.
    """
    from learning import (
        build_features, learn_one, lean_to_outcome,
        predict_strength, _registry,
    )

    def _registry_n_trained(ccy: str) -> int:
        try:
            return _registry.get_n_trained(ccy)
        except Exception:
            return 0
    from data_sources import get_rate_differential, rate_diff_to_score
    from sentiment import get_latest_cot, get_latest_sentiment, cot_to_score, sentiment_to_score
    from indicators import persist_currency_strength

    # Keep reading ALERT_HOURS_BEFORE so /api/health still reports it correctly,
    # but pre-release alerts now use a fixed 10-minute window instead.
    try:
        hours_before = float(os.getenv("ALERT_HOURS_BEFORE", "2"))
    except ValueError:
        hours_before = 2.0  # noqa: F841 — read for health endpoint compatibility

    db = SessionLocal()
    try:
        events  = fetch_upcoming_red_folder_events(force_refresh=False)
        now_utc = datetime.utcnow()

        for ev in events:
            code     = ev.get("event_code")
            currency = ev.get("currency", "USD")
            if not code:
                continue

            # ── Impact filter: only HIGH and MEDIUM events trigger alerts ────
            impact = ev.get("impact", "")
            if impact not in ("HIGH", "MEDIUM"):
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

                        # Build pair signals from event config trade_signals
                        _raw_dir_pre = pred_result.get("lean_direction", "")
                        _dir_key_pre = (
                            "BULLISH" if _raw_dir_pre.upper() in ("BEAT", "BULLISH") else
                            "BEARISH" if _raw_dir_pre.upper() in ("MISS", "BEARISH") else
                            "INLINE"
                        )
                        _trade_signals = event_cfg.get("trade_signals", {}).get(_dir_key_pre, [])
                        pair_signals = [
                            {"pair": s.split()[-1], "direction": s.split()[0]}
                            for s in _trade_signals
                            if s and not s.upper().startswith("WAIT")
                        ]

                        if not existing:
                            direction = pred_result["lean_direction"]
                            is_late_flag = check_is_late(now_utc, rel_str)
                            db.add(PredictionModel(
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
                                pair_signals        = json.dumps(pair_signals),
                                model_version       = "river_arf_v1",
                                is_late             = is_late_flag,
                            ))
                            db.commit()

                        # Inject trade_signals from events config into pred_result for Telegram
                        _raw_dir = pred_result.get("lean_direction", "")
                        _dir_key = (
                            "BULLISH" if _raw_dir.upper() in ("BEAT", "BULLISH") else
                            "BEARISH" if _raw_dir.upper() in ("MISS", "BEARISH") else
                            "INLINE"
                        )
                        pred_result["trade_signals"] = event_cfg.get("trade_signals", {}).get(_dir_key, [])
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
                        log.error("Pre-release alert failed for %s: %s", code, err)

            # ── 2. POST-RELEASE GRADING + RIVER LEARN ────────────────────────
            actual   = ev.get("actual")
            forecast = ev.get("forecast")
            if actual is not None and forecast is not None:
                recent_pred = (
                    db.query(PredictionModel)
                    .filter(
                        PredictionModel.event_code       == code,
                        PredictionModel.release_time_utc == rel_str,
                        PredictionModel.was_correct.is_(None),
                    )
                    .order_by(PredictionModel.created_at.desc())
                    .first()
                )

                if recent_pred:
                    # Data-integrity rule: only pre-release predictions count
                    # toward accuracy, ledger, and River training.
                    if not is_pre_release_prediction(recent_pred):
                        log.info(
                            "Skipping grading & River training for %s (id=%s): post-release/late prediction (is_late=%s)",
                            code, recent_pred.id, recent_pred.is_late
                        )
                    else:
                        surprise = round(actual - forecast, 4)
                        lean     = recent_pred.lean_direction
                        was_correct, verdict_msg = grade_prediction(code, lean, actual, forecast)

                        recent_pred.was_correct     = was_correct
                        recent_pred.actual          = actual
                        recent_pred.forecast        = forecast
                        recent_pred.surprise        = surprise
                        recent_pred.actual_surprise = surprise
                        db.commit()

                        # ── River learn_one() — strictly pre-release predictions only ──
                        new_confidence = recent_pred.confidence_pct or 50.0
                        n_after        = 0
                        n_before       = 0
                        try:
                            rd   = get_rate_differential(currency)
                            cot  = get_latest_cot(currency)
                            sent = get_latest_sentiment(currency)

                            n_before = _registry_n_trained(currency)
                            features = build_features(
                                indicator_score = float(recent_pred.composite_score or 0.0),
                                rate_diff_score = rate_diff_to_score(rd),
                                cot_score       = cot_to_score(cot),
                                sentiment_score = sentiment_to_score(sent),
                            )
                            outcome = lean_to_outcome(lean, was_correct)
                            stats   = learn_one(currency, features, outcome)
                            n_after = stats.get("n_trained", 0)

                            # Persist actual weight shift to the prediction row
                            recent_pred.weight_shift = stats.get("weight_shift_str")
                            db.commit()

                            log.info(
                                "learn_one [%s] event=%s outcome=%d correct=%s "
                                "features={ind=%.3f rd=%.3f cot=%.3f sent=%.3f} "
                                "n_trained: %d → %d  acc=%.1f%%  shift=%s",
                                currency, code, outcome, was_correct,
                                features.get("indicator_score", 0),
                                features.get("rate_diff_score", 0),
                                features.get("cot_score", 0),
                                features.get("sentiment_score", 0),
                                n_before, n_after,
                                (stats.get("live_accuracy") or 0) * 100,
                                recent_pred.weight_shift,
                            )

                            # Refresh currency strength snapshot after learning
                            pred_strength = predict_strength(currency, features)
                            new_confidence = pred_strength.confidence_pct
                            persist_currency_strength(
                                currency        = currency,
                                strength_score  = pred_strength.strength_score,
                                indicator_score = float(recent_pred.composite_score or 0.0),
                                rate_diff_score = rate_diff_to_score(rd),
                                cot_score       = cot_to_score(cot),
                                sentiment_score = sentiment_to_score(sent),
                                confidence_pct  = pred_strength.confidence_pct,
                            )
                        except Exception as le:
                            log.warning("River learn_one failed for %s/%s: %s", code, currency, le)

                    # ── Post-release Telegram alert ───────────────────────────
                    post_sent = db.query(AlertLog).filter(
                        AlertLog.event_code       == code,
                        AlertLog.release_time_str == rel_str,
                        AlertLog.alert_type       == "POST_RELEASE",
                    ).first()
                    if not post_sent:
                        # Compute monthly W/L for this currency
                        try:
                            from datetime import date
                            _month_start = datetime(now_utc.year, now_utc.month, 1)
                            _month_preds = (
                                db.query(PredictionModel)
                                .filter(
                                    PredictionModel.currency    == currency,
                                    PredictionModel.was_correct.isnot(None),
                                    PredictionModel.is_sample.is_(False),
                                    PredictionModel.is_late.is_(False),
                                    PredictionModel.created_at  >= _month_start,
                                )
                                .all()
                            )
                            wins_this_month   = sum(1 for p in _month_preds if p.was_correct is True)
                            losses_this_month = sum(1 for p in _month_preds if p.was_correct is False)
                        except Exception:
                            wins_this_month   = 0
                            losses_this_month = 0

                        send_post_release_alert(
                            pred              = recent_pred,
                            actual            = actual,
                            forecast          = forecast,
                            n_trained_before  = n_before,
                            n_trained_after   = n_after,
                            wins_this_month   = wins_this_month,
                            losses_this_month = losses_this_month,
                            was_correct       = was_correct,
                            new_confidence    = new_confidence,
                            event_name        = ev.get("event_name", code),
                        )
                        db.add(AlertLog(
                            event_code       = code,
                            release_time_str = rel_str,
                            alert_type       = "POST_RELEASE",
                        ))
                        db.commit()

    except Exception as e:
        log.error("check_and_alert_upcoming error: %s", e)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# DAILY RATE-DIFFERENTIAL REFRESH
# ══════════════════════════════════════════════════════════════════════════════

def refresh_rate_differentials():
    """
    Fetch US Treasury yields and compute the USD rate differential.
    Runs daily at 06:00 UTC.
    """
    try:
        from data_sources import compute_rate_differentials
        diffs = compute_rate_differentials()
        log.info(
            "Rate differentials refreshed: %s",
            {ccy: round(d.spread_pct or 0, 3) for ccy, d in diffs.items()},
        )
    except Exception as e:
        log.error("Rate differential refresh failed: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# SENTIMENT REFRESH (every 12 hours)
# ══════════════════════════════════════════════════════════════════════════════

def refresh_sentiment_cycle():
    """
    Pull GDELT + RSS articles and run FinBERT for USD sentiment.
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


# ══════════════════════════════════════════════════════════════════════════════
# FULL CURRENCY STRENGTH REFRESH (daily)
# ══════════════════════════════════════════════════════════════════════════════

def refresh_currency_strengths():
    """
    Build the full 4-feature vector for USD and run River ARF prediction.
    Persists USD strength snapshot to the DB.
    Runs daily at 07:00 UTC (after rate-differential refresh at 06:00).
    """
    try:
        from data_sources import rate_diff_to_score, get_all_rate_differentials
        from sentiment import (
            get_latest_cot, get_latest_sentiment,
            cot_to_score, sentiment_to_score,
        )
        from indicators import get_indicator_scores_all_currencies, persist_currency_strength
        from learning import build_features, predict_strength

        rate_diffs       = get_all_rate_differentials()
        indicator_scores = get_indicator_scores_all_currencies()

        for ccy in CURRENCIES:
            rd   = rate_diffs.get(ccy)
            cot  = get_latest_cot(ccy)
            sent = get_latest_sentiment(ccy)

            ind_score = indicator_scores.get(ccy, 0.0)
            rd_score  = rate_diff_to_score(rd)
            c_score   = cot_to_score(cot)
            s_score   = sentiment_to_score(sent)

            features      = build_features(ind_score, rd_score, c_score, s_score)
            pred_strength = predict_strength(ccy, features)

            # Use direct composite until River has enough real training data
            from database import load_river_model as _lrm
            _, n_trained, _, _ = _lrm(ccy)
            if (n_trained or 0) < 20:
                weights = [0.50, 0.25, 0.15, 0.10]
                scores  = [ind_score, rd_score, c_score, s_score]
                composite = sum(w * s for w, s in zip(weights, scores))
                strength_score = round(max(-1.0, min(1.0, composite)), 4)
                confidence_pct = 40.0 + abs(strength_score) * 25.0
            else:
                strength_score = pred_strength.strength_score
                confidence_pct = pred_strength.confidence_pct

            persist_currency_strength(
                currency        = ccy,
                strength_score  = strength_score,
                indicator_score = ind_score,
                rate_diff_score = rd_score,
                cot_score       = c_score,
                sentiment_score = s_score,
                confidence_pct  = confidence_pct,
            )
            log.info(
                "Currency strength %s: score=%.3f conf=%.1f%%",
                ccy, strength_score, confidence_pct,
            )

    except Exception as e:
        log.error("Currency strength refresh failed: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# SEED CHECK — run once on startup if models are untrained
# ══════════════════════════════════════════════════════════════════════════════

def _maybe_seed_models():
    """
    Called once at startup.  Seeds any currency models that have n_trained == 0
    using current COT + rate-differential priors.  Safe to call repeatedly —
    already-trained models are skipped.
    """
    try:
        from learning import seed_models_with_priors
        seeded = seed_models_with_priors()
        if seeded:
            log.info("Seeded River models for: %s", list(seeded.keys()))
        else:
            log.info("All River models already have training data — seed skipped.")
    except Exception as e:
        log.warning("Model seeding failed: %s", e)


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

    # Daily at 06:00 UTC — rate differentials
    scheduler.add_job(
        refresh_rate_differentials,
        trigger="cron",
        hour=6, minute=0,
        id="rate_diff_job",
    )

    # Daily at 07:00 UTC — full currency strength cycle
    scheduler.add_job(
        refresh_currency_strengths,
        trigger="cron",
        hour=7, minute=0,
        id="strength_job",
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

    scheduler.start()

    # Seed models on startup (non-blocking — runs in same thread before jobs fire)
    _maybe_seed_models()

    log.info(
        "Scheduler started: alert=1min | rate_diff=06:00 UTC | "
        "strengths=07:00 UTC | sentiment=00:30/12:30 UTC | cot=Fri 16:00 UTC"
    )


def stop_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown()
        log.info("Background scheduler stopped.")
