"""
Re-label all seeded GoldForecast outcomes (outcome_label was None because
no prior outcomes existed when each was graded sequentially).
Then run train_gold_outcome for every labeled row.
"""
import sys, os, json, logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING)

from database import init_db, SessionLocal, GoldForecast, GoldModelTraining
from gold_model import classify_gold_return, train_gold_outcome, _gold_trained_moments

init_db()
db = SessionLocal()

# Get all graded rows sorted by release time
rows = (
    db.query(GoldForecast)
    .filter(
        GoldForecast.outcome_recorded_at.isnot(None),
        GoldForecast.gold_change_5m_pct.isnot(None),
    )
    .order_by(GoldForecast.release_time_utc.asc())
    .all()
)

print(f"\nFound {len(rows)} graded GoldForecast rows. Re-labeling...\n")

# Re-label using walk-forward approach (each row sees only earlier same-family priors)
labeled = 0
for row in rows:
    # Gather prior same-family outcomes strictly before this row
    prior = [
        r for r in rows
        if r.event_family == row.event_family
        and r.release_time_utc < row.release_time_utc
        and r.gold_change_5m_pct is not None
    ]
    prior_changes = [float(r.gold_change_5m_pct) for r in prior]

    label, threshold = classify_gold_return(float(row.gold_change_5m_pct), prior_changes)
    old_label = row.outcome_label
    row.outcome_label = label
    row.outcome_threshold_pct = threshold
    db.commit()

    print(f"  {row.release_time_utc}  family={row.event_family:8s}  "
          f"5m={row.gold_change_5m_pct:+.4f}%  "
          f"priors={len(prior_changes)}  "
          f"label: {old_label} -> {label}  threshold={threshold}")
    if label is not None:
        labeled += 1

print(f"\nLabeled: {labeled}/{len(rows)}\n")

db.close()

# Now clear in-memory training set cache and trigger actual training
_gold_trained_moments.clear()

# Also clear any stale GoldModelTraining markers with trained_at=None
db2 = SessionLocal()
stale = db2.query(GoldModelTraining).filter(GoldModelTraining.trained_at.is_(None)).all()
for s in stale:
    db2.delete(s)
db2.commit()
print(f"Cleared {len(stale)} stale GoldModelTraining markers.\n")

# Get fresh labeled rows
rows2 = (
    db2.query(GoldForecast)
    .filter(
        GoldForecast.outcome_recorded_at.isnot(None),
        GoldForecast.outcome_label.isnot(None),
        GoldForecast.gold_change_5m_pct.isnot(None),
    )
    .order_by(GoldForecast.release_time_utc.asc())
    .all()
)
db2.close()

print(f"Training gold model on {len(rows2)} labeled rows...\n")
trained = 0
errors = 0
for row in rows2:
    result = train_gold_outcome(row.release_time_utc)
    if result.get("was_trained"):
        trained += 1
        print(f"  TRAINED {row.release_time_utc}  label={result.get('outcome_label')}  n_trained={result.get('n_trained')}")
    elif result == {}:
        errors += 1
        print(f"  SKIPPED {row.release_time_utc}  (returned empty — check label/features)")
    else:
        print(f"  RESULT  {row.release_time_utc}  {result}")

db3 = SessionLocal()
total_gmt = db3.query(GoldModelTraining).count()
print(f"\nTraining complete: {trained} trained, {errors} empty-result")
print(f"gold_model_training rows in DB: {total_gmt}")

# Show final state of all GoldForecast rows
print("\nFinal GoldForecast state:")
final_rows = db3.query(GoldForecast).order_by(GoldForecast.release_time_utc.asc()).all()
print(f"  {'release_time_utc':35s} {'family':10s} {'5m_pct':10s} {'label':10s} {'n_trained':10s}")
for r in final_rows:
    print(f"  {r.release_time_utc:35s} {(r.event_family or ''):10s} {(str(round(r.gold_change_5m_pct, 4)) if r.gold_change_5m_pct else 'None'):10s} {(r.outcome_label or 'None'):10s} {r.n_trained}")
db3.close()
