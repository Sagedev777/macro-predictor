import os
import sys
import requests
from datetime import datetime, timezone, timedelta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from dotenv import load_dotenv
load_dotenv()

key = os.getenv("TWELVE_DATA_API_KEY", "").strip()

# Let's test a couple historical timestamps:
# 1. Friday Oct 2, 2026 12:30:00 UTC (typical NFP release time: 8:30 AM ET)
# 2. Thursday Oct 8, 2026 12:30:00 UTC (Initial Jobless Claims)
# 3. Today Oct 12, 2026 earlier: e.g. 11:45:00 UTC
candidates = [
    ("2026-10-12 11:45:00", "2026-10-12 12:20:00", "Today Oct 12 11:45 UTC"),
    ("2026-10-08 12:25:00", "2026-10-08 13:05:00", "Jobless Claims Oct 8 12:30 UTC"),
    ("2026-10-02 12:25:00", "2026-10-02 13:05:00", "NFP Oct 2 12:30 UTC"),
]

for start_s, end_s, desc in candidates:
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": "XAU/USD",
        "interval": "1min",
        "start_date": start_s,
        "end_date": end_s,
        "timezone": "UTC",
        "apikey": key,
    }
    r = requests.get(url, params=params, timeout=10)
    data = r.json()
    status = data.get("status")
    vals = data.get("values", [])
    print(f"Candidate '{desc}': status={status}, count={len(vals)}")
    if vals:
        print(f"  First: {vals[0]['datetime']} close={vals[0]['close']} | Last: {vals[-1]['datetime']} close={vals[-1]['close']}")
    elif "message" in data:
        print(f"  Message: {data['message']}")
