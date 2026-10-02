"""Diagnostic: trace why cached events are being dropped by calendar_feed.py"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Load cache directly
with open("calendar_cache.json") as f:
    cached = json.load(f)

print(f"Events in cache: {len(cached)}")
print()

# Simulate what fetch_calendar_events() does after loading cache
from calendar_feed import (
    TRACKED_CURRENCIES, TRACKED_IMPACTS,
    _resolve_event_code, _SORTED_EVENT_MAP,
    FF_EVENT_MAP, _COUNTRY_DISAMBIG,
)

print(f"TRACKED_CURRENCIES: {TRACKED_CURRENCIES}")
print(f"TRACKED_IMPACTS:    {TRACKED_IMPACTS}")
print()

# The cache already has pre-processed events (event_code already resolved).
# The bug: fetch_calendar_events() ONLY runs the resolve+filter logic on RAW
# FF feed data, then falls back to disk cache WITHOUT re-filtering.
# But does the API endpoint then also filter? Let's trace the actual call.

# Simulate what _load_disk_cache() + in-memory fallback returns
from calendar_feed import _load_disk_cache, fetch_calendar_events

disk = _load_disk_cache()
print(f"_load_disk_cache() returned: {len(disk)} events")
if disk:
    print("First event from disk:", json.dumps(disk[0], indent=2))
print()

# Now call the actual function - it will get a 429 and fall back to cache
print("Calling fetch_calendar_events()...")
events = fetch_calendar_events(force_refresh=False)
print(f"fetch_calendar_events() returned: {len(events)} events")
print()

if not events:
    print("EMPTY - checking why...")
    # The in-memory cache timestamp is 0 initially, so it will try FF, get 429,
    # then check _in_memory_cache["events"] (empty) then _load_disk_cache()
    from calendar_feed import _in_memory_cache
    print(f"_in_memory_cache timestamp: {_in_memory_cache['timestamp']}")
    print(f"_in_memory_cache events count: {len(_in_memory_cache['events'])}")
else:
    for ev in events[:5]:
        print(f"  [{ev.get('impact')}] {ev.get('currency')} {ev.get('event_name')} @ {ev.get('release_time_utc')}")

print()
# Check what the API endpoint returns
import requests as req
try:
    r = req.get("http://127.0.0.1:8001/api/events", timeout=10)
    data = r.json()
    print(f"/api/events returned: {data.get('count', '?')} events")
    if data.get('events'):
        for ev in data['events'][:3]:
            print(f"  {ev.get('currency')} {ev.get('event_name')}")
    else:
        print("  Empty events list from API")
except Exception as e:
    print(f"API call failed: {e}")
