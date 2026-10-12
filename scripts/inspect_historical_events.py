import os
import sys
import json
import requests
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv()

# 1. Check calendar cache
if os.path.exists("calendar_cache.json"):
    with open("calendar_cache.json", "r") as f:
        data = json.load(f)
    events = data.get("events", [])
    print(f"Total events in calendar_cache.json: {len(events)}")
    usd_with_actual = [e for e in events if e.get("country") == "USD" and e.get("actual")]
    print(f"USD events with actual in cache: {len(usd_with_actual)}")
    for e in usd_with_actual:
        print(f"  {e.get('date')} : {e.get('title')} -> actual={e.get('actual')} forecast={e.get('forecast')} prev={e.get('previous')}")

# 2. Check Twelve Data candle access for XAU/USD
import price_data
td_key = os.getenv("TWELVE_DATA_API_KEY", "").strip()
print(f"\nTesting Twelve Data XAU/USD candles access:")
try:
    # Test fetching recent candles for XAU/USD
    now = datetime.now(timezone.utc)
    # Fetch 1m candles for last 30 minutes
    candles = price_data.get_candles_cached(
        symbol="XAUUSD",
        interval="1min",
        outputsize=30,
    )
    print(f"Twelve Data get_candles_cached returned {len(candles)} candles.")
    if candles:
        print(f"Most recent candle: {candles[0]}")
        print(f"Oldest candle in batch: {candles[-1]}")
except Exception as e:
    print(f"Error fetching candles from Twelve Data: {e}")
