"""
alerts.py — Telegram alert sender.

Sends a pre-formatted message to your Telegram chat with:
  - Event name + release time
  - BEAT/MISS/INLINE lean with confidence %
  - Trade signals
  - Per-indicator breakdown table
"""

import os
import re
import logging
import requests
from dotenv import load_dotenv
from config.events import EVENTS

load_dotenv()
log = logging.getLogger("alerts")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID", "")

DIRECTION_EMOJI = {
    "BEAT":   "🟢 BEAT",
    "MISS":   "🔴 MISS",
    "INLINE": "🟡 INLINE",
}

SIGNAL_EMOJI = {
    1:  "✅ BULLISH",
    -1: "❌ BEARISH",
    0:  "⚪ NEUTRAL",
}


def _normalize_direction(direction: str) -> str:
    """
    Normalize lean_direction to the key used in EVENTS config.
    The indicator engine returns 'BEAT'/'MISS'/'INLINE' but EVENTS uses
    'BULLISH'/'BEARISH'/'INLINE' as keys for trade_signals, event_labels, explanations.
    """
    d = (direction or "").upper()
    if d in ("BEAT", "BULLISH"):
        return "BULLISH"
    if d in ("MISS", "BEARISH"):
        return "BEARISH"
    return "INLINE"


def _format_prediction_message(prediction: dict, release_time: str = None) -> str:
    """Build the Telegram message from a prediction dict."""
    event_code   = prediction["event_code"]
    direction    = prediction["lean_direction"]
    confidence   = prediction["confidence_pct"]
    composite    = prediction["composite_score"]
    indicators   = prediction["indicator_breakdown"]

    # Normalize so BEAT→BULLISH, MISS→BEARISH for config lookups
    dir_key = _normalize_direction(direction)

    event_cfg   = EVENTS.get(event_code, {})
    event_label = prediction.get("event_label") or event_cfg.get("event_labels", {}).get(dir_key, direction)
    explanation = prediction.get("explanation") or event_cfg.get("explanations", {}).get(dir_key, "")

    macro_bias = "🟢 USD BULLISH" if dir_key == "BULLISH" else ("🔴 USD BEARISH" if dir_key == "BEARISH" else "🟡 NEUTRAL")
    conf_bar = "█" * int(confidence / 10) + "░" * (10 - int(confidence / 10))

    lines = [
        f"📊 *PRE-RELEASE SIGNAL — {event_code}*",
        f"",
        f"Macro Bias: *{macro_bias}*",
        f"Event Lean: *{event_label}*",
        f"Confidence: `{confidence:.0f}%` `{conf_bar}`",
        f"Composite Score: `{composite:+.3f}`",
    ]

    if release_time:
        lines += ["", f"🕐 Release: `{release_time} UTC`"]

    if explanation:
        clean_exp = explanation.replace("_", " ").replace("*", "")
        lines += ["", "─────────────────────", f"💡 *Outlook:* _{clean_exp}_"]

    # Standard affected pairs fallback per event
    default_pairs = {
        "NFP": ["EURUSD", "USDJPY", "GBPUSD", "XAUUSD"],
        "CPI": ["EURUSD", "USDJPY", "XAUUSD", "GBPUSD"],
        "CORE_CPI": ["EURUSD", "USDJPY", "XAUUSD", "GBPUSD"],
        "PPI": ["EURUSD", "USDJPY", "XAUUSD"],
        "JOBLESS_CLAIMS": ["EURUSD", "USDJPY", "XAUUSD", "GBPUSD"],
        "UNEMPLOYMENT_RATE": ["EURUSD", "USDJPY", "GBPUSD", "XAUUSD"],
        "GDP": ["EURUSD", "USDJPY", "US500", "XAUUSD"],
        "FOMC": ["EURUSD", "USDJPY", "XAUUSD", "US500", "US30"],
        "RETAIL_SALES": ["EURUSD", "USDJPY", "US30", "XAUUSD"],
        "ISM_MFG": ["USDJPY", "EURUSD", "US30"],
        "CONSUMER_CONFIDENCE": ["EURUSD", "USDJPY", "US500"],
    }.get(event_code, ["EURUSD", "USDJPY", "GBPUSD", "XAUUSD"])

    # Add trade signals & affected pairs — always look up using normalized direction key
    trade_signals = prediction.get("trade_signals")
    if not trade_signals:
        # Try normalized key first (BULLISH/BEARISH/INLINE)
        trade_signals = event_cfg.get("trade_signals", {}).get(dir_key, [])
    if not trade_signals:
        # Final fallback: try raw direction string
        trade_signals = event_cfg.get("trade_signals", {}).get(direction, [])

    if isinstance(trade_signals, str):
        trade_signals = [s.strip() for s in trade_signals.split(",") if s.strip()] or [trade_signals]

    # Extract all asset/currency pairs from the signals
    extracted_pairs = []
    if trade_signals:
        for ts in trade_signals:
            for word in ts.split():
                clean_word = re.sub(r"[^A-Za-z0-9]", "", word).upper()
                if clean_word in ("USDJPY", "EURUSD", "GBPUSD", "XAUUSD", "US500", "US30", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD", "GOLD"):
                    if clean_word not in extracted_pairs:
                        extracted_pairs.append(clean_word)

    final_pairs = extracted_pairs if extracted_pairs else default_pairs

    lines += ["", "─────────────────────", "🎯 *Pairs to be Affected:*"]
    lines.append(" • ".join([f"`{p}`" for p in final_pairs]))

    if trade_signals:
        lines += ["", "⚡ *Trade Execution Signals:*"]
        for ts in trade_signals:
            lines.append(f"• `{ts}`")

    lines += ["", "─────────────────────", "*Leading Indicators:*"]

    for ind in indicators:
        sig_str = SIGNAL_EMOJI.get(ind.get("signal", 0), "⚪ NEUTRAL")
        z = ind.get("z_score")
        z_str = f"z={z:+.2f}" if z is not None else "z=n/a"
        desc = ind.get("description", ind.get("fred_series", ""))
        # Truncate and clean description to avoid broken telegram markdown
        cleaned_desc = desc.replace("_", " ").replace("*", "")
        short_desc = cleaned_desc[:45] + "…" if len(cleaned_desc) > 45 else cleaned_desc
        lines.append(f"• {sig_str}  `{z_str}`  _{short_desc}_")

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
