import os
import sys
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import price_data

print("Testing price_data.fetch_ohlc for XAUUSD:")
df = price_data.fetch_ohlc("XAUUSD", interval="1min", bars=50)
if df is not None and not df.empty:
    print(f"Success! Fetched {len(df)} candles.")
    print(f"Columns: {df.columns.tolist()}")
    print(f"Index type: {type(df.index)}")
    print(f"Earliest candle: {df.index.min()} | Latest candle: {df.index.max()}")
    print("Latest 3 candles:")
    print(df.tail(3))
else:
    print("fetch_ohlc returned None or empty DataFrame.")
