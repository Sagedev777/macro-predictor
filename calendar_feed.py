"""
calendar_feed.py — Pulls upcoming high-impact events from Forex Factory's
public JSON feed with persistent caching and rate-limit protection.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger("calendar")

FOREX_FACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
CACHE_FILE = "calendar_cache.json"
CACHE_TTL_SECONDS = 900  # 15 minutes cache

_in_memory_cache = {
    "timestamp": 0,
    "events": []
}

# Map Forex Factory event titles → our internal event codes
FF_EVENT_MAP = {
    "Core PCE Price Index m/m":          "CORE_PCE",
    "Core PCE Price Index y/y":          "CORE_PCE",
    "PCE Price Index m/m":               "PCE",
    "PCE Price Index y/y":               "PCE",
    "Core CPI m/m":                      "CORE_CPI",
    "Core CPI y/y":                      "CORE_CPI",
    "CPI m/m":                           "CPI",
    "CPI y/y":                           "CPI",
    "Core Retail Sales m/m":             "CORE_RETAIL_SALES",
    "Retail Sales m/m":                  "RETAIL_SALES",
    "Advance Retail Sales m/m":          "RETAIL_SALES",
    "Core PPI m/m":                      "CORE_PPI",
    "Core PPI y/y":                      "CORE_PPI",
    "PPI m/m":                           "PPI",
    "PPI y/y":                           "PPI",
    "Non-Farm Employment Change":        "NFP",
    "Nonfarm Payrolls":                  "NFP",
    "ADP Non-Farm Employment Change":    "ADP_NFP",
    "Average Hourly Earnings m/m":       "AVG_HOURLY_EARNINGS",
    "Unemployment Rate":                 "UNEMPLOYMENT_RATE",
    "Unemployment Claims":               "JOBLESS_CLAIMS",
    "Initial Jobless Claims":            "JOBLESS_CLAIMS",
    "Continuing Jobless Claims":         "JOBLESS_CLAIMS",
    "CB Consumer Confidence":            "CONSUMER_CONFIDENCE",
    "Prelim UoM Consumer Sentiment":     "CONSUMER_CONFIDENCE",
    "Revised UoM Consumer Sentiment":    "CONSUMER_CONFIDENCE",
    "UoM Consumer Sentiment":            "CONSUMER_CONFIDENCE",
    "ISM Manufacturing PMI":             "ISM_MFG",
    "ISM Manufacturing Index":           "ISM_MFG",
    "ISM Services PMI":                  "ISM_SERVICES",
    "ISM Non-Manufacturing PMI":         "ISM_SERVICES",
    "ISM Services Index":                "ISM_SERVICES",
    "Prelim GDP q/q":                    "GDP",
    "Final GDP q/q":                     "GDP",
    "GDP q/q":                           "GDP",
    "Advance GDP q/q":                   "GDP",
    "Second Estimate GDP q/q":           "GDP",
    "Final GDP Price Index q/q":         "GDP_DEFLATOR",
    "Prelim GDP Price Index q/q":        "GDP_DEFLATOR",
    "GDP Price Index q/q":               "GDP_DEFLATOR",
    "FOMC Statement":                    "FOMC",
    "Federal Funds Rate":                "FOMC",
    "FOMC Press Conference":             "FOMC",
    "JOLTS Job Openings":                "JOLTS",
    "Job Openings":                      "JOLTS",
    "Building Permits":                  "BUILDING_PERMITS",
    "Empire State Manufacturing Index":  "EMPIRE_STATE",
    "Philly Fed Manufacturing Index":    "PHILLY_FED",
    "Philadelphia Fed Manufacturing Index": "PHILLY_FED",
    "Housing Starts":                    "HOUSING_STARTS",
    "Existing Home Sales":               "EXISTING_HOME_SALES",
    "New Home Sales":                    "NEW_HOME_SALES",
    "Durable Goods Orders m/m":          "DURABLE_GOODS",
    "Core Durable Goods Orders m/m":     "DURABLE_GOODS",
    "Trade Balance":                     "TRADE_BALANCE",
    "Industrial Production m/m":         "INDUSTRIAL_PRODUCTION",
    "Capacity Utilization Rate":         "CAPACITY_UTILIZATION",
}


def _load_disk_cache() -> list[dict]:
    """Load cached events from disk if available."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0:
                    return data
        except Exception as e:
            log.warning("Could not read disk cache: %s", e)
    return []


def _save_disk_cache(events: list[dict]):
    """Persist events to disk cache."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(events, f, indent=2)
    except Exception as e:
        log.warning("Could not write disk cache: %s", e)


def fetch_upcoming_red_folder_events(force_refresh: bool = False) -> list[dict]:
    """
    Pull this week's Forex Factory calendar with smart caching.
    Uses browser headers, in-memory + disk cache so events NEVER disappear.
    """
    global _in_memory_cache
    now = time.time()

    # If cache is valid and not forced, return cached events
    if not force_refresh and (now - _in_memory_cache["timestamp"]) < CACHE_TTL_SECONDS:
        if _in_memory_cache["events"]:
            return _in_memory_cache["events"]

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    raw_events = []
    try:
        r = requests.get(FOREX_FACTORY_URL, headers=headers, timeout=12)
        r.raise_for_status()
        raw_events = r.json()
    except Exception as e:
        log.warning("Forex Factory network fetch failed (%s). Using cached events.", e)
        # Fallback to in-memory or disk cache
        if _in_memory_cache["events"]:
            return _in_memory_cache["events"]
        disk_events = _load_disk_cache()
        if disk_events:
            _in_memory_cache = {"timestamp": now, "events": disk_events}
            return disk_events

    if not raw_events:
        # Fallback to cache if request returned empty
        disk_events = _load_disk_cache()
        if disk_events:
            return disk_events
        return []

    # Sort FF_EVENT_MAP by length of title descending so longer specific titles match before shorter ones
    sorted_map = sorted(FF_EVENT_MAP.items(), key=lambda x: len(x[0]), reverse=True)

    results = []
    for ev in raw_events:
        # Only USD events
        if ev.get("country", "").upper() != "USD":
            continue

        title = ev.get("title", "")
        impact = ev.get("impact", "").lower()

        # Match to our known event codes (longest title key first)
        event_code = None
        for ff_name, code in sorted_map:
            if ff_name.lower() in title.lower():
                event_code = code
                break

        # Fallback event code for unmapped high impact USD events
        if not event_code and impact == "high":
            # Sanitize title to UPPER_SNAKE_CASE
            event_code = re.sub(r"[^A-Z0-9]+", "_", title.upper()).strip("_")

        # Filtering rule: Include all High and Medium impact USD events, or any mapped event
        is_mapped = event_code is not None
        is_usd = ev.get("country", "").upper() == "USD"
        is_high_or_medium = impact in ("high", "medium")

        if not (is_usd and (is_mapped or is_high_or_medium)):
            continue

        def _parse_num(val: str) -> Optional[float]:
            if not val:
                return None
            cleaned = re.sub(r"[^\d.\-]", "", str(val))
            try:
                return float(cleaned)
            except ValueError:
                return None

        # Check if actual is already known in disk cache
        disk_events = _load_disk_cache()
        existing_actual = None
        for d in disk_events:
            if d.get("event_name") == title and d.get("release_time_utc") == ev.get("date"):
                if d.get("actual") is not None:
                    existing_actual = d.get("actual")
                break

        parsed_actual = _parse_num(ev.get("actual"))
        actual_val = parsed_actual if parsed_actual is not None else existing_actual

        results.append({
            "event_code":        event_code,
            "event_name":        title,
            "release_time_utc":  ev.get("date"),
            "forecast":          _parse_num(ev.get("forecast")),
            "previous":          _parse_num(ev.get("previous")),
            "actual":            actual_val,
            "impact":            ev.get("impact", "High").upper(),
        })

    if results:
        _in_memory_cache = {
            "timestamp": now,
            "events": results
        }
        _save_disk_cache(results)
        log.info("Forex Factory calendar updated: %d events cached", len(results))
    else:
        # If parsing yielded 0, fall back to disk cache
        disk_events = _load_disk_cache()
        if disk_events:
            return disk_events

    return results


def update_event_actual(event_code: Optional[str], actual: float, event_name: Optional[str] = None) -> bool:
    """
    Manually or programmatically record an actual print for an event.
    Updates in-memory cache and persists to disk cache.
    """
    global _in_memory_cache
    events = fetch_upcoming_red_folder_events()
    updated = False
    for ev in events:
        match_code = event_code and ev.get("event_code") == event_code
        match_name = event_name and ev.get("event_name") == event_name
        if match_code or match_name:
            ev["actual"] = actual
            updated = True

    if updated:
        _in_memory_cache["events"] = events
        _save_disk_cache(events)
        log.info("Recorded actual print for %s: %s", event_code or event_name, actual)
    return updated

