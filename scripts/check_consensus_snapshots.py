import os
import sys
import json
import requests
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database import SessionLocal, ConsensusSnapshot, init_db
init_db()

db = SessionLocal()
try:
    snaps = db.query(ConsensusSnapshot).all()
    print(f"Total ConsensusSnapshots in DB: {len(snaps)}")
    for s in snaps[:10]:
        print(f"  {s.release_time_utc} | {s.event_code} | fcast={s.forecast} | prev={s.previous} | actual={s.actual}")
finally:
    db.close()
