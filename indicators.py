"""
indicators.py — Leading indicator data fetching and z-score computation.

What changed from the original:
  - Core z-score math is PRESERVED verbatim (6-month trailing mean/std,
    ±0.3 neutrality threshold, weighted signal aggregation).  This is the
    part with the good accuracy track record.
  - Output is now a per-currency indicator_score in [-1, +1] instead of a
    standalone "BEAT/MISS/INLINE" composite, so it can slot directly into
    learning.py's build_features() as the indicator_score feature.
  - pull_all_indicators_for_event() now routes series IDs through
    data_sources.fetch_series() so ECB:/ONS:/BOE:/ESTAT:/OECD: prefixed
    series from the new config/events.py definitions are handled correctly.
  - FRED-only series (no prefix) still use the original direct FRED fetcher
    path, so backward compatibility is maintained.
  - build_composite_score() is kept with its original signature for any
    existing callers; it now also returns indicator_score [-1,+1].
  - New function: get_indicator_score_for_currency(currency) aggregates
    indicator scores across all of a currency's upcoming events and returns
    a single [-1,+1] score for River's feature vector.

Cleveland Fed CPI Nowcast is preserved unchanged.
"""

import logging
import os
import time
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from config.events import EVENTS, get_event_config
from database import IndicatorSnapshot, SessionLocal

load_dotenv()
log = logging.getLogger("indicators")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_KEY  = os.getenv("FRED_API_KEY", "")

_fred_cache: dict[str, tuple[float, Optional[pd.Series]]] = {}
_FRED_CACHE_TTL = 3600  # 1 hour

# ── Cleveland Fed CPI Nowcast (unchanged) ─────────────────────────────────────
CLEVELAND_FED_NOWCAST_URL = (
    "https://www.clevelandfed.org/en/indicators-and-data/inflation-nowcasting/-/media/"
    "project/clevelandfedorg/indicators-and-data/inflation-nowcasting/nowcasting-json/"
    "nowcasting-inflation-data.json"
)


def _fetch_fred_series(series_id: str, months: int = 12) -> Optional[pd.Series]:
    """
    Pull a FRED series and return as a pandas Series indexed by date.
    Cached for 1 hour in-process.  Unchanged from original.
    """
    if not FRED_KEY:
        log.warning("FRED_API_KEY not set — cannot pull %s", series_id)
        return None

    cache_key = f"{series_id}_{months}"
    now_ts    = time.time()
    if cache_key in _fred_cache:
        cached_ts, cached_series = _fred_cache[cache_key]
        if (now_ts - cached_ts) < _FRED_CACHE_TTL:
            return cached_series

    start = (datetime.utcnow() - timedelta(days=months * 31)).strftime("%Y-%m-%d")
    params = {
        "series_id":         series_id,
        "api_key":           FRED_KEY,
        "file_type":         "json",
        "observation_start": start,
        "sort_order":        "asc",
    }
    try:
        r = requests.get(FRED_BASE, params=params, timeout=15)
        r.raise_for_status()
        obs = r.json().get("observations", [])
        data = {
            o["date"]: float(o["value"])
            for o in obs
            if o["value"] not in (".", "")
        }
        if not data:
            _fred_cache[cache_key] = (now_ts, None)
            return None
        series = pd.Series(data).sort_index()
        _fred_cache[cache_key] = (now_ts, series)
        return series
    except Exception as e:
        log.error("FRED fetch failed for %s: %s", series_id, e)
        _fred_cache[cache_key] = (now_ts, None)
        return None


def _fetch_series_routed(series_id: str, months: int = 12) -> Optional[pd.Series]:
    """
    Route a series fetch through data_sources.fetch_series() for prefixed IDs
    (ECB:, ONS:, BOE:, ESTAT:, OECD:), or the direct FRED fetcher for bare IDs.
    This preserves backward compatibility while supporting new data sources.
    """
    sid = series_id.strip()
    if any(sid.startswith(p) for p in ("ECB:", "ONS:", "BOE:", "ESTAT:", "OECD:")):
        from data_sources import fetch_series
        return fetch_series(sid, months=months)
    return _fetch_fred_series(sid, months=months)


def _fetch_cleveland_nowcast() -> Optional[float]:
    """Pull the Cleveland Fed's real-time CPI nowcast. Unchanged from original."""
    try:
        r = requests.get(CLEVELAND_FED_NOWCAST_URL, timeout=15)
        r.raise_for_status()
        data = r.json()
        entries = [d for d in data.get("data", []) if d.get("indicator") == "CPI"]
        if entries:
            latest = sorted(entries, key=lambda x: x.get("date", ""))[-1]
            return float(latest.get("nowcast", 0.0))
    except Exception as e:
        log.error("Cleveland Fed nowcast fetch failed: %s", e)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# CORE Z-SCORE MATH — preserved verbatim from original
# ══════════════════════════════════════════════════════════════════════════════

def compute_indicator_score(series_id: str, sign: int, description: str) -> dict:
    """
    Pull a series, compute z-score and directional signal.

    Returns a dict with all computed values for storage and display.
    signal: +1 (leans BEAT/BULLISH), -1 (leans MISS/BEARISH), 0 (neutral)

    *** MATH UNCHANGED FROM ORIGINAL — do not modify ***
    6-month trailing window, ±0.3 neutrality threshold.
    """
    series = _fetch_series_routed(series_id, months=12)

    result = {
        "fred_series":     series_id,
        "description":     description,
        "latest_value":    None,
        "prev_value":      None,
        "trailing_6m_avg": None,
        "trailing_6m_std": None,
        "z_score":         None,
        "signal":          0,
    }

    if series is None or len(series) < 3:
        log.warning("Not enough data for %s — marking neutral", series_id)
        return result

    result["latest_value"] = round(float(series.iloc[-1]), 4)
    if len(series) >= 2:
        result["prev_value"] = round(float(series.iloc[-2]), 4)

    trailing = series.iloc[:-1].tail(6)
    if len(trailing) >= 3:
        avg = float(trailing.mean())
        std = float(trailing.std())
        result["trailing_6m_avg"] = round(avg, 4)
        result["trailing_6m_std"] = round(std, 4)

        if std > 0:
            z = (result["latest_value"] - avg) / std
            result["z_score"] = round(z, 3)
            if abs(z) < 0.3:
                result["signal"] = 0
            else:
                result["signal"] = sign if z > 0 else -sign

    return result


def pull_all_indicators_for_event(event_code: str) -> list[dict]:
    """
    Pull and score all leading indicators for a given event.
    Saves snapshots to DB and returns list of scored indicator dicts.
    Unchanged from original except routing through _fetch_series_routed().
    """
    event  = get_event_config(event_code)
    db: Session = SessionLocal()
    scored = []

    for series_id, weight, sign, description in event["indicators"]:
        log.info("Pulling indicator %s for %s", series_id, event_code)
        score         = compute_indicator_score(series_id, sign, description)
        score["weight"] = weight

        snapshot = IndicatorSnapshot(
            fred_series    = score["fred_series"],
            description    = score["description"],
            latest_value   = score["latest_value"],
            prev_value     = score["prev_value"],
            trailing_6m_avg= score["trailing_6m_avg"],
            trailing_6m_std= score["trailing_6m_std"],
            z_score        = score["z_score"],
            signal         = score["signal"],
        )
        db.add(snapshot)
        scored.append(score)

    db.commit()
    db.close()
    return scored


# ══════════════════════════════════════════════════════════════════════════════
# COMPOSITE SCORE — original signature preserved, now also returns
# indicator_score [-1,+1] for River's feature vector
# ══════════════════════════════════════════════════════════════════════════════

def build_composite_score(event_code: str) -> dict:
    """
    Pull all leading indicators and compute the composite lean + confidence.

    Returns (extended from original):
      composite_score:   weighted sum of signals (positive = BEAT lean)
      lean_direction:    "BEAT", "MISS", or "INLINE"
      confidence_pct:    0–100, % of weighted signals aligned
      indicator_score:   [-1, +1] normalised for River's feature vector
      indicators:        per-indicator breakdown for the dashboard

    *** COMPOSITE MATH UNCHANGED FROM ORIGINAL ***
    Direction threshold: |composite| > 0.15
    Confidence scaling: 50%→30, 85%→85 (epistemic humility cap)
    """
    indicators      = pull_all_indicators_for_event(event_code)
    weighted_score  = 0.0
    total_aligned_w = 0.0
    total_weight    = 0.0

    for ind in indicators:
        w = ind["weight"]
        s = ind["signal"]
        total_weight    += w
        weighted_score  += w * s
        if s != 0:
            total_aligned_w += w

    composite = round(weighted_score, 4)

    # Direction threshold (unchanged)
    if composite > 0.15:
        direction = "BEAT"
    elif composite < -0.15:
        direction = "MISS"
    else:
        direction = "INLINE"

    # Confidence scaling (unchanged)
    if total_aligned_w > 0 and direction != "INLINE":
        agreeing_weight = sum(
            ind["weight"]
            for ind in indicators
            if (ind["signal"] > 0 and direction == "BEAT") or
               (ind["signal"] < 0 and direction == "MISS")
        )
        alignment_pct = (agreeing_weight / total_aligned_w) * 100
        confidence    = 50.0 + (alignment_pct - 60.0) * (35.0 / 40.0)
        confidence    = max(30.0, min(85.0, confidence))
    else:
        confidence = 30.0

    # ── NEW: normalise composite to [-1, +1] for River ───────────────────────
    # composite is already in roughly [-1, +1] (weighted sum of ±1 signals).
    # Clamp to that range for a clean feature value.
    indicator_score = float(max(-1.0, min(1.0, composite)))

    return {
        "event_code":          event_code,
        "composite_score":     composite,
        "lean_direction":      direction,
        "confidence_pct":      round(confidence, 1),
        "indicator_score":     round(indicator_score, 4),   # NEW
        "indicator_breakdown": indicators,
    }


# ══════════════════════════════════════════════════════════════════════════════
# CURRENCY-LEVEL AGGREGATION — new function for multi-currency architecture
# ══════════════════════════════════════════════════════════════════════════════

def get_indicator_score_for_currency(currency: str) -> float:
    """
    Aggregate indicator z-scores across all of a currency's configured events
    to produce a single indicator_score in [-1, +1] for River's feature vector.

    Strategy:
      1. Collect all event codes for the currency from config/events.py
      2. For each event, pull its indicators and compute the weighted signal sum
      3. Average across events (equal weight per event — River will learn which
         events matter more over time via its ARF feature importance)
      4. Clamp to [-1, +1]

    This is called once per prediction cycle per currency, before River inference.
    """
    from config.events import get_events_for_currency

    events = get_events_for_currency(currency)
    if not events:
        log.warning("No events configured for currency %s", currency)
        return 0.0

    scores: list[float] = []
    for event_code, event_cfg in events.items():
        try:
            indicators = pull_all_indicators_for_event(event_code)
            if not indicators:
                continue
            weighted_sum = sum(ind["weight"] * ind["signal"] for ind in indicators)
            scores.append(weighted_sum)
        except Exception as e:
            log.warning("Indicator pull failed for %s/%s: %s", currency, event_code, e)

    if not scores:
        return 0.0

    avg = float(np.mean(scores))
    return round(max(-1.0, min(1.0, avg)), 4)


def get_indicator_scores_all_currencies() -> dict[str, float]:
    """
    Return indicator_score for all 8 currencies.
    Called by the scheduler before building River feature vectors.
    """
    from config.events import CURRENCIES
    return {
        ccy: get_indicator_score_for_currency(ccy)
        for ccy in CURRENCIES
    }


# ══════════════════════════════════════════════════════════════════════════════
# CURRENCY STRENGTH SNAPSHOT PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════

def persist_currency_strength(
    currency:        str,
    strength_score:  float,
    indicator_score: Optional[float] = None,
    rate_diff_score: Optional[float] = None,
    cot_score:       Optional[float] = None,
    sentiment_score: Optional[float] = None,
    confidence_pct:  Optional[float] = None,
) -> None:
    """
    Persist a currency strength snapshot to the currency_strengths table.
    Called by scheduler.py after each full prediction cycle.
    """
    from database import CurrencyStrength

    db = SessionLocal()
    try:
        row = CurrencyStrength(
            recorded_at    = datetime.utcnow(),
            currency       = currency.upper(),
            strength_score = strength_score,
            indicator_score= indicator_score,
            rate_diff_score= rate_diff_score,
            cot_score      = cot_score,
            sentiment_score= sentiment_score,
            confidence_pct = confidence_pct,
        )
        db.add(row)
        db.commit()
    except Exception as e:
        log.error("Failed to persist currency strength for %s: %s", currency, e)
        db.rollback()
    finally:
        db.close()


def get_latest_currency_strengths() -> dict[str, dict]:
    """
    Return the most recent currency strength snapshot for all 8 currencies.
    Used by api.py GET /currency-strengths.
    """
    from config.events import CURRENCIES
    from database import CurrencyStrength

    db = SessionLocal()
    results: dict[str, dict] = {}
    try:
        for ccy in CURRENCIES:
            row = (
                db.query(CurrencyStrength)
                .filter_by(currency=ccy)
                .order_by(CurrencyStrength.recorded_at.desc())
                .first()
            )
            if row:
                results[ccy] = {
                    "currency":       row.currency,
                    "strength_score": row.strength_score,
                    "indicator_score":row.indicator_score,
                    "rate_diff_score":row.rate_diff_score,
                    "cot_score":      row.cot_score,
                    "sentiment_score":row.sentiment_score,
                    "confidence_pct": row.confidence_pct,
                    "recorded_at":    row.recorded_at.isoformat() if row.recorded_at else None,
                }
            else:
                results[ccy] = {
                    "currency":       ccy,
                    "strength_score": 0.0,
                    "indicator_score":None,
                    "rate_diff_score":None,
                    "cot_score":      None,
                    "sentiment_score":None,
                    "confidence_pct": None,
                    "recorded_at":    None,
                }
    finally:
        db.close()
    return results
