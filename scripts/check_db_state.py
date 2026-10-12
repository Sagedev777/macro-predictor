"""Check actual DB tables and row counts."""
import sqlite3
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

conn = sqlite3.connect('macro_predictor.db')
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = cur.fetchall()
print('Existing tables:')
for t in tables:
    name = t[0]
    cur.execute(f'SELECT COUNT(*) FROM "{name}"')
    count = cur.fetchone()[0]
    print(f'  {name}: {count} rows')

print()
print('--- Checking for GoldForecast data ---')
target_tables = ['gold_forecast', 'GoldForecast', 'gold_forecasts']
for tname in target_tables:
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{tname}"')
        count = cur.fetchone()[0]
        print(f'  Found: {tname} with {count} rows')
        if count > 0:
            cur.execute(f'SELECT * FROM "{tname}" LIMIT 3')
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            for row in rows:
                print(dict(zip(cols, row)))
    except sqlite3.OperationalError as e:
        pass  # table doesn't exist

conn.close()
