"""
alerts.py — Telegram alert sender.

Sends pre-formatted messages to your Telegram chat:
  Pre-release (10 min before):
    - Event name + release time
    - BEAT/MISS/INLINE economic-number lean with confidence bar
    - Per-indicator breakdown

  Post-release (immediately on actual posting):
    - Actual vs forecast/surprise
    - Whether prediction was confirmed or flipped
    - Updated confidence bar after learn_one()
    - Monthly W/L record
"""

import os
import logging
import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("alerts")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

SIGNAL_EMOJI = {
    1:  "✅",
    -1: "❌",
    0:  "⚪",
}


def _normalize_direction(direction: str) -> str:
    """Normalize lean_direction to BULLISH/BEARISH/INLINE for config lookups."""
    d = (direction or "").upper()
    if d in ("BEAT", "BULLISH"):
        return "BULLISH"
    if d in ("MISS", "BEARISH"):
        return "BEARISH"
    return "INLINE"


def _direction_emoji_label(direction: str) -> tuple[str, str]:
    """Return (emoji, label) for an economic-number forecast."""
    dir_key = _normalize_direction(direction)
    if dir_key == "BULLISH":
        return "🟢", "BEAT"
    if dir_key == "BEARISH":
        return "🔴", "MISS"
    return "🟡", "INLINE"


def _conf_bar(confidence_pct: float) -> str:
    """Build a 10-block confidence bar from a 0–100 float."""
    filled = int(confidence_pct / 10)
    filled = max(0, min(10, filled))
    return "█" * filled + "░" * (10 - filled)


def _format_prediction_message(prediction: dict, release_time: str = None) -> str:
    """Build the pre-release Telegram message from a prediction dict."""
    event_code = prediction["event_code"]
    direction  = prediction["lean_direction"]
    confidence = prediction["confidence_pct"]
    indicators = prediction.get("indicator_breakdown", [])

    currency = prediction.get("currency", "USD")
    event_name = prediction.get("event_display_name", event_code)

    dir_emoji, dir_label = _direction_emoji_label(direction)
    bar = _conf_bar(confidence)

    # Forecast / Previous
    forecast = prediction.get("forecast")
    previous = prediction.get("previous")
    forecast_str = f"{forecast}" if forecast is not None else "n/a"
    previous_str = f"{previous}" if previous is not None else "n/a"

    # Release time line
    rel_line = release_time if release_time else "—"

    # Indicator detail lines
    ind_lines = []
    for ind in indicators:
        sig      = ind.get("signal", 0)
        ind_emoji = SIGNAL_EMOJI.get(sig, "⚪")
        z        = ind.get("z_score")
        z_str    = f"z={z:+.2f}" if z is not None else "z=n/a"
        desc     = ind.get("description", ind.get("fred_series", ""))
        cleaned  = desc.replace("_", " ").replace("*", "")
        short    = cleaned[:50] + "…" if len(cleaned) > 50 else cleaned
        sig_word = "BULLISH" if sig > 0 else ("BEARISH" if sig < 0 else "NEUTRAL")
        ind_lines.append(f"• {ind_emoji} {sig_word}  {z_str}  {short}")

    indicator_block = "\n".join(ind_lines) if ind_lines else "• (no indicators)"

    lines = [
        f"🔔 UPCOMING — {event_name}",
        f"📅 {rel_line} ({currency})",
        f"Forecast: {forecast_str} | Previous: {previous_str}",
        "",
        f"Economic-number lean: {dir_emoji} {dir_label} vs consensus",
        f"Heuristic score {bar} {confidence:.0f}% (not a probability)",
        "",
        "─────────────────────",
        "📋 Indicator details",
        indicator_block,
        "─────────────────────",
        "Gold price reaction is modelled separately. This is not a trade instruction.",
    ]

    return "\n".join(lines)


def send_telegram_alert(prediction: dict, release_time: str = None) -> bool:
    """Send prediction to Telegram. Returns True on success."""
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram not configured — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")
        return False

    message = _format_prediction_message(prediction, release_time)

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    CHAT_ID,
        "text":       message,
        "parse_mode": "Markdown",
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        log.info("Telegram alert sent for %s", prediction["event_code"])
        return True
    except Exception as e:
        log.error("Telegram send failed: %s (response: %s)", e, getattr(r, 'text', ''))
        return False


def send_post_release_alert(
    pred,                   # PredictionModel ORM row
    actual: float,
    forecast: float,
    n_trained_before: int,
    n_trained_after: int,
    wins_this_month: int,
    losses_this_month: int,
    was_correct: bool,
    new_confidence: float,
    event_name: str = None,
) -> bool:
    """
    Send the post-release outcome alert to Telegram.

    Format:
      ✅ RELEASED — {event_name}
      Actual: {actual} | Forecast: {forecast} | Surprise: {sign}{val:.2f}

      Pre-release call: {emoji} {direction} {currency}, {old_confidence:.0f}%
      Result: ✅ Confirmed  (or ❌ Flipped)

      Updated confidence {bar} {new_confidence:.0f}%

      🎯 Majors — current read:
      {majors_list}

      📊 Model: {currency} now trained on {n_trained_after} real outcomes (was {n_trained_before})
      This month: {wins}W – {losses}L
    """
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram not configured — TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing")
        return False

    event_code = pred.event_code
    currency   = (pred.currency or "USD").upper()
    ev_name    = event_name or pred.event_display_name or event_code
    dir_emoji, dir_label = _direction_emoji_label(pred.lean_direction)

    old_confidence = pred.confidence_pct or 0.0
    surprise = actual - forecast
    surprise_sign = "+" if surprise > 0 else ""
    result_tag = "✅ Confirmed" if was_correct else "❌ Flipped"
    new_bar = _conf_bar(new_confidence)

    lines = [
        f"✅ RELEASED — {ev_name}",
        f"Actual: {actual} | Forecast: {forecast} | Surprise: {surprise_sign}{surprise:.2f}",
        "",
        f"Pre-release economic-number lean: {dir_emoji} {dir_label} {currency}, {old_confidence:.0f}%",
        f"Result: {result_tag}",
        "",
        f"Updated confidence {new_bar} {new_confidence:.0f}%",
        "",
        "This describes the economic print versus consensus, not the gold-price reaction.",
        "",
        f"📊 Model: {currency} now trained on {n_trained_after} real outcomes (was {n_trained_before})",
        f"This month: {wins_this_month}W – {losses_this_month}L",
    ]

    message = "\n".join(lines)
    url     = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message, "parse_mode": "Markdown"}

    try:
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        log.info("Post-release alert sent for %s", event_code)
        return True
    except Exception as e:
        log.error("Post-release alert send failed: %s (response: %s)", e, getattr(r, 'text', ''))
        return False


def send_test_message() -> bool:
    """Send a test ping to confirm Telegram is working."""
    if not BOT_TOKEN or not CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": "✅ *TitanFX Sage — MacroPredictor* connected! Real-time pre-release signals & outcome alerts are live.",
            "parse_mode": "Markdown",
        }, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        log.error("Telegram test failed: %s", e)
        return False


# ══════════════════════════════════════════════════════════════════════════════
# XAU/USD GOLD MODEL TELEGRAM ALERTS (Pre-Release & Outcome)
# ══════════════════════════════════════════════════════════════════════════════

def _extract_gold_forecast_data(gf) -> dict:
    """Extract standard dictionary attributes from GoldForecast ORM model or dict."""
    import json
    if isinstance(gf, dict):
        return gf

    event_names = []
    if getattr(gf, "event_names_json", None):
        try:
            event_names = json.loads(gf.event_names_json)
        except Exception:
            event_names = []

    probs = None
    if getattr(gf, "probabilities_json", None):
        try:
            probs = json.loads(gf.probabilities_json)
        except Exception:
            probs = None

    features = {}
    if getattr(gf, "feature_snapshot", None):
        try:
            features = json.loads(gf.feature_snapshot)
        except Exception:
            features = {}

    missing_features = [
        name for name, item in features.items()
        if isinstance(item, dict) and (
            item.get("value") is None or not str(item.get("status", "")).startswith("available")
        )
    ]

    cutoff_str = ""
    if getattr(gf, "created_at", None):
        cutoff_str = gf.created_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    return {
        "id": getattr(gf, "id", None),
        "release_moment_id": getattr(gf, "release_moment_id", None),
        "release_time_utc": getattr(gf, "release_time_utc", None),
        "event_family": getattr(gf, "event_family", "other"),
        "event_names": event_names,
        "horizon_minutes": getattr(gf, "horizon_minutes", 5),
        "forecast_status": getattr(gf, "forecast_status", "warming_up"),
        "direction": getattr(gf, "forecast_direction", None),
        "probabilities": probs,
        "n_trained": getattr(gf, "n_trained", 0),
        "created_at_str": cutoff_str,
        "missing_features": missing_features,
        "model_version": getattr(gf, "model_version", "gold_arf_v1"),
        "gold_price_at_release": getattr(gf, "gold_price_at_release", None),
        "gold_change_1m_pct": getattr(gf, "gold_change_1m_pct", None),
        "gold_change_5m_pct": getattr(gf, "gold_change_5m_pct", None),
        "gold_change_15m_pct": getattr(gf, "gold_change_15m_pct", None),
        "gold_change_30m_pct": getattr(gf, "gold_change_30m_pct", None),
        "max_up_5m_pct": getattr(gf, "max_up_5m_pct", None),
        "max_down_5m_pct": getattr(gf, "max_down_5m_pct", None),
        "outcome_label": getattr(gf, "outcome_label", None),
    }


def format_gold_prediction_message(
    gold_forecast,
    stage_minutes: int,
    scheduled_time_str: str,
) -> str:
    """
    Format a complete, transparent pre-release XAU/USD forecast notification.
    Strictly uses real model state without fabricated probabilities.
    """
    data = _extract_gold_forecast_data(gold_forecast)
    event_names = data.get("event_names") or []
    if isinstance(event_names, list):
        names_str = ", ".join(event_names) if event_names else data.get("event_family", "USD Release")
    else:
        names_str = str(event_names)

    direction = data.get("direction")
    dir_labels = {
        "BULLISH": "🟢 BULLISH (Upward Reaction Expected)",
        "BEARISH": "🔴 BEARISH (Downward Reaction Expected)",
        "NEUTRAL": "⚪ NEUTRAL (Subdued / Rangebound)",
    }
    dir_str = dir_labels.get((direction or "").upper(), "🟡 WARMING UP (No Directional Bias)")

    probabilities = data.get("probabilities")
    n_trained = data.get("n_trained", 0)
    if probabilities and all(k in probabilities for k in ("bullish", "bearish", "neutral")):
        p_up = probabilities["bullish"] * 100.0
        p_dn = probabilities["bearish"] * 100.0
        p_nt = probabilities["neutral"] * 100.0
        prob_block = (
            f"📈 Model Probabilities (5m Horizon):\n"
            f"  • 🟢 Bullish (Gold Up):    {p_up:.1f}%\n"
            f"  • 🔴 Bearish (Gold Down):  {p_dn:.1f}%\n"
            f"  • ⚪ Neutral (Rangebound): {p_nt:.1f}%"
        )
    else:
        prob_block = (
            f"📈 Model Probabilities: Withheld\n"
            f"  (Model warming up — n={n_trained} of 10 required release moments trained)"
        )

    missing = data.get("missing_features") or []
    if missing:
        missing_str = f"⚠️ Warning: {len(missing)} input(s) incomplete: {', '.join(missing[:3])}"
    else:
        missing_str = "✅ Input Quality: All leading indicator inputs available at snapshot"

    horizon = data.get("horizon_minutes", 5)
    model_ver = data.get("model_version", "gold_arf_v1")
    created_at = data.get("created_at_str") or "at snapshot cutoff"

    lines = [
        f"🔔 UPCOMING XAU/USD FORECAST — {names_str}",
        f"⏰ Scheduled: {scheduled_time_str} (in {stage_minutes}m)",
        f"⏱ Snapshot Cutoff: {created_at}",
        "─────────────────────",
        f"🎯 Horizon: Primary {horizon}-minute reaction window",
        f"📊 Anticipated Bias: {dir_str}",
        "",
        prob_block,
        "",
        f"🧠 Model: {model_ver} (River Adaptive Random Forest)",
        f"📚 Training Base: {n_trained} historical {data.get('event_family', 'USD')} release moments",
        missing_str,
        "─────────────────────",
        "⚠️ Probabilistic macroeconomic model. This is NOT trading advice or a guaranteed execution signal.",
    ]
    return "\n".join(lines)


def format_gold_outcome_message(gold_forecast) -> str:
    """
    Format a post-release outcome report confirming whether the model predicted the truth or failed.
    """
    data = _extract_gold_forecast_data(gold_forecast)
    event_names = data.get("event_names") or []
    if isinstance(event_names, list):
        names_str = ", ".join(event_names) if event_names else data.get("event_family", "USD Release")
    else:
        names_str = str(event_names)

    rel_time = data.get("release_time_utc") or "Release"
    horizon = data.get("horizon_minutes", 5)

    gold_price = data.get("gold_price_at_release")
    p_str = f"${gold_price:,.2f}" if gold_price is not None else "n/a"

    c1m = data.get("gold_change_1m_pct")
    c5m = data.get("gold_change_5m_pct")
    c15m = data.get("gold_change_15m_pct")
    c30m = data.get("gold_change_30m_pct")
    c5m_str = f"{c5m:+.4f}%" if c5m is not None else "n/a"
    c1m_str = f"{c1m:+.4f}%" if c1m is not None else "n/a"
    c15m_str = f"{c15m:+.4f}%" if c15m is not None else "n/a"
    c30m_str = f"{c30m:+.4f}%" if c30m is not None else "n/a"

    max_up = data.get("max_up_5m_pct")
    max_down = data.get("max_down_5m_pct")
    up_str = f"{max_up:+.2f}%" if max_up is not None else "n/a"
    dn_str = f"{max_down:+.2f}%" if max_down is not None else "n/a"

    realized_label = data.get("outcome_label") or "UNDETERMINED"
    predicted_dir = data.get("direction")

    # Evaluate Truth vs Failed
    if predicted_dir in ("BULLISH", "BEARISH", "NEUTRAL"):
        if realized_label == predicted_dir:
            verdict_icon = "✅"
            verdict_status = "PREDICTION CONFIRMED (TRUTH)"
            verdict_detail = f"Model accurately anticipated the 5-minute {realized_label} reaction in XAU/USD."
        else:
            verdict_icon = "❌"
            verdict_status = "PREDICTION MISSED (FAILED)"
            verdict_detail = f"Model anticipated {predicted_dir}, but realized 5m market outcome was {realized_label} ({c5m_str})."
    else:
        verdict_icon = "⚪"
        verdict_status = "BASELINE OBSERVATION"
        verdict_detail = f"Model was warming up; realized outcome {realized_label} ({c5m_str}) ingested for training."

    lines = [
        f"📢 XAU/USD OUTCOME & VERIFICATION — {names_str}",
        f"📅 Release Time: {rel_time}",
        f"⏱ Graded Horizon: {horizon}-minute reaction window",
        "─────────────────────",
        "📊 Realized Market Reaction:",
        f"  • Price at release: {p_str}",
        f"  • 5m Reaction: {c5m_str} ({realized_label})",
        f"  • 5m Excursion: High {up_str} | Low {dn_str}",
        f"  • Multi-horizon: 1m={c1m_str} | 15m={c15m_str} | 30m={c30m_str}",
        "",
        f"🎯 Pre-Release Prediction: {predicted_dir or 'WARMING UP'}",
        f"🔍 Verification: {verdict_icon} {verdict_status}",
        f"   {verdict_detail}",
        "─────────────────────",
        "🧠 Incremental Learning: Outcome ingested into online River model.",
    ]
    return "\n".join(lines)


def send_gold_prediction_alert(
    db,
    gold_forecast,
    stage_minutes: int,
    scheduled_time_str: str,
    sender_func=None,
) -> tuple[bool, str | None]:
    """
    Send an idempotent pre-release gold prediction Telegram alert.
    Tracks delivery status, attempts, and errors in the AlertLog table.
    """
    from datetime import datetime, timezone
    from database import AlertLog

    data = _extract_gold_forecast_data(gold_forecast)
    rel_time = data.get("release_time_utc") or ""
    moment_id = data.get("release_moment_id") or rel_time
    alert_type = f"GOLD_PRE_{stage_minutes}M"
    idempotency_key = f"gold_pre|{moment_id}|{stage_minutes}m"
    event_code_primary = data.get("event_family", "GOLD").upper()

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    log_entry = db.query(AlertLog).filter_by(idempotency_key=idempotency_key).first()
    if log_entry and log_entry.status == "sent":
        log.info("Gold prediction alert already sent for %s (%dm)", moment_id, stage_minutes)
        return False, "already_sent"

    if log_entry and log_entry.status == "failed":
        if log_entry.delivery_attempts >= 3:
            msg = f"Max delivery attempts ({log_entry.delivery_attempts}) reached for {idempotency_key}"
            log.warning(msg)
            return False, msg
        log_entry.delivery_attempts += 1
        log_entry.last_attempt_at = now_utc
    elif not log_entry:
        log_entry = AlertLog(
            event_code=event_code_primary,
            release_time_str=rel_time,
            alert_type=alert_type,
            idempotency_key=idempotency_key,
            status="pending",
            delivery_attempts=1,
            last_attempt_at=now_utc,
        )
        db.add(log_entry)
        try:
            db.flush()
        except Exception as fe:
            db.rollback()
            log.warning("AlertLog flush collision for %s: %s", idempotency_key, fe)
            return False, "collision"

    if not sender_func and (not BOT_TOKEN or not CHAT_ID):
        log_entry.status = "skipped"
        log_entry.error_message = "Telegram BOT_TOKEN or CHAT_ID missing"
        db.commit()
        log.warning("Telegram not configured; gold %dm alert skipped", stage_minutes)
        return False, "Telegram credentials not configured"

    msg_text = format_gold_prediction_message(gold_forecast, stage_minutes, scheduled_time_str)

    try:
        if sender_func:
            sender_func(msg_text)
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": msg_text}
            r = requests.post(url, json=payload, timeout=10)
            r.raise_for_status()

        log_entry.status = "sent"
        log_entry.sent_at = now_utc
        log_entry.error_message = None
        db.commit()
        log.info("Gold prediction alert sent: %s (%dm)", moment_id, stage_minutes)
        return True, None
    except Exception as e:
        db.rollback()
        fail_entry = db.query(AlertLog).filter_by(idempotency_key=idempotency_key).first()
        if not fail_entry:
            fail_entry = AlertLog(
                event_code=event_code_primary,
                release_time_str=rel_time,
                alert_type=alert_type,
                idempotency_key=idempotency_key,
                status="failed",
                delivery_attempts=1,
                last_attempt_at=now_utc,
                error_message=str(e),
            )
            db.add(fail_entry)
        else:
            fail_entry.status = "failed"
            fail_entry.error_message = str(e)
            fail_entry.last_attempt_at = now_utc
        try:
            db.commit()
        except Exception:
            db.rollback()
        log.error("Failed sending gold prediction alert for %s: %s", idempotency_key, e)
        return False, str(e)

def send_gold_outcome_alert(
    db,
    gold_forecast,
    sender_func=None,
) -> tuple[bool, str | None]:
    """
    Send an idempotent post-release gold outcome verification Telegram alert.
    Reports whether the model predicted truth or failed.
    """
    from datetime import datetime, timezone
    from database import AlertLog

    data = _extract_gold_forecast_data(gold_forecast)
    rel_time = data.get("release_time_utc") or ""
    moment_id = data.get("release_moment_id") or rel_time
    alert_type = "GOLD_OUTCOME"
    idempotency_key = f"gold_outcome|{moment_id}"
    event_code_primary = data.get("event_family", "GOLD").upper()

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

    log_entry = db.query(AlertLog).filter_by(idempotency_key=idempotency_key).first()
    if log_entry and log_entry.status == "sent":
        log.info("Gold outcome alert already sent for %s", moment_id)
        return False, "already_sent"

    if log_entry and log_entry.status == "failed":
        if log_entry.delivery_attempts >= 3:
            msg = f"Max delivery attempts ({log_entry.delivery_attempts}) reached for {idempotency_key}"
            log.warning(msg)
            return False, msg
        log_entry.delivery_attempts += 1
        log_entry.last_attempt_at = now_utc
    elif not log_entry:
        log_entry = AlertLog(
            event_code=event_code_primary,
            release_time_str=rel_time,
            alert_type=alert_type,
            idempotency_key=idempotency_key,
            status="pending",
            delivery_attempts=1,
            last_attempt_at=now_utc,
        )
        db.add(log_entry)
        try:
            db.flush()
        except Exception as fe:
            db.rollback()
            log.warning("AlertLog flush collision for %s: %s", idempotency_key, fe)
            return False, "collision"

    if not sender_func and (not BOT_TOKEN or not CHAT_ID):
        log_entry.status = "skipped"
        log_entry.error_message = "Telegram BOT_TOKEN or CHAT_ID missing"
        db.commit()
        log.warning("Telegram not configured; gold outcome alert skipped")
        return False, "Telegram credentials not configured"

    msg_text = format_gold_outcome_message(gold_forecast)

    try:
        if sender_func:
            sender_func(msg_text)
        else:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
            payload = {"chat_id": CHAT_ID, "text": msg_text}
            r = requests.post(url, json=payload, timeout=10)
            r.raise_for_status()

        log_entry.status = "sent"
        log_entry.sent_at = now_utc
        log_entry.error_message = None
        db.commit()
        log.info("Gold outcome alert sent for %s", moment_id)
        return True, None
    except Exception as e:
        db.rollback()
        fail_entry = db.query(AlertLog).filter_by(idempotency_key=idempotency_key).first()
        if not fail_entry:
            fail_entry = AlertLog(
                event_code=event_code_primary,
                release_time_str=rel_time,
                alert_type=alert_type,
                idempotency_key=idempotency_key,
                status="failed",
                delivery_attempts=1,
                last_attempt_at=now_utc,
                error_message=str(e),
            )
            db.add(fail_entry)
        else:
            fail_entry.status = "failed"
            fail_entry.error_message = str(e)
            fail_entry.last_attempt_at = now_utc
        try:
            db.commit()
        except Exception:
            db.rollback()
        log.error("Failed sending gold outcome alert for %s: %s", idempotency_key, e)
        return False, str(e)
