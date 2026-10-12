import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from sentiment import refresh_all_cot, refresh_all_sentiment
from database import SessionLocal, CotSnapshot, SentimentSnapshot, init_db
init_db()

print("Running refresh_all_cot()...")
cot_results = refresh_all_cot()
print(f"COT results keys: {list(cot_results.keys())}")
for k, v in cot_results.items():
    print(f"  {k}: net_long={v.net_long}, net_long_pct={v.net_long_pct:.4f}, positioning={v.positioning}")

db = SessionLocal()
try:
    cots = db.query(CotSnapshot).all()
    print(f"\nCotSnapshot rows in DB: {len(cots)}")
    for c in cots:
        print(f"  {c.currency} | report_date={c.report_date} | published_at={c.published_at} | net_long={c.net_long} | net_long_pct={c.net_long_pct}")
finally:
    db.close()
