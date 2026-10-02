"""
price_data.py — Live OHLC price fetching and ATR-based order-level suggestions.

Data source: Twelve Data (https://twelvedata.com)
  - Free tier: 800 API calls/day, 8 calls/minute
  - Requires TWELVE_DATA_API_KEY in .env
  - New account required: register at https://twelvedata.com/register

ATR calculation: pandas-ta ATR(14) on daily candles.

Order-level suggestion formula (per pair, per upcoming event):
  Given model bias direction (BUY/SELL) and current price P:
    entry     = P + (1 × ATR)   if BUY   (buy-stop above market)
                P - (1 × ATR)   if SELL  (sell-stop below market)
    stop_loss = entry - (1.5 × ATR) if BUY
                entry + (1.5 × ATR) if SELL
    take_profit = entry + (2 × ATR) if BUY   (1:2 risk-reward)
                  entry - (2 × ATR) if SELL

  XAUUSD uses 1.5×ATR for entry distance (gold is more volatile intraday).
  All levels are rounded to the instrument's standard decimal precision.

Public interface:
  fetch_ohlc(pair, interval, bars)       → pd.DataFrame | None
  get_current_price(pair)                → float | None
  compute_atr(pair, period)              → float | None
  build_order_suggestion(pair, bias, confidence_pct, event_code, release_time_utc)
                                         → OrderSuggestion
  build_all_order_suggestions(event_code, release_time_utc, pair_biases)
                                         → list[OrderSuggestion]
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger("price_data")

# ── Twelve Data configuration ─────────────────────────────────────────────────
TWELVE_DATA_BASE = "https://api.twelvedata.com"
TWELVE_DATA_KEY  = os.getenv("TWELVE_DATA_API_KEY", "")

# Rate-limit guard: 8 calls/minute on free tier → 7.5s minimum between calls
_TWELVE_DATA_INTERVAL_S = 7.5
_last_call_ts: float = 0.0

# In-process OHLC cache: key = (pair, interval, bars) → (timestamp, DataFrame)
_ohlc_cache: dict[tuple, tuple] = {}
_OHLC_CACHE_TTL = 3600   # refresh hourly; prices only matter pre-event

# Decimal precision per instrument (used for rounding order levels)
_PAIR_PRECISION: dict[str, int] = {
    "EURUSD":  5, "GBPUSD":  5, "USDCHF":  5, "AUDUSD":  5,
    "NZDUSD":  5, "USDCAD":  5, "USDJPY":  3, "EURJPY":  3,
    "GBPJPY":  3, "AUDJPY":  3, "CADJPY":  3, "EURGBP":  5,
    "XAUUSD":  2,
}

# Entry ATR multiplier per instrument (gold needs wider pending-stop distance)
_ATR_ENTRY_MULT: dict[str, float] = {
    "XAUUSD": 1.5,
}
_ATR_ENTRY_MULT_DEFAULT = 1.0
_ATR_SL_MULT            = 1.5   # stop-loss distance from entry
_ATR_TP_MULT            = 2.0   # take-profit distance from entry (1:2 RR)


# ══════════════════════════════════════════════════════════════════════════════
# RESULT TYPE
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class OrderSuggestion:
    pair:              str
    bias:              str             # "BUY" | "SELL" | "NEUTRAL"
    current_price:     Optional[float]
    atr_14:            Optional[float]
    suggested_entry:   Optional[float]
    suggested_sl:      Optional[float]
    suggested_tp:      Optional[float]
    confidence_pct:    float
    event_code:        str
    release_time_utc:  Optional[str]
    is_reference_only: bool = True      # always True — not a guarantee
    note:              str  = ""


# ══════════════════════════════════════════════════════════════════════════════
# TWELVE DATA FETCHERS
# ══════════════════════════════════════════════════════════════════════════════

def _rate_limit_wait():
    """Enforce Twelve Data free-tier rate limit: max 8 calls/minute."""
    global _last_call_ts
    elapsed = time.time() - _last_call_ts
    if elapsed < _TWELVE_DATA_INTERVAL_S:
        time.sleep(_TWELVE_DATA_INTERVAL_S - elapsed)
    _last_call_ts = time.time()


def _twelve_data_symbol(pair: str) -> str:
    """
    Convert internal pair code to Twelve Data symbol format.
    EURUSD → EUR/USD, XAUUSD → XAU/USD, USDJPY → USD/JPY, etc.
    """
    p = pair.upper()
    if p == "XAUUSD":
        return "XAU/USD"
    if len(p) == 6:
        return f"{p[:3]}/{p[3:]}"
    return p   # pass through if already formatted


def fetch_ohlc(
    pair:     str,
    interval: str = "1day",
    bars:     int = 30,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLC candles from Twelve Data.

    Parameters:
      pair     — internal pair code (e.g. "EURUSD", "XAUUSD")
      interval — Twelve Data interval string: "1min","5min","15min","1h","1day"
      bars     — number of bars to fetch (30 gives enough for ATR(14) with headroom)

    Returns a DataFrame with columns [open, high, low, close, volume] indexed
    by datetime, or None on failure.
    """
    if not TWELVE_DATA_KEY:
        log.warning("TWELVE_DATA_API_KEY not set — price data unavailable.")
        return None

    cache_key = (pair.upper(), interval, bars)
    now_ts    = time.time()
    cached    = _ohlc_cache.get(cache_key)
    if cached and (now_ts - cached[0]) < _OHLC_CACHE_TTL:
        return cached[1]

    symbol = _twelve_data_symbol(pair)
    _rate_limit_wait()

    url = f"{TWELVE_DATA_BASE}/time_series"
    params = {
        "symbol":     symbol,
        "interval":   interval,
        "outputsize": bars,
        "apikey":     TWELVE_DATA_KEY,
        "format":     "JSON",
    }

    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        if data.get("status") == "error":
            log.error("Twelve Data error for %s: %s", pair, data.get("message", "unknown"))
            return None

        candles = data.get("values", [])
        if not candles:
            log.warning("Twelve Data returned no candles for %s", pair)
            return None

        rows = []
        for c in candles:
            try:
                rows.append({
                    "datetime": pd.to_datetime(c["datetime"]),
                    "open":     float(c["open"]),
                    "high":     float(c["high"]),
                    "low":      float(c["low"]),
                    "close":    float(c["close"]),
                    "volume":   float(c.get("volume", 0) or 0),
                })
            except (KeyError, ValueError):
                continue

        if not rows:
            return None

        df = pd.DataFrame(rows).set_index("datetime").sort_index()
        _ohlc_cache[cache_key] = (now_ts, df)
        log.info("Twelve Data: fetched %d %s candles for %s", len(df), interval, pair)
        return df

    except Exception as e:
        log.error("Twelve Data fetch failed for %s: %s", pair, e)
        return None


def get_current_price(pair: str) -> Optional[float]:
    """
    Return the most recent close price for a pair.
    Uses cached daily candles if available, else fetches fresh.
    """
    df = fetch_ohlc(pair, interval="1day", bars=5)
    if df is None or df.empty:
        return None
    return float(df["close"].iloc[-1])


# ══════════════════════════════════════════════════════════════════════════════
# ATR CALCULATION (pandas-ta)
# ══════════════════════════════════════════════════════════════════════════════

def compute_atr(pair: str, period: int = 14) -> Optional[float]:
    """
    Compute the 14-period Average True Range for a pair using pandas-ta.

    Fetches 30 daily candles (gives ATR(14) enough warm-up bars).
    Returns the most recent ATR value, or None if data is insufficient.
    """
    df = fetch_ohlc(pair, interval="1day", bars=period + 16)
    if df is None or len(df) < period + 1:
        log.warning("Insufficient candles for ATR(%d) on %s", period, pair)
        return None

    try:
        import pandas_ta as ta
        atr_series = ta.atr(
            high=df["high"],
            low=df["low"],
            close=df["close"],
            length=period,
        )
        if atr_series is None or atr_series.empty:
            return None
        latest_atr = atr_series.dropna().iloc[-1]
        return float(latest_atr)

    except ImportError:
        log.error("pandas-ta not installed — ATR calculation disabled.")
        return None
    except Exception as e:
        log.error("ATR computation failed for %s: %s", pair, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# ORDER-LEVEL SUGGESTION
# ══════════════════════════════════════════════════════════════════════════════

def _round_price(price: float, pair: str) -> float:
    """Round a price to the instrument's standard decimal precision."""
    precision = _PAIR_PRECISION.get(pair.upper(), 5)
    return round(price, precision)


def build_order_suggestion(
    pair:             str,
    bias:             str,              # "BUY" | "SELL" | "NEUTRAL"
    confidence_pct:   float,
    event_code:       str,
    release_time_utc: Optional[str] = None,
) -> OrderSuggestion:
    """
    Build an ATR-based pending-order suggestion for a pair + directional bias.

    Returns an OrderSuggestion with entry/SL/TP levels.
    All levels are marked is_reference_only=True — they are calculated
    reference points, not trade recommendations.

    When bias is NEUTRAL or price/ATR data is unavailable, entry/SL/TP
    will be None but the object is still returned (for consistent API shape).
    """
    p = pair.upper()
    note = "Calculated reference level only. Not a trade recommendation."

    if bias == "NEUTRAL":
        return OrderSuggestion(
            pair=p, bias=bias,
            current_price=None, atr_14=None,
            suggested_entry=None, suggested_sl=None, suggested_tp=None,
            confidence_pct=confidence_pct,
            event_code=event_code, release_time_utc=release_time_utc,
            note="No directional bias — no order level calculated.",
        )

    current_price = get_current_price(p)
    atr           = compute_atr(p)

    if current_price is None or atr is None or atr <= 0:
        return OrderSuggestion(
            pair=p, bias=bias,
            current_price=current_price, atr_14=atr,
            suggested_entry=None, suggested_sl=None, suggested_tp=None,
            confidence_pct=confidence_pct,
            event_code=event_code, release_time_utc=release_time_utc,
            note="Price/ATR data unavailable — check TWELVE_DATA_API_KEY.",
        )

    entry_mult = _ATR_ENTRY_MULT.get(p, _ATR_ENTRY_MULT_DEFAULT)

    if bias == "BUY":
        entry = _round_price(current_price + entry_mult * atr,  p)
        sl    = _round_price(entry          - _ATR_SL_MULT * atr, p)
        tp    = _round_price(entry          + _ATR_TP_MULT * atr, p)
    else:  # SELL
        entry = _round_price(current_price - entry_mult * atr,  p)
        sl    = _round_price(entry          + _ATR_SL_MULT * atr, p)
        tp    = _round_price(entry          - _ATR_TP_MULT * atr, p)

    # Persist to DB
    _persist_suggestion(
        event_code=event_code,
        release_time_utc=release_time_utc,
        pair=p,
        bias=bias,
        current_price=current_price,
        atr_14=atr,
        entry=entry,
        sl=sl,
        tp=tp,
        confidence_pct=confidence_pct,
    )

    return OrderSuggestion(
        pair=p,
        bias=bias,
        current_price=current_price,
        atr_14=round(atr, _PAIR_PRECISION.get(p, 5)),
        suggested_entry=entry,
        suggested_sl=sl,
        suggested_tp=tp,
        confidence_pct=confidence_pct,
        event_code=event_code,
        release_time_utc=release_time_utc,
        note=note,
    )


def build_all_order_suggestions(
    event_code:        str,
    release_time_utc:  Optional[str],
    pair_biases:       dict,   # dict[str, learning.PairBias]
) -> list[OrderSuggestion]:
    """
    Build OrderSuggestion for every pair in pair_biases.
    Respects Twelve Data rate limit by processing sequentially.
    Skips pairs where bias is NEUTRAL (no pending order makes sense).

    Returns list of OrderSuggestion sorted by confidence descending.
    """
    from config.events import CANONICAL_PAIRS

    suggestions: list[OrderSuggestion] = []
    # Only process canonical pairs that have a directional bias
    for pair in CANONICAL_PAIRS:
        pb = pair_biases.get(pair)
        if pb is None:
            continue

        suggestion = build_order_suggestion(
            pair=pair,
            bias=pb.direction,
            confidence_pct=pb.confidence_pct,
            event_code=event_code,
            release_time_utc=release_time_utc,
        )
        suggestions.append(suggestion)

    # Sort: directional biases first, then by confidence descending
    suggestions.sort(
        key=lambda s: (0 if s.bias in ("BUY", "SELL") else 1, -s.confidence_pct)
    )
    return suggestions


# ══════════════════════════════════════════════════════════════════════════════
# PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def _persist_suggestion(
    event_code:       str,
    release_time_utc: Optional[str],
    pair:             str,
    bias:             str,
    current_price:    float,
    atr_14:           float,
    entry:            float,
    sl:               float,
    tp:               float,
    confidence_pct:   float,
) -> None:
    """Insert a PairSuggestion row into the database."""
    from database import PairSuggestion, SessionLocal
    db = SessionLocal()
    try:
        row = PairSuggestion(
            calculated_at    = datetime.utcnow(),
            event_code       = event_code,
            release_time_utc = release_time_utc,
            pair             = pair,
            bias             = bias,
            current_price    = current_price,
            atr_14           = atr_14,
            suggested_entry  = entry,
            suggested_sl     = sl,
            suggested_tp     = tp,
            confidence_pct   = confidence_pct,
            is_reference_only= True,
        )
        db.add(row)
        db.commit()
    except Exception as e:
        log.error("Failed to persist order suggestion for %s: %s", pair, e)
        db.rollback()
    finally:
        db.close()


def get_latest_suggestions(event_code: str) -> list[dict]:
    """
    Return the most recent OrderSuggestion rows for an event from the DB.
    Used by api.py GET /order-suggestion/{event_code}.
    """
    from database import PairSuggestion, SessionLocal
    db = SessionLocal()
    try:
        rows = (
            db.query(PairSuggestion)
            .filter_by(event_code=event_code)
            .order_by(PairSuggestion.calculated_at.desc())
            .limit(50)
            .all()
        )
        seen_pairs: set[str] = set()
        results: list[dict] = []
        for row in rows:
            if row.pair in seen_pairs:
                continue   # keep only most recent per pair
            seen_pairs.add(row.pair)
            results.append({
                "pair":             row.pair,
                "bias":             row.bias,
                "current_price":    row.current_price,
                "atr_14":           row.atr_14,
                "suggested_entry":  row.suggested_entry,
                "suggested_sl":     row.suggested_sl,
                "suggested_tp":     row.suggested_tp,
                "confidence_pct":   row.confidence_pct,
                "event_code":       row.event_code,
                "release_time_utc": row.release_time_utc,
                "calculated_at":    row.calculated_at.isoformat() if row.calculated_at else None,
                "is_reference_only": True,
            })
        return results
    finally:
        db.close()
