"""
indicators.py — Pulls leading indicator data from FRED and computes
z-scores and directional signals for each event.

For each FRED series:
  1. Pull last 12 months of data
  2. Compute trailing 6-month mean and std dev
  3. Compute z-score: (latest - mean) / std
  4. Multiply by sign convention → directional signal
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np
import requests
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from config.events import EVENTS
from database import IndicatorSnapshot, SessionLocal

load_dotenv()
log = logging.getLogger("indicators")

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"
FRED_KEY  = os.getenv("FRED_API_KEY", "")

# ── Cleveland Fed CPI Nowcast (free, no API key) ──────────────────────────────
CLEVELAND_FED_NOWCAST_URL = (
    "https://www.clevelandfed.org/en/indicators-and-data/inflation-nowcasting/-/media/"
    "project/clevelandfedorg/indicators-and-data/inflation-nowcasting/nowcasting-json/"
    "nowcasting-inflation-data.json"
)


def _fetch_fred_series(series_id: str, months: int = 12) -> Optional[pd.Series]:
    """Pull a FRED series and return as a pandas Series indexed by date."""
    if not FRED_KEY:
        log.warning("FRED_API_KEY not set — cannot pull %s", series_id)
        return None

    start = (datetime.utcnow() - timedelta(days=months * 31)).strftime("%Y-%m-%d")
    params = {
        "series_id":        series_id,
        "api_key":          FRED_KEY,
        "file_type":        "json",
        "observation_start": start,
        "sort_order":       "asc",
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
            return None
        return pd.Series(data).sort_index()
    except Exception as e:
        log.error("FRED fetch failed for %s: %s", series_id, e)
        return None


def _fetch_cleveland_nowcast() -> Optional[float]:
    """
    Pull the Cleveland Fed's real-time CPI nowcast.
    Returns the latest 1-month CPI nowcast as an annualized % change.
    """
    try:
        r = requests.get(CLEVELAND_FED_NOWCAST_URL, timeout=15)
        r.raise_for_status()
        data = r.json()
        # The JSON structure has a "data" list — grab the most recent CPI entry
        entries = [d for d in data.get("data", []) if d.get("indicator") == "CPI"]
        if entries:
            latest = sorted(entries, key=lambda x: x.get("date", ""))[-1]
            return float(latest.get("nowcast", 0.0))
    except Exception as e:
        log.error("Cleveland Fed nowcast fetch failed: %s", e)
    return None


def compute_indicator_score(series_id: str, sign: int, description: str) -> dict:
    """
    Pull a FRED series, compute z-score and directional signal.

    Returns a dict with all computed values for storage and display.
    signal: +1 (leans BEAT), -1 (leans MISS), 0 (neutral / insufficient data)
    """
    series = _fetch_fred_series(series_id, months=12)

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

    # Latest and previous
    result["latest_value"] = round(float(series.iloc[-1]), 4)
    if len(series) >= 2:
        result["prev_value"] = round(float(series.iloc[-2]), 4)

    # Trailing 6-month window (up to but not including the latest point)
    trailing = series.iloc[:-1].tail(6)
    if len(trailing) >= 3:
        avg = float(trailing.mean())
        std = float(trailing.std())
        result["trailing_6m_avg"] = round(avg, 4)
        result["trailing_6m_std"] = round(std, 4)

        if std > 0:
            z = (result["latest_value"] - avg) / std
            result["z_score"] = round(z, 3)
            # Apply sign convention and threshold
            if abs(z) < 0.3:
                result["signal"] = 0   # too close to neutral
            else:
                result["signal"] = sign if z > 0 else -sign

    return result


def pull_all_indicators_for_event(event_code: str) -> list[dict]:
    """
    Pull and score all leading indicators for a given event.
    Saves snapshots to DB and returns list of scored indicator dicts.
    """
    event = EVENTS.get(event_code)
    if not event:
        raise ValueError(f"Unknown event code: {event_code}")

    db: Session = SessionLocal()
    scored = []

    for series_id, weight, sign, description in event["indicators"]:
        log.info("Pulling indicator %s for %s", series_id, event_code)
        score = compute_indicator_score(series_id, sign, description)
        score["weight"] = weight

        # Persist to DB
        snapshot = IndicatorSnapshot(
            fred_series=score["fred_series"],
            description=score["description"],
            latest_value=score["latest_value"],
            prev_value=score["prev_value"],
            trailing_6m_avg=score["trailing_6m_avg"],
            trailing_6m_std=score["trailing_6m_std"],
            z_score=score["z_score"],
            signal=score["signal"],
        )
        db.add(snapshot)
        scored.append(score)

    db.commit()
    db.close()
    return scored


def build_composite_score(event_code: str) -> dict:
    """
    Pull all leading indicators and compute the composite lean + confidence.

    Returns:
      composite_score:  weighted sum of signals (positive = BEAT lean)
      lean_direction:   "BEAT", "MISS", or "INLINE"
      confidence_pct:   0–100, % of weighted signals aligned
      indicators:       per-indicator breakdown for the dashboard
    """
    indicators = pull_all_indicators_for_event(event_code)

    weighted_score = 0.0
    total_aligned_weight = 0.0
    total_weight = 0.0

    for ind in indicators:
        w = ind["weight"]
        s = ind["signal"]  # +1, 0, -1
        total_weight += w
        weighted_score += w * s

        if s != 0:
            total_aligned_weight += w   # weight of non-neutral indicators

    # Composite score: ranges from -1.0 (all MISS) to +1.0 (all BEAT)
    composite = round(weighted_score, 4)

    # Direction threshold: |composite| > 0.15 = directional, else INLINE
    if composite > 0.15:
        direction = "BEAT"
    elif composite < -0.15:
        direction = "MISS"
    else:
        direction = "INLINE"

    # Confidence = % of non-neutral weight that agrees with composite direction
    if total_aligned_weight > 0 and direction != "INLINE":
        agreeing_weight = sum(
            ind["weight"]
            for ind in indicators
            if (ind["signal"] > 0 and direction == "BEAT") or
               (ind["signal"] < 0 and direction == "MISS")
        )
        alignment_pct = (agreeing_weight / total_aligned_weight) * 100

        # Scale: 100% agreement → 85% max confidence (no model is ever 100% certain)
        # 60% agreement → ~50% confidence (coin-flip territory)
        confidence = 50.0 + (alignment_pct - 60.0) * (35.0 / 40.0)
        confidence = max(30.0, min(85.0, confidence))
    else:
        confidence = 30.0  # INLINE / not enough data

    return {
        "event_code":          event_code,
        "composite_score":     composite,
        "lean_direction":      direction,
        "confidence_pct":      round(confidence, 1),
        "indicator_breakdown": indicators,
    }
