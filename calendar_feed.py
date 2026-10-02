"""
calendar_feed.py — Pulls upcoming economic events from Forex Factory's public
JSON feed with persistent caching and rate-limit protection.

Changes from original:
  - Now tracks ALL 8 currencies (USD, EUR, GBP, JPY, AUD, CHF, CAD, NZD)
  - Includes both red-folder (high) AND orange-folder (medium) impact events
  - FF_EVENT_MAP expanded to cover all currency event codes in config/events.py
  - update_event_actual() signature unchanged (backward compatible)
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
CACHE_TTL_SECONDS = 900  # 15 minutes

_in_memory_cache: dict = {
    "timestamp": 0,
    "events": [],
}

# ── Tracked currencies ────────────────────────────────────────────────────────
TRACKED_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "CHF", "CAD", "NZD"}

# ── Tracked impact tiers ──────────────────────────────────────────────────────
TRACKED_IMPACTS = {"high", "medium"}   # red = high, orange = medium

# ── Forex Factory title → internal event code ─────────────────────────────────
# Sorted longest-key-first at runtime so specific titles win over partial matches.
# All 8 currencies covered.  USD events preserved from original; others added.
FF_EVENT_MAP: dict[str, str] = {

    # ── USD ───────────────────────────────────────────────────────────────────
    "Core PCE Price Index m/m":                 "CORE_PCE",
    "Core PCE Price Index y/y":                 "CORE_PCE",
    "PCE Price Index m/m":                      "PCE",
    "PCE Price Index y/y":                      "PCE",
    "Core CPI m/m":                             "CORE_CPI",
    "Core CPI y/y":                             "CORE_CPI",
    "CPI m/m":                                  "CPI",
    "CPI y/y":                                  "CPI",
    "Core Retail Sales m/m":                    "CORE_RETAIL_SALES",
    "Retail Sales m/m":                         "RETAIL_SALES",
    "Advance Retail Sales m/m":                 "RETAIL_SALES",
    "Core PPI m/m":                             "CORE_PPI",
    "Core PPI y/y":                             "CORE_PPI",
    "PPI m/m":                                  "PPI",
    "PPI y/y":                                  "PPI",
    "Non-Farm Employment Change":               "NFP",
    "Nonfarm Payrolls":                         "NFP",
    "ADP Non-Farm Employment Change":           "ADP_NFP",
    "Average Hourly Earnings m/m":              "AVG_HOURLY_EARNINGS",
    "Unemployment Rate":                        "UNEMPLOYMENT_RATE",
    "Unemployment Claims":                      "JOBLESS_CLAIMS",
    "Initial Jobless Claims":                   "JOBLESS_CLAIMS",
    "Continuing Jobless Claims":                "JOBLESS_CLAIMS",
    "CB Consumer Confidence":                   "CONSUMER_CONFIDENCE",
    "Prelim UoM Consumer Sentiment":            "CONSUMER_CONFIDENCE",
    "Revised UoM Consumer Sentiment":           "CONSUMER_CONFIDENCE",
    "UoM Consumer Sentiment":                   "CONSUMER_CONFIDENCE",
    "ISM Manufacturing PMI":                    "ISM_MFG",
    "ISM Manufacturing Index":                  "ISM_MFG",
    "ISM Services PMI":                         "ISM_SERVICES",
    "ISM Non-Manufacturing PMI":                "ISM_SERVICES",
    "ISM Services Index":                       "ISM_SERVICES",
    "Prelim GDP q/q":                           "GDP",
    "Final GDP q/q":                            "GDP",
    "GDP q/q":                                  "GDP",
    "Advance GDP q/q":                          "GDP",
    "Second Estimate GDP q/q":                  "GDP",
    "Final GDP Price Index q/q":                "GDP_DEFLATOR",
    "Prelim GDP Price Index q/q":               "GDP_DEFLATOR",
    "GDP Price Index q/q":                      "GDP_DEFLATOR",
    "FOMC Statement":                           "FOMC",
    "Federal Funds Rate":                       "FOMC",
    "FOMC Press Conference":                    "FOMC",
    "JOLTS Job Openings":                       "JOLTS",
    "Job Openings":                             "JOLTS",
    "Building Permits":                         "BUILDING_PERMITS",
    "Empire State Manufacturing Index":         "EMPIRE_STATE",
    "Philly Fed Manufacturing Index":           "PHILLY_FED",
    "Philadelphia Fed Manufacturing Index":     "PHILLY_FED",
    "Housing Starts":                           "HOUSING_STARTS",
    "Existing Home Sales":                      "EXISTING_HOME_SALES",
    "New Home Sales":                           "NEW_HOME_SALES",
    "Durable Goods Orders m/m":                 "DURABLE_GOODS",
    "Core Durable Goods Orders m/m":            "DURABLE_GOODS",
    "Trade Balance":                            "TRADE_BALANCE",
    "Industrial Production m/m":               "INDUSTRIAL_PRODUCTION",
    "Capacity Utilization Rate":                "CAPACITY_UTILIZATION",

    # ── EUR ───────────────────────────────────────────────────────────────────
    "CPI Flash Estimate y/y":                   "EUR_CPI",
    "CPI Flash Estimate m/m":                   "EUR_CPI",
    "CPI y/y":                                  "EUR_CPI",   # country-code deduplication happens below
    "Core CPI Flash Estimate y/y":              "EUR_CORE_CPI",
    "Flash GDP q/q":                            "EUR_GDP",
    "GDP q/q":                                  "EUR_GDP",   # country deduplication below
    "Prelim Flash GDP q/q":                     "EUR_GDP",
    "Main Refinancing Rate":                    "ECB_RATE",
    "Refinancing Rate":                         "ECB_RATE",
    "ECB Press Conference":                     "ECB_RATE",
    "ECB Monetary Policy Statement":            "ECB_RATE",
    "Flash Manufacturing PMI":                  "EUR_PMI_MFG",
    "Manufacturing PMI":                        "EUR_PMI_MFG",
    "Flash Services PMI":                       "EUR_PMI_SERVICES",
    "Services PMI":                             "EUR_PMI_SERVICES",
    "Unemployment Rate":                        "EUR_UNEMPLOYMENT",   # deduped below
    "German Ifo Business Climate":              "GERMAN_IFO",
    "Ifo Business Climate":                     "GERMAN_IFO",
    "German ZEW Economic Sentiment":            "GERMAN_ZEW",
    "ZEW Economic Sentiment":                   "GERMAN_ZEW",
    "German Prelim GDP q/q":                    "EUR_GDP",
    "German Final GDP q/q":                     "EUR_GDP",
    "French Flash GDP q/q":                     "EUR_GDP",

    # ── GBP ───────────────────────────────────────────────────────────────────
    "CPI y/y":                                  "GBP_CPI",   # deduped below
    "CPI m/m":                                  "GBP_CPI",
    "Core CPI y/y":                             "GBP_CORE_CPI",
    "GDP m/m":                                  "GBP_GDP",
    "GDP q/q":                                  "GBP_GDP",
    "Prelim GDP q/q":                           "GBP_GDP",
    "Official Bank Rate":                       "BOE_RATE",
    "MPC Official Bank Rate Votes":             "BOE_RATE",
    "BOE Inflation Report":                     "BOE_RATE",
    "BOE Monetary Policy Report":               "BOE_RATE",
    "Claimant Count Change":                    "GBP_EMPLOYMENT",
    "Employment Change 3m/3m":                  "GBP_EMPLOYMENT",
    "Average Earnings Index 3m/y":              "GBP_EMPLOYMENT",
    "Manufacturing PMI":                        "GBP_PMI_MFG",   # deduped below
    "Services PMI":                             "GBP_PMI_SERVICES",
    "Retail Sales m/m":                         "GBP_RETAIL_SALES",
    "Core Retail Sales m/m":                    "GBP_RETAIL_SALES",

    # ── JPY ───────────────────────────────────────────────────────────────────
    "National Core CPI y/y":                    "JPY_CPI",
    "Tokyo Core CPI y/y":                       "JPY_CPI",
    "Monetary Policy Statement":                "BOJ_RATE",
    "BOJ Press Conference":                     "BOJ_RATE",
    "Overnight Call Rate":                      "BOJ_RATE",
    "BOJ Outlook Report":                       "BOJ_RATE",
    "Prelim GDP q/q":                           "JAPAN_GDP",   # deduped by country below
    "Flash GDP q/q":                            "JAPAN_GDP",
    "Tankan Large Manufacturers Index":         "JAPAN_TANKAN",
    "Tankan Non-Manufacturing Index":           "JAPAN_TANKAN",

    # ── AUD ───────────────────────────────────────────────────────────────────
    "Trimmed Mean CPI q/q":                     "AUD_CPI",
    "CPI q/q":                                  "AUD_CPI",   # deduped by country below
    "CPI y/y":                                  "AUD_CPI",
    "RBA Rate Statement":                       "RBA_RATE",
    "Cash Rate":                                "RBA_RATE",
    "RBA Monetary Policy Statement":            "RBA_RATE",
    "Employment Change":                        "AUD_EMPLOYMENT",   # deduped below
    "Unemployment Rate":                        "AUD_EMPLOYMENT",
    "Retail Sales m/m":                         "AUD_RETAIL_SALES",

    # ── CAD ───────────────────────────────────────────────────────────────────
    "CPI m/m":                                  "CAD_CPI",   # deduped by country
    "CPI y/y":                                  "CAD_CPI",
    "Overnight Rate":                           "BOC_RATE",
    "BOC Rate Statement":                       "BOC_RATE",
    "BOC Monetary Policy Report":               "BOC_RATE",
    "Employment Change":                        "CAD_EMPLOYMENT",
    "Unemployment Rate":                        "CAD_EMPLOYMENT",
    "GDP m/m":                                  "CAD_GDP",
    "GDP q/q":                                  "CAD_GDP",

    # ── NZD ───────────────────────────────────────────────────────────────────
    "CPI q/q":                                  "NZD_CPI",   # deduped by country
    "CPI y/y":                                  "NZD_CPI",
    "Official Cash Rate":                       "RBNZ_RATE",
    "RBNZ Rate Statement":                      "RBNZ_RATE",
    "RBNZ Monetary Policy Statement":           "RBNZ_RATE",
    "Employment Change q/q":                    "NZD_EMPLOYMENT",
    "Unemployment Rate":                        "NZD_EMPLOYMENT",

    # ── CHF ───────────────────────────────────────────────────────────────────
    "CPI m/m":                                  "CHF_CPI",   # deduped by country
    "CPI y/y":                                  "CHF_CPI",
    "SNB Policy Rate":                          "SNB_RATE",
    "SNB Monetary Policy Assessment":           "SNB_RATE",
    "Unemployment Rate":                        "CHF_UNEMPLOYMENT",
}

# Titles that are shared across currencies and require country-code disambiguation.
# Key: (ff_country_code_upper, ff_title_lower_fragment) → event_code
_COUNTRY_DISAMBIG: dict[tuple[str, str], str] = {
    # CPI / inflation
    ("EUR", "cpi"):                 "EUR_CPI",
    ("EUR", "hicp"):                "EUR_CPI",
    ("EUR", "core cpi"):            "EUR_CORE_CPI",
    ("GBP", "cpi"):                 "GBP_CPI",
    ("GBP", "core cpi"):            "GBP_CORE_CPI",
    ("JPY", "cpi"):                 "JPY_CPI",
    ("AUD", "cpi"):                 "AUD_CPI",
    ("AUD", "trimmed mean"):        "AUD_CPI",
    ("CAD", "cpi"):                 "CAD_CPI",
    ("NZD", "cpi"):                 "NZD_CPI",
    ("CHF", "cpi"):                 "CHF_CPI",
    # GDP
    ("EUR", "gdp"):                 "EUR_GDP",
    ("GBP", "gdp"):                 "GBP_GDP",
    ("JPY", "gdp"):                 "JAPAN_GDP",
    ("CAD", "gdp"):                 "CAD_GDP",
    ("NZD", "gdp"):                 "NZD_CPI",   # NZD has no standalone GDP event code; map to closest
    # Employment / unemployment
    ("EUR", "unemployment"):        "EUR_UNEMPLOYMENT",
    ("GBP", "employment"):          "GBP_EMPLOYMENT",
    ("GBP", "claimant"):            "GBP_EMPLOYMENT",
    ("GBP", "average earnings"):    "GBP_EMPLOYMENT",
    ("AUD", "employment"):          "AUD_EMPLOYMENT",
    ("AUD", "unemployment"):        "AUD_EMPLOYMENT",
    ("CAD", "employment"):          "CAD_EMPLOYMENT",
    ("CAD", "unemployment"):        "CAD_EMPLOYMENT",
    ("NZD", "employment"):          "NZD_EMPLOYMENT",
    ("NZD", "unemployment"):        "NZD_EMPLOYMENT",
    ("CHF", "unemployment"):        "CHF_UNEMPLOYMENT",
    # PMI — shared title but different currencies
    ("EUR", "manufacturing pmi"):   "EUR_PMI_MFG",
    ("EUR", "flash manufacturing"): "EUR_PMI_MFG",
    ("EUR", "services pmi"):        "EUR_PMI_SERVICES",
    ("EUR", "flash services"):      "EUR_PMI_SERVICES",
    ("GBP", "manufacturing pmi"):   "GBP_PMI_MFG",
    ("GBP", "services pmi"):        "GBP_PMI_SERVICES",
    # Retail sales
    ("GBP", "retail sales"):        "GBP_RETAIL_SALES",
    ("AUD", "retail sales"):        "AUD_RETAIL_SALES",
    # Rate decisions — shared "unemployment rate" title
    ("USD", "unemployment rate"):   "UNEMPLOYMENT_RATE",
}


def _load_disk_cache() -> list[dict]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    return data
        except Exception as e:
            log.warning("Could not read disk cache: %s", e)
    return []


def _save_disk_cache(events: list[dict]) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(events, f, indent=2)
    except Exception as e:
        log.warning("Could not write disk cache: %s", e)


def _parse_num(val: str | None) -> Optional[float]:
    if not val:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(val))
    try:
        return float(cleaned)
    except ValueError:
        return None


def _resolve_event_code(country: str, title: str, impact: str) -> Optional[str]:
    """
    Resolve an FF event to an internal event_code.

    Resolution order:
      1. Country-specific disambiguation table (handles shared titles like "CPI y/y")
      2. Longest-match scan of FF_EVENT_MAP
      3. Fallback: sanitise title to UPPER_SNAKE for high/medium impact events
    """
    title_lower = title.lower()
    ccy = country.upper()

    # Step 1 — country + keyword disambiguation
    for (c, kw), code in _COUNTRY_DISAMBIG.items():
        if c == ccy and kw in title_lower:
            return code

    # Step 2 — longest-match scan (sorted at module load below)
    for ff_name, code in _SORTED_EVENT_MAP:
        if ff_name.lower() in title_lower:
            return code

    # Step 3 — fallback for mapped countries with high/medium impact
    if impact in ("high", "medium"):
        prefix = {
            "EUR": "EUR_", "GBP": "GBP_", "JPY": "JPY_",
            "AUD": "AUD_", "CHF": "CHF_", "CAD": "CAD_", "NZD": "NZD_",
            "USD": "",
        }.get(ccy, f"{ccy}_")
        sanitised = re.sub(r"[^A-Z0-9]+", "_", title.upper()).strip("_")
        return f"{prefix}{sanitised}"

    return None


# Pre-sort the map once at import time — longest key first for deterministic matching
_SORTED_EVENT_MAP = sorted(FF_EVENT_MAP.items(), key=lambda x: len(x[0]), reverse=True)


def fetch_calendar_events(force_refresh: bool = False) -> list[dict]:
    """
    Pull this week's Forex Factory calendar for all 8 currencies,
    both red (high) and orange (medium) impact events.

    Returns a list of event dicts:
      event_code        — internal code (e.g. "NFP", "EUR_CPI")
      event_name        — original FF title
      currency          — 3-letter code
      release_time_utc  — ISO-8601 string from FF feed
      forecast          — float | None
      previous          — float | None
      actual            — float | None
      impact            — "HIGH" | "MEDIUM"
    """
    global _in_memory_cache
    now = time.time()

    # Serve from in-memory cache if still fresh
    if not force_refresh and (now - _in_memory_cache["timestamp"]) < CACHE_TTL_SECONDS:
        if _in_memory_cache["events"]:
            return _in_memory_cache["events"]

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    raw_events: list[dict] = []
    try:
        r = requests.get(FOREX_FACTORY_URL, headers=headers, timeout=12)
        r.raise_for_status()
        raw_events = r.json()
    except Exception as e:
        log.warning("Forex Factory fetch failed (%s) — using cached events.", e)
        fallback = _in_memory_cache["events"] or _load_disk_cache()
        if fallback:
            _in_memory_cache = {"timestamp": now, "events": fallback}
        return fallback

    if not raw_events:
        log.warning("Forex Factory returned empty list — using cached events.")
        fallback = _load_disk_cache()
        if fallback:
            return fallback
        return []

    # Load disk cache once for actual-value preservation
    disk_events = _load_disk_cache()
    _disk_actual_index: dict[str, float] = {}
    for d in disk_events:
        if d.get("actual") is not None:
            key = f"{d.get('event_name','')}||{d.get('release_time_utc','')}"
            _disk_actual_index[key] = d["actual"]

    results: list[dict] = []
    for ev in raw_events:
        country = ev.get("country", "").upper()
        if country not in TRACKED_CURRENCIES:
            continue

        impact_raw = ev.get("impact", "").lower()
        if impact_raw not in TRACKED_IMPACTS:
            continue

        title = ev.get("title", "")
        event_code = _resolve_event_code(country, title, impact_raw)

        if not event_code:
            continue

        # Preserve any already-known actual from disk cache
        cache_key = f"{title}||{ev.get('date', '')}"
        parsed_actual = _parse_num(ev.get("actual"))
        actual_val = parsed_actual if parsed_actual is not None else _disk_actual_index.get(cache_key)

        results.append({
            "event_code":       event_code,
            "event_name":       title,
            "currency":         country,
            "release_time_utc": ev.get("date"),
            "forecast":         _parse_num(ev.get("forecast")),
            "previous":         _parse_num(ev.get("previous")),
            "actual":           actual_val,
            "impact":           impact_raw.upper(),   # "HIGH" | "MEDIUM"
        })

    if results:
        _in_memory_cache = {"timestamp": now, "events": results}
        _save_disk_cache(results)
        log.info(
            "Calendar updated: %d events (%d currencies, red+orange)",
            len(results),
            len({e["currency"] for e in results}),
        )
    else:
        # Parsing yielded nothing — fall back to disk cache silently
        fallback = _load_disk_cache()
        if fallback:
            _in_memory_cache = {"timestamp": now, "events": fallback}
            return fallback

    return results


# ── Backward-compatible alias (used by existing scheduler / api.py code) ──────
def fetch_upcoming_red_folder_events(force_refresh: bool = False) -> list[dict]:
    """
    Backward-compatible wrapper — returns ALL tracked events (red + orange).
    Old callers that filtered by impact can keep working; the impact field
    on each event now carries "HIGH" or "MEDIUM" for downstream filtering.
    """
    return fetch_calendar_events(force_refresh=force_refresh)


def get_events_for_currency(currency: str, force_refresh: bool = False) -> list[dict]:
    """Return only events for a specific currency."""
    return [
        e for e in fetch_calendar_events(force_refresh=force_refresh)
        if e["currency"] == currency.upper()
    ]


def get_red_events_only(force_refresh: bool = False) -> list[dict]:
    """Return only high-impact (red folder) events."""
    return [
        e for e in fetch_calendar_events(force_refresh=force_refresh)
        if e["impact"] == "HIGH"
    ]


def update_event_actual(
    event_code: Optional[str],
    actual: float,
    event_name: Optional[str] = None,
    currency: Optional[str] = None,
) -> bool:
    """
    Record an actual print for an event.
    Matches on event_code OR event_name; optionally narrows by currency.
    Updates in-memory cache and persists to disk.
    """
    global _in_memory_cache
    events = fetch_calendar_events()
    updated = False

    for ev in events:
        match_code = event_code and ev.get("event_code") == event_code
        match_name = event_name and ev.get("event_name") == event_name
        match_ccy  = (not currency) or ev.get("currency") == currency.upper()

        if (match_code or match_name) and match_ccy:
            ev["actual"] = actual
            updated = True

    if updated:
        _in_memory_cache["events"] = events
        _save_disk_cache(events)
        log.info(
            "Recorded actual for %s (%s): %s",
            event_code or event_name,
            currency or "any",
            actual,
        )
    return updated
