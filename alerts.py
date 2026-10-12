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
