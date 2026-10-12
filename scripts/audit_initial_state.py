import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from calendar_feed import fetch_upcoming_red_folder_events
import price_data
from database import (
    SessionLocal,
    GoldForecast,
    GoldModelTraining,
    Prediction,
    PriceReaction,
    CotSnapshot,
    SentimentSnapshot,
    RiverModelState,
    init_db,
)
import gold_model

init_db()

td_key = os.getenv('TWELVE_DATA_API_KEY', '').strip()
fred_key = os.getenv('FRED_API_KEY', '').strip()

print(f"TWELVE_DATA_API_KEY present: {bool(td_key)}")
print(f"FRED_API_KEY present: {bool(fred_key)}")

events = fetch_upcoming_red_folder_events()
print(f"Fetched {len(events)} calendar events.")
usd_events = [e for e in events if e.get('currency') == 'USD']
print(f"USD events count: {len(usd_events)}")
for e in usd_events[:15]:
    print(f"  {e.get('release_time_utc')} : {e.get('event_code')} - {e.get('event_name')} [impact={e.get('impact')}] (actual={e.get('actual')})")

db = SessionLocal()
try:
    print("\nDATABASE TABLE COUNTS:")
    print(f"GoldForecast: {db.query(GoldForecast).count()}")
    print(f"GoldModelTraining: {db.query(GoldModelTraining).count()}")
    print(f"Prediction: {db.query(Prediction).count()}")
    print(f"PriceReaction: {db.query(PriceReaction).count()}")
    print(f"CotSnapshot: {db.query(CotSnapshot).count()}")
    print(f"SentimentSnapshot: {db.query(SentimentSnapshot).count()}")
    print(f"RiverModelState: {db.query(RiverModelState).count()}")
finally:
    db.close()
