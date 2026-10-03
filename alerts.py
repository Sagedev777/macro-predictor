"""
alerts.py — Telegram alert sender.

Sends a pre-formatted message to your Telegram chat with:
  - Event name + release time
  - BEAT/MISS/INLINE lean with confidence %
  - Affected majors (from trade_signals in events.py)
  - Per-indicator breakdown table
"""

import os
import logging
import requests
from dotenv import load_dotenv
from config.events import EVENTS

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


def _format_pair(signal: str) -> str:
    """
    Format a trade signal string for display.
    'BUY USDJPY' → 'BUY USD/JPY'
    'SELL XAUUSD' → 'SELL XAU/USD'
    Leaves WAIT/NO BIAS signals untouched.
    """
    parts = signal.strip().split(" ", 1)
    if len(parts) != 2:
        return signal
    direction, sym = parts
    sym = sym.strip()
    # Insert slash into 6-char forex pairs; handle XAUUSD as XAU/USD
    if len(sym) == 6:
        fmtSym = f"{sym[:3]}/{sym[3:]}"
    else:
        fmtSym = sym
    return f"{direction} {fmtSym}"


def _format_prediction_message(prediction: dict, release_time: str = None) -> str:
    """Build the Telegram message from a prediction dict."""
    event_code = prediction["event_code"]
    direction  = prediction["lean_direction"]
    confidence = prediction["confidence_pct"]
    indicators = prediction["indicator_breakdown"]

    # Normalize BEAT→BULLISH, MISS→BEARISH for config lookups
    dir_key   = _normalize_direction(direction)
    event_cfg = EVENTS.get(event_code, {})
    currency  = event_cfg.get("currency", prediction.get("currency", "USD"))

    # Direction label and emoji
    if dir_key == "BULLISH":
        dir_emoji = "🟢"
        dir_label = "BUY"
    elif dir_key == "BEARISH":
        dir_emoji = "🔴"
        dir_label = "SELL"
    else:
        dir_emoji = "🟡"
        dir_label = "HOLD"

    conf_bar = "█" * int(confidence / 10) + "░" * (10 - int(confidence / 10))

    # Affected majors — sourced exclusively from trade_signals in events.py
    trade_signals = prediction.get("trade_signals")
    if not trade_signals:
        trade_signals = event_cfg.get("trade_signals", {}).get(dir_key, [])

    if isinstance(trade_signals, str):
        trade_signals = [s.strip() for s in trade_signals.split(",") if s.strip()]

    # Filter out WAIT/NO BIAS entries, format for display
    major_signals = [
        s for s in trade_signals
        if not s.upper().startswith("WAIT")
    ]
    majors_line = " • ".join(f"`{_format_pair(s)}`" for s in major_signals) if major_signals else "`—`"

    lines = [
        f"📊 *PRE-RELEASE SIGNAL — {event_code}*",
        "",
        f"{event_code} → {dir_emoji} {dir_label} {currency}",
        f"Confidence: `{confidence:.0f}%` `{conf_bar}`",
        "",
        "🎯 *Affected majors:*",
        majors_line,
    ]

    if release_time:
        lines += ["", f"🕐 Release: `{release_time}`"]

    lines += [
        "",
        "─────────────────────",
        "📋 *Indicator Details*",
    ]

    for ind in indicators:
        sig  = ind.get("signal", 0)
        emoji = SIGNAL_EMOJI.get(sig, "⚪")
        z    = ind.get("z_score")
        z_str = f"z={z:+.2f}" if z is not None else "z=n/a"
        desc  = ind.get("description", ind.get("fred_series", ""))
        cleaned = desc.replace("_", " ").replace("*", "")
        short   = cleaned[:50] + "…" if len(cleaned) > 50 else cleaned
        sig_word = "BULLISH" if sig > 0 else ("BEARISH" if sig < 0 else "NEUTRAL")
        lines.append(f"• {emoji} {sig_word}  `{z_str}`  _{short}_")

    lines += [
        "",
        "─────────────────────",
        "⚠️ _Signal is probabilistic. Apply your own risk management._",
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
