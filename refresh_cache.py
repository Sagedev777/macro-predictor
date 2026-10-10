import calendar_feed
import json

# Clear both caches to force a real fetch
calendar_feed._in_memory_cache["timestamp"] = 0

events = calendar_feed.fetch_calendar_events(force_refresh=True)

with_actual = [e for e in events if e.get("actual") is not None]
without_actual = [e for e in events if e.get("actual") is None]

print(f"Total events fetched: {len(events)}")
print(f"With actuals: {len(with_actual)}")
print(f"Without actuals: {len(without_actual)}")
print()
print("=== WITH ACTUALS ===")
for e in sorted(with_actual, key=lambda x: x.get("release_time_utc", "")):
    print(f"  {e.get('release_time_utc','')[:10]}  {e.get('event_name',''):<45} actual={e.get('actual')}")
print()
print("=== UPCOMING (no actual yet) ===")
for e in sorted(without_actual, key=lambda x: x.get("release_time_utc", "")):
    print(f"  {e.get('release_time_utc','')[:10]}  {e.get('currency','')}  {e.get('event_name',''):<45} fcst={e.get('forecast')}")
