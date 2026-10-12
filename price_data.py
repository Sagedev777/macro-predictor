"""
price_data.py — Live OHLC price fetching and ATR-based order-level suggestions.

Data source: Twelve Data (https://twelvedata.com)
  - Free tier: 800 API calls/day, 8 calls/minute
  - Requires TWELVE_DATA_API_KEY in .env
  - New account required: register at https://twelvedata.com/register

ATR calculation: pandas Wilder smoothing on daily candles.

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

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
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
_PRICE_REACTION_RETRY_LIMIT = 5
_PRICE_REACTION_RETRY_INTERVAL = timedelta(minutes=10)

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
        "timezone":   "UTC",
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
# ATR CALCULATION (Wilder smoothing)
# ══════════════════════════════════════════════════════════════════════════════

def _calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series,
                   period: int = 14) -> pd.Series:
    """Calculate ATR with Wilder smoothing and an initial true-range SMA."""
    previous_close = close.shift(1)
    true_range = pd.concat(
        (
            high - low,
            (high - previous_close).abs(),
            (previous_close - low).abs(),
        ),
        axis=1,
    ).max(axis=1)
    seeded_range = true_range.copy()
    seeded_range.iloc[:period - 1] = float("nan")
    seeded_range.iloc[period - 1] = true_range.iloc[:period].mean()
    return seeded_range.ewm(alpha=1.0 / period, adjust=False, min_periods=1).mean()


def compute_atr(pair: str, period: int = 14) -> Optional[float]:
    """
    Compute the Average True Range for a pair using pandas Wilder smoothing.

    Fetches 30 daily candles (gives ATR(14) enough warm-up bars).
    Returns the most recent ATR value, or None if data is insufficient.
    """
    df = fetch_ohlc(pair, interval="1day", bars=period + 16)
    if df is None or len(df) < period + 1:
        log.warning("Insufficient candles for ATR(%d) on %s", period, pair)
        return None

    try:
        atr_series = _calculate_atr(
            df["high"], df["low"], df["close"], period
        )
        if atr_series.empty or atr_series.dropna().empty:
            return None
        return float(atr_series.dropna().iloc[-1])
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


# ══════════════════════════════════════════════════════════════════════════════
# REAL USD PRICE REACTION TRACKING & GRADING (Twelve Data 1-min candles)
# ══════════════════════════════════════════════════════════════════════════════

USD_REACTION_SYMBOLS = ["USDJPY", "EURUSD", "XAUUSD"]


def parse_release_utc(release_time_str: str) -> Optional[datetime]:
    """Parse an ISO release time string and convert to timezone-naive UTC datetime."""
    if not release_time_str:
        return None
    try:
        dt = datetime.fromisoformat(release_time_str.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception as e:
        log.error("Failed to parse release time '%s': %s", release_time_str, e)
        return None


def derive_usd_moves(symbol_data: dict) -> dict:
    """
    Derive usd_move per horizon (+5m, +15m, +60m):
      - USDJPY up counts as USD up
      - EURUSD down counts as USD up
      - XAUUSD down counts as USD up
    Call it UP or DOWN only if at least 2 of 3 agree and the move exceeds
    0.25 × ATR(14) of 15-minute candles at release time. Otherwise FLAT or MIXED.
    """
    results = {}
    for horizon, price_col in [("5m", "price_5m"), ("15m", "price_15m"), ("60m", "price_60m")]:
        votes = {}
        for sym in USD_REACTION_SYMBOLS:
            s_info = symbol_data.get(sym, {})
            if s_info.get("status") != "ok":
                continue
            p_rel = s_info.get("price_at_release")
            p_h   = s_info.get(price_col)
            atr   = s_info.get("atr_15m")

            if p_rel is None or p_h is None or atr is None or atr <= 0:
                continue

            diff = p_h - p_rel
            threshold = 0.25 * atr

            if abs(diff) > threshold:
                if sym == "USDJPY":
                    votes[sym] = "UP" if diff > 0 else "DOWN"
                else:  # EURUSD, XAUUSD
                    votes[sym] = "UP" if diff < 0 else "DOWN"
            else:
                votes[sym] = "FLAT"

        up_count   = sum(1 for v in votes.values() if v == "UP")
        down_count = sum(1 for v in votes.values() if v == "DOWN")

        if up_count >= 2:
            results[horizon] = "UP"
        elif down_count >= 2:
            results[horizon] = "DOWN"
        elif up_count >= 1 and down_count >= 1:
            results[horizon] = "MIXED"
        else:
            results[horizon] = "FLAT"

    return results


def grade_prediction_on_price(
    lean_direction: str,
    usd_move: str,
) -> tuple[Optional[bool], str]:
    """
    Grade a prediction based on real USD price reaction.
    Returns (was_correct: bool | None, result_status: str).
    Only BEAT/MISS leans and UP/DOWN moves are graded; other values return
    (None, "NO_CLEAR_MOVE").
    result_status: "CORRECT" | "INCORRECT" | "NO_CLEAR_MOVE"
    """
    lean = (lean_direction or "").upper()
    if lean == "BEAT":
        predicted = "UP"
    elif lean == "MISS":
        predicted = "DOWN"
    else:
        return None, "NO_CLEAR_MOVE"

    if usd_move in ("FLAT", "MIXED", "UNAVAILABLE"):
        return None, "NO_CLEAR_MOVE"

    if usd_move == "UP":
        return (True, "CORRECT") if predicted == "UP" else (False, "INCORRECT")
    elif usd_move == "DOWN":
        return (True, "CORRECT") if predicted == "DOWN" else (False, "INCORRECT")

    return None, "NO_CLEAR_MOVE"


def fetch_and_record_price_reactions(
    event_code: str,
    release_time_utc: str,
    force_refresh: bool = False,
) -> dict:
    """
    Fetch 1-minute OHLC from Twelve Data for USDJPY, EURUSD, XAUUSD.
    One 1-minute candle request per symbol and release moment.
    Calculates:
      - price_at_release (last 1-min close before release, i.e. release - 1 min)
      - price at +5m, +15m, +60m
      - % change at each horizon
      - ATR(14) of 15-minute candles before release
      - derives usd_move at +5m, +15m, +60m
    Persists rows into price_reactions table.
    """
    from database import PriceReaction, SessionLocal

    rel_dt = parse_release_utc(release_time_utc)
    if not rel_dt:
        return {"status": "unavailable", "error": "Invalid release time"}

    # Target timestamps
    t_release = rel_dt - timedelta(minutes=1)
    t_5m      = rel_dt + timedelta(minutes=5)
    t_15m     = rel_dt + timedelta(minutes=15)
    t_60m     = rel_dt + timedelta(minutes=60)

    db = SessionLocal()
    try:
        existing_rows = (
            db.query(PriceReaction)
            .filter_by(release_time_utc=release_time_utc)
            .all()
        )
        existing_by_symbol = {row.symbol: row for row in existing_rows}
        symbol_data = {}
        normalized_existing_status = False
        for row in existing_rows:
            cached_status = row.status
            cached_values = (
                row.price_at_release,
                row.price_5m,
                row.price_15m,
                row.price_60m,
                row.atr_15m,
            )
            if cached_status == "ok" and (
                any(value is None for value in cached_values)
                or row.atr_15m <= 0
            ):
                cached_status = "unavailable"
                row.status = cached_status
                normalized_existing_status = True
            symbol_data[row.symbol] = {
                "price_at_release": row.price_at_release,
                "price_5m":         row.price_5m,
                "price_15m":        row.price_15m,
                "price_60m":        row.price_60m,
                "pct_change_5m":    row.pct_change_5m,
                "pct_change_15m":   row.pct_change_15m,
                "pct_change_60m":   row.pct_change_60m,
                "atr_15m":          row.atr_15m,
                "status":           cached_status,
            }
        if normalized_existing_status:
            db.commit()

        start_str = (rel_dt - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
        end_str   = (rel_dt + timedelta(minutes=65)).strftime("%Y-%m-%d %H:%M:%S")

        for sym in USD_REACTION_SYMBOLS:
            row = existing_by_symbol.get(sym)
            if row is not None:
                if row.status == "ok" and not force_refresh:
                    continue
                if (row.attempt_count or 0) >= _PRICE_REACTION_RETRY_LIMIT:
                    continue
                if (
                    row.status != "ok"
                    and row.last_attempt_at is not None
                    and datetime.now(timezone.utc).replace(tzinfo=None)
                    - row.last_attempt_at < _PRICE_REACTION_RETRY_INTERVAL
                ):
                    continue
            else:
                row = PriceReaction(
                    fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
                    event_code=event_code,
                    release_time_utc=release_time_utc,
                    symbol=sym,
                    status="unavailable",
                    attempt_count=0,
                )
                db.add(row)
                db.flush()

            attempt_at = datetime.now(timezone.utc).replace(tzinfo=None)
            row.attempt_count = (row.attempt_count or 0) + 1
            row.last_attempt_at = attempt_at
            row.status = "unavailable"
            db.commit()

            td_sym = _twelve_data_symbol(sym)
            _rate_limit_wait()

            url = f"{TWELVE_DATA_BASE}/time_series"
            params = {
                "symbol":     td_sym,
                "interval":   "1min",
                "start_date": start_str,
                "end_date":   end_str,
                "timezone":   "UTC",
                "apikey":     TWELVE_DATA_KEY,
                "format":     "JSON",
            }

            p_rel = p_5 = p_15 = p_60 = None
            pct_5 = pct_15 = pct_60 = None
            status_val = "unavailable"
            atr14 = None
            df = None

            try:
                r = requests.get(url, params=params, timeout=20)
                r.raise_for_status()
                data = r.json()

                if data.get("status") == "ok" and data.get("values"):
                    df = pd.DataFrame(data["values"]).astype({
                        "open": float, "high": float, "low": float, "close": float,
                    })
                    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(None)
                    df = df.set_index("datetime").sort_index()

                    target_times = {
                        "release": t_release,
                        "5m": t_5m,
                        "15m": t_15m,
                        "60m": t_60m,
                    }
                    nearest_prices = {}
                    missing_targets = []
                    for target_name, target_time in target_times.items():
                        index = df.index.get_indexer(
                            [pd.Timestamp(target_time)],
                            method="nearest",
                            tolerance=pd.Timedelta(minutes=2),
                        )[0]
                        if index < 0:
                            missing_targets.append(target_name)
                        else:
                            nearest_prices[target_name] = float(df.iloc[index]["close"])

                    if not missing_targets:
                        p_rel = nearest_prices["release"]
                        p_5 = nearest_prices["5m"]
                        p_15 = nearest_prices["15m"]
                        p_60 = nearest_prices["60m"]
                        pct_5  = round(((p_5 - p_rel) / p_rel) * 100.0, 4)
                        pct_15 = round(((p_15 - p_rel) / p_rel) * 100.0, 4)
                        pct_60 = round(((p_60 - p_rel) / p_rel) * 100.0, 4)

                        df_pre = df[df.index < rel_dt]
                        df15 = df_pre.resample("15min", closed="left", label="left").agg({
                            "open": "first", "high": "max", "low": "min", "close": "last"
                        }).dropna()
                        if len(df15) >= 14:
                            atr_series = _calculate_atr(
                                df15["high"], df15["low"], df15["close"], 14
                            )
                            if not atr_series.dropna().empty:
                                atr14 = float(atr_series.dropna().iloc[-1])
                        if atr14 is not None and pd.notna(atr14) and atr14 > 0:
                            status_val = "ok"
                        else:
                            p_rel = p_5 = p_15 = p_60 = None
                            pct_5 = pct_15 = pct_60 = None
                            log.warning(
                                "Twelve Data ATR unavailable for %s at %s",
                                sym, release_time_utc,
                            )
                    else:
                        log.warning(
                            "Twelve Data missing candles within 2 minutes for %s at %s: %s",
                            sym, release_time_utc, ", ".join(missing_targets),
                        )
                else:
                    log.warning(
                        "Twelve Data non-ok for %s at %s: %s",
                        sym, release_time_utc, data.get("message")
                    )
            except Exception as e:
                log.error("Twelve Data fetch failed for %s at %s: %s", sym, release_time_utc, e)

            symbol_data[sym] = {
                "price_at_release": p_rel,
                "price_5m":         p_5,
                "price_15m":        p_15,
                "price_60m":        p_60,
                "pct_change_5m":    pct_5,
                "pct_change_15m":   pct_15,
                "pct_change_60m":   pct_60,
                "atr_15m":          atr14,
                "status":           status_val,
            }

            row.price_at_release = p_rel
            row.price_5m = p_5
            row.price_15m = p_15
            row.price_60m = p_60
            row.pct_change_5m = pct_5
            row.pct_change_15m = pct_15
            row.pct_change_60m = pct_60
            row.atr_15m = atr14
            row.status = status_val
            row.fetched_at = datetime.now(timezone.utc).replace(tzinfo=None)
            db.commit()
            if sym == "XAUUSD" and df is not None and not df.empty:
                try:
                    from gold_model import record_gold_outcome

                    record_gold_outcome(db, release_time_utc, df)
                except Exception:
                    log.exception(
                        "Could not persist gold outcome for %s at %s",
                        event_code,
                        release_time_utc,
                    )

        successful_symbols = sum(
            symbol.get("status") == "ok" for symbol in symbol_data.values()
        )
        usd_moves = derive_usd_moves(symbol_data) if successful_symbols >= 2 else {}
        return {
            "status": "ok" if successful_symbols == len(USD_REACTION_SYMBOLS) else "unavailable",
            "symbols": symbol_data,
            "usd_moves": usd_moves,
        }
    finally:
        db.close()


def fetch_and_record_gold_outcome(
    release_time_utc: str,
    force_refresh: bool = False,
    db=None,
) -> bool:
    """
    Fetch 1-minute XAU/USD OHLC candles from Twelve Data for a release moment
    and record the 5-minute reaction, excursions, and 1m/5m/15m/30m returns.

    Directly grades the GoldForecast row independently of USD multi-pair logic.
    Returns True if the outcome is successfully recorded.
    """
    from database import GoldForecast, SessionLocal
    from gold_model import record_gold_outcome

    rel_dt = parse_release_utc(release_time_utc)
    if not rel_dt:
        return False

    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        row = db.query(GoldForecast).filter_by(release_time_utc=release_time_utc).first()
        if row is None:
            return False
        if row.outcome_recorded_at is not None and not force_refresh:
            return True

        start_str = (rel_dt - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        end_str   = (rel_dt + timedelta(minutes=35)).strftime("%Y-%m-%d %H:%M:%S")

        td_sym = _twelve_data_symbol("XAUUSD")
        _rate_limit_wait()

        url = f"{TWELVE_DATA_BASE}/time_series"
        params = {
            "symbol":     td_sym,
            "interval":   "1min",
            "start_date": start_str,
            "end_date":   end_str,
            "timezone":   "UTC",
            "apikey":     TWELVE_DATA_KEY,
            "format":     "JSON",
        }

        try:
            r = requests.get(url, params=params, timeout=20)
            r.raise_for_status()
            data = r.json()

            if data.get("status") == "ok" and data.get("values"):
                df = pd.DataFrame(data["values"]).astype({
                    "open": float, "high": float, "low": float, "close": float,
                })
                df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(None)
                df = df.set_index("datetime").sort_index()

                return record_gold_outcome(db, release_time_utc, df)
            else:
                log.warning(
                    "Twelve Data returned non-ok for XAUUSD at %s: %s",
                    release_time_utc, data.get("message")
                )
                return False
        except Exception as e:
            log.error("Twelve Data fetch failed for XAUUSD at %s: %s", release_time_utc, e)
            return False
    finally:
        if close_db:
            db.close()


def process_and_grade_event_price_reactions(
    event_code: str,
    release_time_utc: str,
    pred_id: Optional[int] = None,
) -> dict:
    """
    Fetch/load real USD price reactions for an event, derive moves at +5m, +15m, +60m,
    and grade the corresponding Prediction(s).
    A prediction is correct if its direction matches usd_move at +15m.
    Stores +5m and +60m results separately.
    Fewer than two successful symbols leaves predictions ungraded and retryable.
    FLAT and MIXED from valid fetches remain excluded from accuracy.
    """
    from database import Prediction, SessionLocal

    rx_result = fetch_and_record_price_reactions(event_code, release_time_utc)
    symbol_data = rx_result.get("symbols", {})
    if sum(data.get("status") == "ok" for data in symbol_data.values()) < 2:
        return {
            "event_code": event_code,
            "release_time_utc": release_time_utc,
            "status": "unavailable",
            "usd_moves": {},
            "graded_predictions": [],
        }

    usd_moves = rx_result["usd_moves"]
    move_5m  = usd_moves["5m"]
    move_15m = usd_moves["15m"]
    move_60m = usd_moves["60m"]

    db = SessionLocal()
    graded_preds = []
    try:
        q = db.query(Prediction).filter(
            Prediction.event_code == event_code,
            Prediction.release_time_utc == release_time_utc,
        )
        if pred_id:
            q = q.filter(Prediction.id == pred_id)
        preds = q.all()

        for pred in preds:
            # Preserve old was_correct if not already preserved
            if pred.old_was_correct is None and pred.was_correct is not None:
                pred.old_was_correct = pred.was_correct

            _, res_5m         = grade_prediction_on_price(pred.lean_direction, move_5m)
            was_corr, res_15m = grade_prediction_on_price(pred.lean_direction, move_15m)
            _, res_60m        = grade_prediction_on_price(pred.lean_direction, move_60m)

            pred.usd_move_5m     = move_5m
            pred.usd_move_15m    = move_15m
            pred.usd_move_60m    = move_60m
            pred.result_5m       = res_5m
            pred.result_15m      = res_15m
            pred.result_60m      = res_60m
            pred.was_correct     = was_corr  # True if CORRECT, False if INCORRECT, None if NO_CLEAR_MOVE
            pred.price_graded_at = datetime.now(timezone.utc).replace(tzinfo=None)

            graded_preds.append({
                "id": pred.id,
                "event_code": pred.event_code,
                "lean_direction": pred.lean_direction,
                "old_was_correct": pred.old_was_correct,
                "new_was_correct": pred.was_correct,
                "usd_move_15m": move_15m,
                "result_15m": res_15m,
                "result_5m": res_5m,
                "result_60m": res_60m,
                "is_late": pred.is_late,
            })
        db.commit()
    finally:
        db.close()

    return {
        "event_code": event_code,
        "release_time_utc": release_time_utc,
        "status": rx_result["status"],
        "usd_moves": usd_moves,
        "graded_predictions": graded_preds,
    }
