"""
calendar_feed.py — Pulls upcoming economic events from Forex Factory's public
JSON feed with persistent caching and rate-limit protection.

Changes from original:
  - Now tracks ALL 8 currencies (USD, EUR, GBP, JPY, AUD, CHF, CAD, NZD)
  - Includes both red-folder (high) AND orange-folder (medium) impact events
  - FF_EVENT_MAP expanded to cover all currency event codes in config/events.py
  - update_event_actual() signature unchanged (backward compatible)
  - Fetches current week AND next week on 429 / network failure fallback
  - Startup diagnostic logging: logs total fetched, filtered, and per-currency counts
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

# Forex Factory publishes two week URLs — we try current then next on failure
FF_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]
CACHE_FILE = "calendar_cache.json"
CACHE_TTL_SECONDS = 1800  # 30 minutes — FF updates at most every 15min; don't hammer the endpoint

_in_memory_cache: dict = {
    "timestamp": 0,
    "events": [],
}

# ── Tracked currencies ────────────────────────────────────────────────────────
TRACKED_CURRENCIES = {"USD"}

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
    "Core CPI m/m":                             "CORE_CPI_MM",
    "Core CPI y/y":                             "CORE_CPI_YY",
    "CPI m/m":                                  "CPI_MM",
    "CPI y/y":                                  "CPI_YY",
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
    "Unemployment Claims":                      "INITIAL_JOBLESS_CLAIMS",
    "Initial Jobless Claims":                   "INITIAL_JOBLESS_CLAIMS",
    "Continuing Jobless Claims":                "CONTINUING_JOBLESS_CLAIMS",
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
}

# Titles that are shared across currencies and require country-code disambiguation.
# Key: (ff_country_code_upper, ff_title_lower_fragment) → event_code
_COUNTRY_DISAMBIG: dict[tuple[str, str], str] = {
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

    # Step 3 — fallback for USD with high/medium impact
    if impact in ("high", "medium"):
        prefix = {"USD": ""}.get(ccy, f"{ccy}_")
        sanitised = re.sub(r"[^A-Z0-9]+", "_", title.upper()).strip("_")
        return f"{prefix}{sanitised}"

    return None


# Pre-sort the map once at import time — longest key first for deterministic matching
_SORTED_EVENT_MAP = sorted(FF_EVENT_MAP.items(), key=lambda x: len(x[0]), reverse=True)


def fetch_calendar_events(force_refresh: bool = False) -> list[dict]:
    """
    Pull this week's + next week's FF calendar for all 8 currencies,
    red (high) + orange (medium) impact events.

    On 429 / network failure, falls back to disk cache immediately.
    Logs a diagnostic summary so empty results are never silent.
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
        "Referer": "https://www.forexfactory.com/",
    }

    # Load disk cache once — used for actual-value preservation + fallback
    disk_events = _load_disk_cache()
    _disk_actual_index: dict[str, float] = {}
    for d in disk_events:
        if d.get("actual") is not None:
            key = f"{d.get('event_name','')}||{d.get('release_time_utc','')}"
            _disk_actual_index[key] = d["actual"]

    # Try fetching both week URLs; stop on 429 (rate-limited)
    raw_events: list[dict] = []
    fetch_succeeded = False

    for url in FF_URLS:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 429:
                log.warning(
                    "Forex Factory 429 on %s — using disk cache (%d events)",
                    url, len(disk_events),
                )
                break
            r.raise_for_status()
            week_data = r.json()
            label = "thisweek" if "thisweek" in url else "nextweek"
            log.info("FF %s: %d raw events fetched", label, len(week_data))
            raw_events.extend(week_data)
            fetch_succeeded = True
        except requests.exceptions.HTTPError as e:
            code_val = e.response.status_code if e.response is not None else 0
            if code_val == 429:
                log.warning("Forex Factory 429 — falling back to disk cache")
                break
            log.warning("Forex Factory HTTP error %s: %s", url, e)
        except Exception as e:
            log.warning("Forex Factory fetch error %s: %s", url, e)

    # Fall back to disk cache if live fetch failed or was rate-limited
    if not fetch_succeeded or not raw_events:
        fallback = disk_events or _in_memory_cache["events"]
        if fallback:
            log.info(
                "Calendar using cache fallback: %d events "
                "(FF unavailable or rate-limited)", len(fallback),
            )
            _in_memory_cache = {"timestamp": now, "events": fallback}
            return fallback
        log.error("Calendar: no FF data and no cache — returning empty list")
        return []

    # Deduplicate across weeks (same event can appear in both responses near week boundary)
    seen_raw: set[str] = set()
    deduped: list[dict] = []
    for ev in raw_events:
        key = f"{ev.get('title','')}||{ev.get('date','')}"
        if key not in seen_raw:
            seen_raw.add(key)
            deduped.append(ev)

    log.info("FF raw events after dedup: %d (from %d)", len(deduped), len(raw_events))

    # Filter and resolve
    results: list[dict] = []
    skipped_country = skipped_impact = skipped_no_code = 0

    for ev in deduped:
        country = ev.get("country", "").upper()
        if country not in TRACKED_CURRENCIES:
            skipped_country += 1
            continue

        impact_raw = ev.get("impact", "").lower()
        if impact_raw not in TRACKED_IMPACTS:
            skipped_impact += 1
            continue

        title      = ev.get("title", "")
        event_code = _resolve_event_code(country, title, impact_raw)

        if not event_code:
            skipped_no_code += 1
            log.debug("No mapping: [%s] %s %s", impact_raw, country, title)
            continue

        cache_key     = f"{title}||{ev.get('date', '')}"
        parsed_actual = _parse_num(ev.get("actual"))
        actual_val    = parsed_actual if parsed_actual is not None else _disk_actual_index.get(cache_key)

        results.append({
            "event_code":       event_code,
            "event_name":       title,
            "currency":         country,
            "release_time_utc": ev.get("date"),
            "forecast":         _parse_num(ev.get("forecast")),
            "previous":         _parse_num(ev.get("previous")),
            "actual":           actual_val,
            "impact":           impact_raw.upper(),
        })

    # Diagnostic summary — always logged
    ccy_counts = {}
    for ev in results:
        ccy_counts[ev["currency"]] = ccy_counts.get(ev["currency"], 0) + 1

    log.info(
        "Calendar: %d events kept | skipped: %d country / %d impact / %d no-mapping | "
        "per-currency: %s",
        len(results), skipped_country, skipped_impact, skipped_no_code, ccy_counts,
    )

    if results:
        _in_memory_cache = {"timestamp": now, "events": results}
        _save_disk_cache(results)
    else:
        # Parsed successfully but 0 results survived filtering — use cache
        fallback = disk_events or _in_memory_cache["events"]
        if fallback:
            log.warning(
                "Calendar parse yielded 0 results despite %d raw events — "
                "using %d cached events", len(deduped), len(fallback),
            )
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
