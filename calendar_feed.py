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

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

log = logging.getLogger("calendar")

# Forex Factory publishes two week URLs — we try current then next on failure
FF_URLS = [
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://nfs.faireconomy.media/ff_calendar_nextweek.json",
]
_CACHE_FILE_CONFIG = os.getenv(
    "MACRO_PREDICTOR_CALENDAR_CACHE", "calendar_cache.json"
)
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.abspath(
    _CACHE_FILE_CONFIG
    if os.path.isabs(_CACHE_FILE_CONFIG)
    else os.path.join(_PROJECT_ROOT, _CACHE_FILE_CONFIG)
)
CACHE_TTL_SECONDS = 1800  # 30 minutes — FF updates at most every 15min; don't hammer the endpoint
RELEASE_CACHE_TTL_SECONDS = 30
RATE_LIMIT_BACKOFF_SECONDS = 120

_in_memory_cache: dict = {
    "timestamp": 0,
    "events": [],
    "retry_after": 0,
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


def _load_disk_cache() -> tuple[list[dict], float, float]:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("events"), list):
                    return (
                        data["events"],
                        float(data.get("fetched_at", 0)),
                        float(data.get("retry_after", 0)),
                    )
                if isinstance(data, list) and data:
                    return data, os.path.getmtime(CACHE_FILE), 0.0
        except Exception as e:
            log.warning("Could not read disk cache: %s", e)
    return [], 0.0, 0.0


def _save_disk_cache(
    events: list[dict],
    fetched_at: Optional[float] = None,
    retry_after: Optional[float] = None,
) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "fetched_at": (
                        _in_memory_cache["timestamp"]
                        if fetched_at is None else fetched_at
                    ),
                    "retry_after": (
                        _in_memory_cache.get("retry_after", 0)
                        if retry_after is None else retry_after
                    ),
                    "events": events,
                },
                f,
                indent=2,
            )
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


def _record_consensus_snapshots(
    events: list[dict],
    captured_at: Optional[datetime] = None,
) -> None:
    """Persist changed USD calendar consensus and update the latest row with actuals."""
    from database import ConsensusSnapshot, SessionLocal

    captured_at = captured_at or datetime.now(timezone.utc).replace(tzinfo=None)
    if captured_at.tzinfo is not None:
        captured_at = captured_at.astimezone(timezone.utc).replace(tzinfo=None)

    db = SessionLocal()
    try:
        for event in events:
            if event.get("currency", "").upper() != "USD":
                continue
            event_code = event.get("event_code")
            release_time = event.get("release_time_utc")
            forecast = event.get("forecast")
            previous = event.get("previous")
            if (
                not event_code
                or not release_time
                or not any(isinstance(value, (int, float)) for value in (forecast, previous))
            ):
                continue
            try:
                release_at = datetime.fromisoformat(
                    str(release_time).replace("Z", "+00:00")
                )
            except ValueError:
                log.warning("Skipping consensus snapshot with invalid release time: %s", release_time)
                continue
            if release_at.tzinfo is not None:
                release_at = release_at.astimezone(timezone.utc).replace(tzinfo=None)

            rows = (
                db.query(ConsensusSnapshot)
                .filter_by(event_code=event_code, release_time_utc=release_time)
                .order_by(ConsensusSnapshot.captured_at.desc(), ConsensusSnapshot.id.desc())
                .all()
            )
            latest = rows[0] if rows else None
            actual = event.get("actual")
            explicit_revision = event.get("previous_revised")
            data_as_of = event.get("data_as_of")
            if isinstance(data_as_of, str):
                try:
                    data_as_of = datetime.fromisoformat(
                        data_as_of.replace("Z", "+00:00")
                    )
                except ValueError:
                    log.warning(
                        "Invalid consensus data_as_of for %s/%s: %s",
                        event_code, release_time, data_as_of,
                    )
                    data_as_of = None
            if data_as_of is not None and data_as_of.tzinfo is not None:
                data_as_of = data_as_of.astimezone(timezone.utc).replace(tzinfo=None)
            data_as_of = data_as_of or captured_at
            if latest is not None and actual is not None:
                if latest.actual is None:
                    latest.actual = actual
                    latest.actual_first_seen_at = captured_at
                    latest.actual_source = event.get("source") or "unknown"
                if explicit_revision is not None:
                    latest.previous_revised = explicit_revision
                elif previous is not None and previous != latest.previous:
                    latest.previous_revised = previous

            if release_at <= captured_at:
                continue

            consensus_changed = latest is None or (
                latest.forecast != forecast or latest.previous != previous
            )
            final_pre_release = (
                release_at - timedelta(minutes=10) <= captured_at < release_at
                and not any(
                    release_at - timedelta(minutes=10)
                    <= row.captured_at < release_at
                    for row in rows
                )
            )
            if not consensus_changed and not final_pre_release:
                continue

            previous_changed = latest is not None and latest.previous != previous
            db.add(ConsensusSnapshot(
                event_code=event_code,
                release_time_utc=release_time,
                captured_at=captured_at,
                data_as_of=data_as_of,
                forecast=forecast,
                previous=previous,
                previous_revised=(
                    explicit_revision
                    if explicit_revision is not None
                    else previous if previous_changed else None
                ),
                actual=actual,
                actual_first_seen_at=captured_at if actual is not None else None,
                actual_source=(
                    (event.get("source") or "unknown")
                    if actual is not None else None
                ),
                source=event.get("source") or "forex_factory",
            ))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _with_cache_provenance(
    events: list[dict],
    source: str,
    data_as_of: float,
) -> list[dict]:
    data_time = datetime.fromtimestamp(data_as_of, timezone.utc).replace(tzinfo=None)
    return [
        dict(event, source=source, data_as_of=data_time.isoformat())
        for event in events
    ]


def _has_unreleased_numeric_usd_event(events: list[dict], now: float) -> bool:
    now_utc = datetime.fromtimestamp(now, timezone.utc).replace(tzinfo=None)
    candidates = []
    for event in events:
        if event.get("currency", "").upper() != "USD":
            continue
        if not any(
            isinstance(event.get(field), (int, float))
            and not isinstance(event.get(field), bool)
            for field in ("forecast", "previous")
        ):
            continue
        release_time = event.get("release_time_utc")
        if not release_time:
            continue
        try:
            release_at = datetime.fromisoformat(
                str(release_time).replace("Z", "+00:00")
            )
        except ValueError:
            continue
        if release_at.tzinfo is not None:
            release_at = release_at.astimezone(timezone.utc).replace(tzinfo=None)
        if (
            release_at - timedelta(minutes=3)
            <= now_utc
            <= release_at + timedelta(minutes=20)
            and event.get("actual") is None
        ):
            candidates.append((event.get("event_code"), release_time))

    if not candidates:
        return False

    from database import ConsensusSnapshot, SessionLocal

    db = SessionLocal()
    try:
        for event_code, release_time in candidates:
            latest = (
                db.query(ConsensusSnapshot)
                .filter_by(event_code=event_code, release_time_utc=release_time)
                .order_by(ConsensusSnapshot.captured_at.desc(), ConsensusSnapshot.id.desc())
                .first()
            )
            if latest is None or latest.actual is None:
                return True
        return False
    finally:
        db.close()


def _cache_ttl_seconds(events: list[dict], now: float) -> int:
    if _has_unreleased_numeric_usd_event(events, now):
        return RELEASE_CACHE_TTL_SECONDS
    return CACHE_TTL_SECONDS


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

    memory_events = _in_memory_cache["events"]
    memory_fetched_at = _in_memory_cache["timestamp"]
    memory_retry_after = _in_memory_cache.get("retry_after", 0)
    disk_events, disk_fetched_at, disk_retry_after = _load_disk_cache()
    if memory_events and memory_fetched_at >= disk_fetched_at:
        cached_events = memory_events
        cached_fetched_at = memory_fetched_at
    else:
        cached_events = disk_events
        cached_fetched_at = disk_fetched_at
    retry_after = max(memory_retry_after, disk_retry_after)
    _in_memory_cache["retry_after"] = retry_after

    if now < retry_after:
        if cached_events:
            fallback = _with_cache_provenance(
                cached_events, "fallback", cached_fetched_at
            )
            _record_consensus_snapshots(fallback)
            return fallback
        return []

    # Serve cached data according to the release-sensitive TTL.
    if (
        not force_refresh
        and memory_events
        and now - memory_fetched_at < _cache_ttl_seconds(memory_events, now)
    ):
        cached = _with_cache_provenance(memory_events, "cache", memory_fetched_at)
        _record_consensus_snapshots(cached)
        return cached

    if (
        not force_refresh
        and disk_events
        and 0 <= now - disk_fetched_at < _cache_ttl_seconds(disk_events, now)
    ):
        _in_memory_cache = {
            "timestamp": disk_fetched_at,
            "events": disk_events,
            "retry_after": disk_retry_after,
        }
        cached = _with_cache_provenance(disk_events, "cache", disk_fetched_at)
        _record_consensus_snapshots(cached)
        return cached

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
    _disk_actual_index: dict[str, float] = {}
    for d in disk_events:
        if d.get("actual") is not None:
            key = f"{d.get('event_name','')}||{d.get('release_time_utc','')}"
            _disk_actual_index[key] = d["actual"]

    # Try fetching both week URLs; stop on 429 (rate-limited).
    raw_events: list[dict] = []
    fetch_succeeded = False
    rate_limited = False

    urls_to_fetch = (
        FF_URLS[:1] if _has_unreleased_numeric_usd_event(cached_events, now)
        else FF_URLS
    )
    for url in urls_to_fetch:
        try:
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 429:
                rate_limited = True
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
                rate_limited = True
                log.warning("Forex Factory 429 — falling back to disk cache")
                break
            log.warning("Forex Factory HTTP error %s: %s", url, e)
        except Exception as e:
            log.warning("Forex Factory fetch error %s: %s", url, e)

    if rate_limited:
        retry_after = now + RATE_LIMIT_BACKOFF_SECONDS
        _in_memory_cache["retry_after"] = retry_after
        _save_disk_cache(
            cached_events,
            fetched_at=cached_fetched_at,
            retry_after=retry_after,
        )

    # Fall back to disk cache if live fetch failed or was rate-limited
    if not fetch_succeeded or not raw_events:
        fallback = cached_events
        if fallback:
            log.info(
                "Calendar using cache fallback: %d events "
                "(FF unavailable or rate-limited)", len(fallback),
            )
            _in_memory_cache = {
                "timestamp": cached_fetched_at,
                "events": fallback,
                "retry_after": retry_after,
            }
            fallback_result = _with_cache_provenance(
                fallback, "fallback", cached_fetched_at
            )
            _record_consensus_snapshots(fallback_result)
            return fallback_result
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

    data_as_of = datetime.fromtimestamp(now, timezone.utc).replace(tzinfo=None)
    data_as_of_string = data_as_of.isoformat()
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
            "previous_revised": _parse_num(
                ev.get("previous_revised", ev.get("previousRevised"))
            ),
            "actual":           actual_val,
            "impact":           impact_raw.upper(),
            "source":           "forex_factory",
            "data_as_of":       data_as_of_string,
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
        _in_memory_cache = {
            "timestamp": now,
            "events": results,
            "retry_after": 0,
        }
        _save_disk_cache(results, fetched_at=now, retry_after=0)
    else:
        # Parsed successfully but 0 results survived filtering — use cache
        fallback = disk_events or _in_memory_cache["events"]
        if fallback:
            log.warning(
                "Calendar parse yielded 0 results despite %d raw events — "
                "using %d cached events", len(deduped), len(fallback),
            )
            fallback_fetched_at = disk_fetched_at if disk_events else memory_fetched_at
            _in_memory_cache = {
                "timestamp": fallback_fetched_at,
                "events": fallback,
                "retry_after": retry_after,
            }
            fallback_result = _with_cache_provenance(
                fallback, "fallback", fallback_fetched_at
            )
            _record_consensus_snapshots(fallback_result)
            return fallback_result

    live_results = _with_cache_provenance(results, "forex_factory", now)
    _record_consensus_snapshots(live_results)
    return live_results


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
        _record_consensus_snapshots(events)
        _save_disk_cache(
            events,
            fetched_at=_in_memory_cache["timestamp"],
            retry_after=_in_memory_cache.get("retry_after", 0),
        )
        log.info(
            "Recorded actual for %s (%s): %s",
            event_code or event_name,
            currency or "any",
            actual,
        )
    return updated
