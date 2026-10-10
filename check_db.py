from database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
tables = db.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
print("Tables:")
for t in tables:
    name = t[0]
    count = db.execute(text("SELECT COUNT(*) FROM [" + name + "]")).scalar()
    print("  " + name + ": " + str(count) + " rows")
db.close()
