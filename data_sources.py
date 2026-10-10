"""
data_sources.py — Unified fetcher for all free macroeconomic data sources.

Sources implemented (all free, no API key unless noted):
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Source          │ Base URL                                              │
  ├─────────────────────────────────────────────────────────────────────────┤
  │ FRED            │ https://api.stlouisfed.org/fred/series/observations   │
  │                 │ Requires FRED_API_KEY in .env                         │
  │ ECB SDW         │ https://sdw-wsrest.ecb.europa.eu/service/             │
  │ Eurostat        │ https://ec.europa.eu/eurostat/api/dissemination/      │
  │ ONS (UK)        │ https://api.ons.gov.uk/                               │
  │ Bank of England │ https://www.bankofengland.co.uk/boeapps/database/     │
  │ OECD            │ https://stats.oecd.org/SDMX-JSON/                     │
  └─────────────────────────────────────────────────────────────────────────┘

Public interface:
  fetch_series(series_id, months)  → pd.Series (date-indexed floats)
      Routes by prefix:  "ECB:", "ESTAT:", "ONS:", "BOE:", "OECD:", bare = FRED

  compute_rate_differentials()     → dict[currency, RateDiff]
      Fetches each currency's benchmark yield + US 10Y, computes spread,
      3-month trailing average, and trend direction.

  get_rate_differential(currency)  → RateDiff | None
      Returns latest snapshot for a single currency from the DB.

All fetched series are cached in-process for TTL seconds (default 3600).
"""

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests
from dotenv import load_dotenv

from config.events import RATE_SERIES
from database import RateDifferential, SessionLocal

load_dotenv()
log = logging.getLogger("data_sources")

FRED_KEY  = os.getenv("FRED_API_KEY", "")
CACHE_TTL = 3600   # 1 hour in-process cache for all sources

# ── In-process series cache ────────────────────────────────────────────────────
# key: (series_id, months)  value: (timestamp, pd.Series | None)
_cache: dict[tuple[str, int], tuple[float, Optional[pd.Series]]] = {}


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL FETCHERS — one per source
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_fred(series_id: str, months: int) -> Optional[pd.Series]:
    """FRED REST API — requires FRED_API_KEY."""
    if not FRED_KEY:
        log.warning("FRED_API_KEY not set — cannot pull %s", series_id)
        return None
    start = (datetime.utcnow() - timedelta(days=months * 31)).strftime("%Y-%m-%d")
    params = {
        "series_id":         series_id,
        "api_key":           FRED_KEY,
        "file_type":         "json",
        "observation_start": start,
        "sort_order":        "asc",
    }
    try:
        r = requests.get(
            "https://api.stlouisfed.org/fred/series/observations",
            params=params, timeout=15,
        )
        r.raise_for_status()
        obs = r.json().get("observations", [])
        data = {
            o["date"]: float(o["value"])
            for o in obs
            if o["value"] not in (".", "")
        }
        return pd.Series(data).sort_index() if data else None
    except Exception as e:
        log.error("FRED fetch failed [%s]: %s", series_id, e)
        return None


def _fetch_ecb_sdw(series_key: str, months: int) -> Optional[pd.Series]:
    """
    ECB Statistical Data Warehouse — free, no key.
    Tries the newer ECB Data Portal API first, falls back to legacy SDW.
    """
    start = (datetime.utcnow() - timedelta(days=months * 31)).strftime("%Y-%m-%d")

    # New ECB Data Portal endpoint (2024+)
    url_new = f"https://data-api.ecb.europa.eu/service/data/{series_key}"
    # Legacy SDW endpoint (kept as fallback)
    url_old = f"https://sdw-wsrest.ecb.europa.eu/service/data/{series_key}"

    for url in [url_new, url_old]:
        params  = {"startPeriod": start, "format": "jsondata"}
        headers = {"Accept": "application/json"}
        try:
            r = requests.get(url, params=params, headers=headers, timeout=20)
            r.raise_for_status()
            payload = r.json()

            dataset   = payload.get("dataSets", [{}])[0]
            structure = payload.get("structure", {})
            dims      = structure.get("dimensions", {}).get("observation", [])
            time_dim  = next((d for d in dims if d.get("id") == "TIME_PERIOD"), None)
            if not time_dim:
                continue

            time_values = [v["id"] for v in time_dim.get("values", [])]
            series_data = dataset.get("series", {})
            if not series_data:
                continue

            first_series = next(iter(series_data.values()))
            obs = first_series.get("observations", {})

            data: dict[str, float] = {}
            for idx_str, values in obs.items():
                idx = int(idx_str)
                if idx < len(time_values) and values[0] is not None:
                    data[time_values[idx]] = float(values[0])

            if data:
                return pd.Series(data).sort_index()

        except Exception as e:
            log.debug("ECB fetch attempt failed [%s] %s: %s", url, series_key, e)
            continue

    log.warning("ECB SDW: all endpoints failed for %s", series_key)
    return None


def _fetch_eurostat(dataset_code: str, months: int) -> Optional[pd.Series]:
    """
    Eurostat dissemination API — free, no key.
    Endpoint: https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}
    Returns SDMX-JSON.  We request EU27 aggregate where available.
    """
    start_year = (datetime.utcnow() - timedelta(days=months * 31)).year
    url = (
        f"https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
        f"{dataset_code}"
    )
    params = {
        "format":  "JSON",
        "lang":    "EN",
        "sinceTimePeriod": str(start_year),
        "geo":     "EA19",   # Euro Area 19 aggregate
    }
    headers = {"Accept": "application/json"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        r.raise_for_status()
        payload = r.json()

        dims      = payload.get("dimension", {})
        time_dim  = dims.get("time", {}).get("category", {})
        time_idx  = time_dim.get("index", {})   # period_str → position
        time_labels = {v: k for k, v in time_idx.items()}

        values = payload.get("value", {})
        data: dict[str, float] = {}
        for idx_str, val in values.items():
            idx = int(idx_str)
            label = time_labels.get(idx)
            if label and val is not None:
                data[label] = float(val)

        return pd.Series(data).sort_index() if data else None

    except Exception as e:
        log.error("Eurostat fetch failed [%s]: %s", dataset_code, e)
        return None


def _fetch_ons(series_id: str, months: int) -> Optional[pd.Series]:
    """
    ONS (Office for National Statistics) API — free, no key.
    Endpoint: https://api.ons.gov.uk/v1/dataset/{dataset}/timeseries/{series}/data
    series_id format: "DATASET/SERIES"  e.g. "MM23/L55O"
    """
    if "/" not in series_id:
        log.warning("ONS series_id must be 'DATASET/SERIES', got: %s", series_id)
        return None

    dataset, series = series_id.split("/", 1)
    url = f"https://api.ons.gov.uk/v1/datasets/{dataset}/timeseries/{series}/data"
    headers = {"Accept": "application/json"}
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        payload = r.json()

        # ONS returns nested "months", "quarters", or "years" sections
        cutoff = datetime.utcnow() - timedelta(days=months * 31)

        data: dict[str, float] = {}

        # Monthly data
        for entry in payload.get("months", []):
            try:
                date_str = entry.get("date", "")   # e.g. "2024 JAN"
                val      = entry.get("value")
                if val and val not in ("", "N/A"):
                    dt = datetime.strptime(date_str, "%Y %b")
                    if dt >= cutoff:
                        data[dt.strftime("%Y-%m")] = float(val)
            except (ValueError, TypeError):
                continue

        # Quarterly data (fallback)
        if not data:
            for entry in payload.get("quarters", []):
                try:
                    date_str = entry.get("date", "")  # e.g. "2024 Q1"
                    val      = entry.get("value")
                    if val and val not in ("", "N/A"):
                        year, q = date_str.split(" Q")
                        month = (int(q) - 1) * 3 + 1
                        dt = datetime(int(year), month, 1)
                        if dt >= cutoff:
                            data[dt.strftime("%Y-%m")] = float(val)
                except (ValueError, TypeError):
                    continue

        return pd.Series(data).sort_index() if data else None

    except Exception as e:
        log.error("ONS fetch failed [%s]: %s", series_id, e)
        return None


def _fetch_boe(series_code: str, months: int) -> Optional[pd.Series]:
    """
    Bank of England Statistical Interactive Database — free, no key.
    CSV export endpoint.  We fetch the last N years to cover `months`.
    series_code: e.g. "IUDMNZC" (Gilt nominal zero coupon 10Y)
    """
    years_back = max(2, (months // 12) + 1)
    start_date = (datetime.utcnow() - timedelta(days=years_back * 365)).strftime("%d/%b/%Y")
    end_date   = datetime.utcnow().strftime("%d/%b/%Y")

    # BoE CSV export URL
    url = (
        "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp"
        f"?Travel=NIxIRxSUx&FromSeries=1&ToSeries=50&DAT=RNG"
        f"&FD={start_date}&TD={end_date}&FNY=&CSVF=TT&html.x=66&html.y=26"
        f"&SeriesCodes={series_code}&UsingCodes=Y"
    )
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept":     "text/html,application/xhtml+xml",
    }
    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        lines = r.text.strip().splitlines()

        # BoE CSV format: date in first column, value in second
        # Header row(s) start with non-numeric characters
        data: dict[str, float] = {}
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                continue
            date_str = parts[0]
            val_str  = parts[1]
            try:
                # BoE dates: "01 Jan 2024" or "2024-01-01"
                for fmt in ("%d %b %Y", "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(date_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    continue
                if val_str not in ("", "N/A", "."):
                    data[dt.strftime("%Y-%m-%d")] = float(val_str)
            except (ValueError, TypeError):
                continue

        return pd.Series(data).sort_index() if data else None

    except Exception as e:
        log.error("BoE fetch failed [%s]: %s", series_code, e)
        return None


def _fetch_oecd(series_key: str, months: int) -> Optional[pd.Series]:
    """
    OECD SDMX-JSON endpoint — free, no key.
    series_key format: "DATASET/FILTER"  e.g. "QNA/GBR.B1_GE.GYSA.Q"
    or                 "MEI/JPN.CPALTT01.IXNBSA.M"
    Endpoint: https://stats.oecd.org/SDMX-JSON/data/{dataset}/{filter}/all
    """
    if "/" not in series_key:
        log.warning("OECD series_key must be 'DATASET/FILTER', got: %s", series_key)
        return None

    dataset, data_filter = series_key.split("/", 1)
    start_period = (datetime.utcnow() - timedelta(days=months * 31)).strftime("%Y-%m")
    url = f"https://stats.oecd.org/SDMX-JSON/data/{dataset}/{data_filter}/all"
    params = {
        "startTime":   start_period,
        "contentType": "json",
    }
    headers = {"Accept": "application/json"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=25)
        r.raise_for_status()
        payload = r.json()

        # OECD SDMX-JSON structure
        dataset_obj  = payload.get("dataSets", [{}])[0]
        structure    = payload.get("structure", {})
        dims         = structure.get("dimensions", {}).get("observation", [])
        time_dim     = next((d for d in dims if d.get("id") == "TIME_PERIOD"), None)

        if not time_dim:
            log.warning("OECD: no TIME_PERIOD dimension for %s", series_key)
            return None

        time_values = [v["id"] for v in time_dim.get("values", [])]
        series_data = dataset_obj.get("series", {})
        if not series_data:
            return None

        # Merge all series if multiple are returned (take first for simplicity)
        first_series = next(iter(series_data.values()))
        obs = first_series.get("observations", {})

        data: dict[str, float] = {}
        for idx_str, values in obs.items():
            idx = int(idx_str)
            if idx < len(time_values) and values and values[0] is not None:
                data[time_values[idx]] = float(values[0])

        return pd.Series(data).sort_index() if data else None

    except Exception as e:
        log.error("OECD fetch failed [%s]: %s", series_key, e)
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC ROUTER
# ══════════════════════════════════════════════════════════════════════════════

def fetch_series(series_id: str, months: int = 12) -> Optional[pd.Series]:
    """
    Unified series fetcher.  Routes by prefix:
      "ECB:"   → ECB Statistical Data Warehouse
      "ESTAT:" → Eurostat dissemination API
      "ONS:"   → ONS UK API
      "BOE:"   → Bank of England database CSV
      "OECD:"  → OECD SDMX-JSON
      bare     → FRED (backward compatible with indicators.py)

    Results are cached in-process for CACHE_TTL seconds.
    Returns a pandas Series indexed by date strings, or None on failure.
    """
    cache_key = (series_id, months)
    now_ts    = time.time()

    cached = _cache.get(cache_key)
    if cached and (now_ts - cached[0]) < CACHE_TTL:
        return cached[1]

    sid = series_id.strip()

    if sid.startswith("ECB:"):
        result = _fetch_ecb_sdw(sid[4:], months)
    elif sid.startswith("ESTAT:"):
        result = _fetch_eurostat(sid[6:], months)
    elif sid.startswith("ONS:"):
        result = _fetch_ons(sid[4:], months)
    elif sid.startswith("BOE:"):
        result = _fetch_boe(sid[4:], months)
    elif sid.startswith("OECD:"):
        result = _fetch_oecd(sid[5:], months)
    else:
        result = _fetch_fred(sid, months)

    _cache[cache_key] = (now_ts, result)
    return result


def invalidate_cache(series_id: Optional[str] = None) -> None:
    """Clear the in-process cache for a specific series, or all entries."""
    if series_id is None:
        _cache.clear()
    else:
        keys_to_del = [k for k in _cache if k[0] == series_id]
        for k in keys_to_del:
            del _cache[k]


# ══════════════════════════════════════════════════════════════════════════════
# RATE DIFFERENTIAL COMPUTATION
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RateDiff:
    currency:        str
    local_yield_pct: Optional[float]
    us_yield_pct:    Optional[float]
    spread_pct:      Optional[float]   # local - US
    spread_3m_avg:   Optional[float]
    trend_direction: str               # "WIDENING" | "NARROWING" | "FLAT" | "UNKNOWN"


def _latest_value(series: Optional[pd.Series]) -> Optional[float]:
    """Return the most recent non-null value from a Series."""
    if series is None or series.empty:
        return None
    return float(series.dropna().iloc[-1])


def _trailing_mean(series: Optional[pd.Series], n_periods: int) -> Optional[float]:
    """Return trailing N-period mean of a Series."""
    if series is None or len(series) < 2:
        return None
    window = series.dropna().tail(n_periods)
    return float(window.mean()) if not window.empty else None


def compute_rate_differentials() -> dict[str, RateDiff]:
    """
    Fetch benchmark yields for all 8 currencies + US 10Y Treasury, then
    compute the spread (local − US), trailing 3-month average, and trend.

    Saves each RateDifferential snapshot to the database and returns a
    dict keyed by currency code.

    Yield sources (from config/events.py RATE_SERIES):
      USD: FRED DGS10          (US 10Y Treasury)
      EUR: ECB SDW IRS 10Y
      GBP: BoE Gilt nominal 10Y
      JPY: ECB SDW JPY IRS 10Y
      AUD: FRED IR3TIB01AUM156N (3M interbank proxy)
      CHF: ECB SDW CHF IRS 10Y
      CAD: FRED IR3TIB01CAM156N
      NZD: FRED IR3TIB01NZM156N
    """
    # Fetch US 10Y first — needed for all differentials
    us_series_id, us_source = RATE_SERIES["USD"]
    us_series = fetch_series(us_series_id, months=6)
    us_yield  = _latest_value(us_series)

    if us_yield is None:
        log.warning("Could not fetch US 10Y yield — rate differentials will be incomplete.")

    results: dict[str, RateDiff] = {}
    db = SessionLocal()

    try:
        for currency, (series_id, source) in RATE_SERIES.items():
            if currency == "USD":
                # USD vs itself = 0; still record for completeness
                diff = RateDiff(
                    currency="USD",
                    local_yield_pct=us_yield,
                    us_yield_pct=us_yield,
                    spread_pct=0.0,
                    spread_3m_avg=0.0,
                    trend_direction="FLAT",
                )
                results["USD"] = diff
                _persist_rate_diff(db, diff)
                continue

            # Source routing follows fetch_series() prefix convention
            if source == "fred":
                local_series = fetch_series(series_id, months=6)
            elif source == "ecb_sdw":
                local_series = fetch_series(f"ECB:{series_id}", months=6)
            elif source == "boe":
                local_series = fetch_series(f"BOE:{series_id}", months=6)
            else:
                local_series = fetch_series(series_id, months=6)

            local_yield = _latest_value(local_series)

            # Compute spread and 3-month trailing average
            spread: Optional[float] = None
            spread_3m: Optional[float] = None
            if local_yield is not None and us_yield is not None:
                spread = round(local_yield - us_yield, 4)

                # Build a synthetic spread series for trailing average
                if local_series is not None and us_series is not None:
                    # Align on common dates
                    combined = pd.DataFrame({
                        "local": local_series,
                        "us":    us_series,
                    }).dropna()
                    if not combined.empty:
                        spread_series = combined["local"] - combined["us"]
                        # 3 months ≈ 3 observations for quarterly or 3 for monthly
                        spread_3m = _trailing_mean(spread_series, n_periods=3)

            # Trend: compare current spread to the 3-month average
            trend = "UNKNOWN"
            if spread is not None and spread_3m is not None:
                delta = spread - spread_3m
                if delta > 0.05:
                    trend = "WIDENING"    # foreign yield rising faster than US
                elif delta < -0.05:
                    trend = "NARROWING"
                else:
                    trend = "FLAT"

            diff = RateDiff(
                currency=currency,
                local_yield_pct=local_yield,
                us_yield_pct=us_yield,
                spread_pct=spread,
                spread_3m_avg=round(spread_3m, 4) if spread_3m is not None else None,
                trend_direction=trend,
            )
            results[currency] = diff
            _persist_rate_diff(db, diff)
            log.info(
                "Rate diff %s: local=%.3f%% US=%.3f%% spread=%.3f%% trend=%s",
                currency,
                local_yield  or 0,
                us_yield     or 0,
                spread       or 0,
                trend,
            )

        db.commit()
    except Exception as e:
        log.error("Rate differential computation failed: %s", e)
        db.rollback()
    finally:
        db.close()

    return results


def _persist_rate_diff(db, diff: RateDiff) -> None:
    """Insert a new RateDifferential row — called inside compute_rate_differentials()."""
    row = RateDifferential(
        recorded_at     = datetime.utcnow(),
        currency        = diff.currency,
        local_yield_pct = diff.local_yield_pct,
        us_yield_pct    = diff.us_yield_pct,
        spread_pct      = diff.spread_pct,
        spread_3m_avg   = diff.spread_3m_avg,
        trend_direction = diff.trend_direction,
    )
    db.add(row)


def get_rate_differential(currency: str) -> Optional[RateDiff]:
    """
    Return the most recent RateDiff for a currency from the database.
    Returns None if no data has been computed yet.
    """
    db = SessionLocal()
    try:
        row = (
            db.query(RateDifferential)
            .filter_by(currency=currency.upper())
            .order_by(RateDifferential.recorded_at.desc())
            .first()
        )
        if row is None:
            return None
        return RateDiff(
            currency        = row.currency,
            local_yield_pct = row.local_yield_pct,
            us_yield_pct    = row.us_yield_pct,
            spread_pct      = row.spread_pct,
            spread_3m_avg   = row.spread_3m_avg,
            trend_direction = row.trend_direction or "UNKNOWN",
        )
    finally:
        db.close()


def get_all_rate_differentials() -> dict[str, RateDiff]:
    """Return latest RateDiff for all 8 currencies from the database."""
    from config.events import CURRENCIES
    return {
        ccy: diff
        for ccy in CURRENCIES
        if (diff := get_rate_differential(ccy)) is not None
    }


def rate_diff_to_score(diff: Optional[RateDiff]) -> float:
    """
    Normalise a RateDiff spread into a [-1, +1] feature score for River.

    Logic:
      spread > +2.0%  → +1.0 (foreign yield much higher than US = strong foreign CCY)
      spread < -2.0%  → -1.0 (foreign yield much lower than US = weak foreign CCY)
      Linear interpolation between those bounds.
      USD always returns 0.0 (it's the reference currency).
    """
    if diff is None or diff.spread_pct is None:
        return 0.0
    if diff.currency == "USD":
        return 0.0
    clamped = max(-2.0, min(2.0, diff.spread_pct))
    return round(clamped / 2.0, 4)
