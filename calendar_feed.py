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
    "Non-Farm Employment Change": "NFP",
    "Nonfarm Payrolls":           "NFP",
    "Unemployment Rate":          "UNEMPLOYMENT_RATE",
    "Unemployment Claims":        "JOBLESS_CLAIMS",
    "Initial Jobless Claims":     "JOBLESS_CLAIMS",
    "CPI m/m":                    "CPI",
    "CPI y/y":                    "CPI",
    "Core CPI m/m":               "CORE_CPI",
    "Core CPI y/y":               "CORE_CPI",
    "PPI m/m":                    "PPI",
    "PPI y/y":                    "PPI",
    "Retail Sales m/m":           "RETAIL_SALES",
    "Core Retail Sales m/m":      "RETAIL_SALES",
    "CB Consumer Confidence":     "CONSUMER_CONFIDENCE",
    "Prelim UoM Consumer Sentiment": "CONSUMER_CONFIDENCE",
    "Revised UoM Consumer Sentiment": "CONSUMER_CONFIDENCE",
    "ISM Manufacturing PMI":      "ISM_MFG",
    "ISM Manufacturing":          "ISM_MFG",
    "Prelim GDP q/q":             "GDP",
    "Final GDP q/q":              "GDP",
    "GDP q/q":                    "GDP",
    "FOMC Statement":             "FOMC",
    "Federal Funds Rate":         "FOMC",
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

    results = []
    for ev in raw_events:
        # Only USD events
        if ev.get("country", "").upper() != "USD":
            continue

        title = ev.get("title", "")

        # Match to our known event codes
        event_code = None
        for ff_name, code in FF_EVENT_MAP.items():
            if ff_name.lower() in title.lower():
                event_code = code
                break

        if not event_code:
            continue

        # Only HIGH impact (red folder) or key medium if it's jobless claims / sentiment
        impact = ev.get("impact", "").lower()
        if impact != "high" and not ("claims" in title.lower() or "sentiment" in title.lower()):
            continue

        def _parse_num(val: str) -> Optional[float]:
            if not val:
                return None
            cleaned = re.sub(r"[^\d.\-]", "", str(val))
            try:
                return float(cleaned)
            except ValueError:
                return None

        results.append({
            "event_code":        event_code,
            "event_name":        title,
            "release_time_utc":  ev.get("date"),
            "forecast":          _parse_num(ev.get("forecast")),
            "previous":          _parse_num(ev.get("previous")),
            "actual":            _parse_num(ev.get("actual")),
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
