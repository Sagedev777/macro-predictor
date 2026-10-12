"""
Trigger the real pipeline to:
1. Fetch calendar events and store releases
2. Generate gold forecasts for qualifying events
3. Show current state
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')

import sqlite3
from database import init_db, get_db

# Ensure tables are initialized
init_db()
print("DB initialized.")

# Check schema
conn = sqlite3.connect('macro_predictor.db')
conn.row_factory = sqlite3.Row
cur = conn.cursor()

for table in ['gold_forecasts', 'gold_model_training', 'releases']:
    cur.execute(f"PRAGMA table_info({table})")
    cols = cur.fetchall()
    print(f"\n--- {table} columns ---")
    for c in cols:
        print(f"  {c['name']} ({c['type']})")

conn.close()
