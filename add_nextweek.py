"""
Manually seed next-week events into the disk cache.
FF won't publish nextweek.json until Sunday/Monday — this bridges the gap.
These will be overwritten automatically once FF publishes the real feed.
"""
import json
from datetime import datetime

CACHE_FILE = "calendar_cache.json"

# Next week events (Oct 5-10 2026), UTC times
NEXT_WEEK = [
    {
        "event_code": "ISM_SERVICES",
        "event_name": "ISM Services PMI",
        "display_name": "ISM Services PMI",
        "currency": "USD",
        "release_time_utc": "2026-10-05T14:00:00-04:00",
        "forecast": 55.1,
        "previous": 55.4,
        "actual": None,
        "impact": "MEDIUM",
        "is_simultaneous": False,
        "simultaneous_event_codes": "",
        "simultaneous_event_names": "",
        "prediction": None,
    },
    {
        "event_code": "FOMC_MINUTES",
        "event_name": "FOMC Meeting Minutes",
        "display_name": "FOMC Meeting Minutes",
        "currency": "USD",
        "release_time_utc": "2026-10-07T18:00:00-04:00",
        "forecast": None,
        "previous": None,
        "actual": None,
        "impact": "HIGH",
        "is_simultaneous": False,
        "simultaneous_event_codes": "",
        "simultaneous_event_names": "",
        "prediction": None,
    },
    {
        "event_code": "JOBLESS_CLAIMS",
        "event_name": "Unemployment Claims",
        "display_name": "Weekly Initial Jobless Claims",
        "currency": "USD",
        "release_time_utc": "2026-10-08T12:30:00-04:00",
        "forecast": 200.0,
        "previous": 197.0,
        "actual": None,
        "impact": "MEDIUM",
        "is_simultaneous": False,
        "simultaneous_event_codes": "",
        "simultaneous_event_names": "",
        "prediction": None,
    },
    {
        "event_code": "CONSUMER_CONFIDENCE",
        "event_name": "Prelim UoM Consumer Sentiment",
        "display_name": "Consumer Confidence & Sentiment",
        "currency": "USD",
        "release_time_utc": "2026-10-09T14:00:00-04:00",
        "forecast": 47.6,
        "previous": 48.1,
        "actual": None,
        "impact": "MEDIUM",
        "is_simultaneous": True,
        "simultaneous_event_codes": "UOM_INFLATION",
        "simultaneous_event_names": "Prelim UoM Inflation Expectations",
        "prediction": None,
    },
    {
        "event_code": "UOM_INFLATION",
        "event_name": "Prelim UoM Inflation Expectations",
        "display_name": "Prelim UoM Inflation Expectations",
        "currency": "USD",
        "release_time_utc": "2026-10-09T14:00:00-04:00",
        "forecast": None,
        "previous": 4.6,
        "actual": None,
        "impact": "MEDIUM",
        "is_simultaneous": True,
        "simultaneous_event_codes": "CONSUMER_CONFIDENCE",
        "simultaneous_event_names": "Prelim UoM Consumer Sentiment",
        "prediction": None,
    },
]

with open(CACHE_FILE, "r", encoding="utf-8") as f:
    events = json.load(f)

# Remove any existing next-week entries (avoid duplicates on re-run)
existing_codes_next = {
    e["event_code"] for e in NEXT_WEEK
}
events = [
    e for e in events
    if not (e.get("event_code") in existing_codes_next and
            e.get("release_time_utc", "")[:10] >= "2026-10-05")
]

events.extend(NEXT_WEEK)

# Sort by release time
events.sort(key=lambda x: x.get("release_time_utc", ""))

with open(CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump(events, f, indent=2)

print(f"Cache now has {len(events)} events")
print("\nNext week events added:")
for e in NEXT_WEEK:
    print(f"  {e['release_time_utc'][:10]}  {e['event_name']}  fcst={e['forecast']}")
print("\nRestart the backend to reload.")
