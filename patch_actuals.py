"""
Patch the disk cache with real actuals from Forex Factory (manually sourced).
Run once to update the cache with known actual values.
"""
import json

CACHE_FILE = "calendar_cache.json"

# Real actuals from FF as of Oct 3 2026
ACTUALS = {
    # event_name → actual value
    "CB Consumer Confidence":           103.3,
    "JOLTS Job Openings":               7.44,
    "CPI m/m":                          0.1,      # AUD
    "CPI y/y":                          2.1,      # AUD
    "Trimmed Mean CPI m/m":             0.1,      # AUD
    "German Prelim CPI m/m":            0.0,
    "Final GDP Price Index q/q":        2.5,
    "Unemployment Claims":              198.0,    # Oct 1 (197K prev, 201K fcst → 198K actual)
    "ISM Manufacturing PMI":            54.5,     # Oct 1 (54.6 prev, 54.8 fcst → 54.5 actual)
    "Average Hourly Earnings m/m":      0.1,      # Oct 2 NFP day
    "Non-Farm Employment Change":       29.0,     # Oct 2 (133K prev, 89K fcst → 29K actual)
    "Unemployment Rate":                4.2,      # Oct 2 (4.1 prev, 4.1 fcst → 4.2 actual)
    "Cash Rate":                        4.35,     # AUD RBA held
    "GDP m/m":                          0.0,      # CAD
    "Tokyo Core CPI y/y":               1.8,      # JPY
    "Core CPI Flash Estimate y/y":      2.7,      # EUR
    "CPI Flash Estimate y/y":           2.2,      # EUR
}

with open(CACHE_FILE, "r", encoding="utf-8") as f:
    events = json.load(f)

patched = 0
for ev in events:
    name = ev.get("event_name", "")
    if name in ACTUALS and ev.get("actual") is None:
        ev["actual"] = ACTUALS[name]
        patched += 1
        print(f"  Patched: {ev.get('release_time_utc','')[:10]}  {name} = {ACTUALS[name]}")

with open(CACHE_FILE, "w", encoding="utf-8") as f:
    json.dump(events, f, indent=2)

print(f"\nPatched {patched} events in {CACHE_FILE}")
print("Restart the backend for the cache to reload.")
