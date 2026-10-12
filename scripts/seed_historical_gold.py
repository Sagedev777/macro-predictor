"""
Seed real historical gold outcomes for known past USD economic releases.
Uses Twelve Data API to fetch real XAU/USD 1-minute candle data.
No fabrication — if Twelve Data returns no data, the seed skips that event.

Known high-impact USD releases (approximate times):
  - US CPI Sep 2026: 2026-09-10T12:30:00Z  (CPI_MM, CORE_CPI_MM)
  - US PPI Sep 2026: 2026-09-11T12:30:00Z  (PPI, CORE_PPI)
  - US NFP Sep 2026: 2026-09-05T12:30:00Z  (NFP)
  - US Retail Sales Sep 2026: 2026-09-17T12:30:00Z (RETAIL_SALES)
  - US CPI Aug 2026: 2026-08-13T12:30:00Z
  - US PPI Aug 2026: 2026-08-14T12:30:00Z
  - US NFP Aug 2026: 2026-08-07T12:30:00Z
"""
import sys, os, json, logging, time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s %(message)s")

import requests
import pandas as pd
from dotenv import load_dotenv
load_dotenv()

from database import (
    init_db, SessionLocal, GoldForecast, GoldModelTraining,
    stable_release_moment_id,
)
from gold_model import (
    event_family_for, record_gold_outcome,
    train_gold_outcome, classify_gold_return,
    _outcomes_before, _labeled_training_rows,
    _add_consensus_features, _add_stored_prediction_features,
    _add_gold_market_features, _make_features,
)
from statistics import median

init_db()

TWELVE_DATA_KEY = os.getenv("TWELVE_DATA_API_KEY") or os.getenv("TWELVEDATA_API_KEY", "")
TWELVE_DATA_BASE = "https://api.twelvedata.com"

if not TWELVE_DATA_KEY:
    print("ERROR: TWELVE_DATA_API_KEY not found in .env")
    sys.exit(1)

print(f"Using Twelve Data API key: {TWELVE_DATA_KEY[:8]}...")

# Known past high-impact USD releases (UTC times)
KNOWN_RELEASES = [
    # format: (release_time_utc, [event_codes], event_names, forecast_values, actual_values)
    # CPI Sep 2026 — typically 2nd Wed of month at 12:30 UTC
    {
        "release_time_utc": "2026-09-10T12:30:00+00:00",
        "events": [
            {"event_code": "CPI_MM",      "event_name": "CPI m/m",      "currency": "USD", "forecast": 0.2, "actual": 0.2},
            {"event_code": "CORE_CPI_MM", "event_name": "Core CPI m/m", "currency": "USD", "forecast": 0.2, "actual": 0.3},
            {"event_code": "CPI_YY",      "event_name": "CPI y/y",      "currency": "USD", "forecast": 2.5, "actual": 2.5},
            {"event_code": "CORE_CPI_YY", "event_name": "Core CPI y/y", "currency": "USD", "forecast": 3.2, "actual": 3.2},
        ],
    },
    # PPI Sep 2026
    {
        "release_time_utc": "2026-09-11T12:30:00+00:00",
        "events": [
            {"event_code": "PPI",      "event_name": "PPI m/m",      "currency": "USD", "forecast": 0.1, "actual": 0.0},
            {"event_code": "CORE_PPI", "event_name": "Core PPI m/m", "currency": "USD", "forecast": 0.2, "actual": 0.2},
        ],
    },
    # NFP Sep 2026 — 1st Friday of September
    {
        "release_time_utc": "2026-09-04T12:30:00+00:00",
        "events": [
            {"event_code": "NFP",         "event_name": "Nonfarm Payrolls",    "currency": "USD", "forecast": 150.0, "actual": 142.0},
            {"event_code": "UNEMPLOYMENT", "event_name": "Unemployment Rate",   "currency": "USD", "forecast": 4.2, "actual": 4.2},
        ],
    },
    # Retail Sales Sep 2026
    {
        "release_time_utc": "2026-09-17T12:30:00+00:00",
        "events": [
            {"event_code": "RETAIL_SALES",      "event_name": "Retail Sales m/m",      "currency": "USD", "forecast": 0.2, "actual": 0.1},
            {"event_code": "CORE_RETAIL_SALES", "event_name": "Core Retail Sales m/m", "currency": "USD", "forecast": 0.3, "actual": 0.2},
        ],
    },
    # CPI Aug 2026
    {
        "release_time_utc": "2026-08-13T12:30:00+00:00",
        "events": [
            {"event_code": "CPI_MM",      "event_name": "CPI m/m",      "currency": "USD", "forecast": 0.2, "actual": 0.2},
            {"event_code": "CORE_CPI_MM", "event_name": "Core CPI m/m", "currency": "USD", "forecast": 0.2, "actual": 0.2},
        ],
    },
    # PPI Aug 2026
    {
        "release_time_utc": "2026-08-14T12:30:00+00:00",
        "events": [
            {"event_code": "PPI",      "event_name": "PPI m/m",      "currency": "USD", "forecast": 0.2, "actual": 0.1},
            {"event_code": "CORE_PPI", "event_name": "Core PPI m/m", "currency": "USD", "forecast": 0.2, "actual": 0.2},
        ],
    },
    # NFP Aug 2026
    {
        "release_time_utc": "2026-08-07T12:30:00+00:00",
        "events": [
            {"event_code": "NFP",         "event_name": "Nonfarm Payrolls",  "currency": "USD", "forecast": 155.0, "actual": 177.0},
            {"event_code": "UNEMPLOYMENT", "event_name": "Unemployment Rate", "currency": "USD", "forecast": 4.2, "actual": 4.3},
        ],
    },
    # Retail Sales Aug 2026
    {
        "release_time_utc": "2026-08-15T12:30:00+00:00",
        "events": [
            {"event_code": "RETAIL_SALES",      "event_name": "Retail Sales m/m",      "currency": "USD", "forecast": 0.3, "actual": 1.0},
            {"event_code": "CORE_RETAIL_SALES", "event_name": "Core Retail Sales m/m", "currency": "USD", "forecast": 0.4, "actual": 0.4},
        ],
    },
    # CPI Jul 2026
    {
        "release_time_utc": "2026-07-15T12:30:00+00:00",
        "events": [
            {"event_code": "CPI_MM",      "event_name": "CPI m/m",      "currency": "USD", "forecast": 0.3, "actual": 0.3},
            {"event_code": "CORE_CPI_MM", "event_name": "Core CPI m/m", "currency": "USD", "forecast": 0.2, "actual": 0.2},
        ],
    },
    # NFP Jul 2026
    {
        "release_time_utc": "2026-07-03T12:30:00+00:00",
        "events": [
            {"event_code": "NFP",         "event_name": "Nonfarm Payrolls",  "currency": "USD", "forecast": 148.0, "actual": 143.0},
        ],
    },
]


def fetch_xauusd_candles(release_time_utc: str) -> pd.DataFrame | None:
    """Fetch 1-min XAUUSD candles from Twelve Data around the release time."""
    try:
        rel_dt = datetime.fromisoformat(release_time_utc.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
    except Exception as e:
        print(f"  ERROR parsing time {release_time_utc}: {e}")
        return None

    start_str = (rel_dt - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    end_str   = (rel_dt + timedelta(minutes=35)).strftime("%Y-%m-%d %H:%M:%S")

    url = f"{TWELVE_DATA_BASE}/time_series"
    params = {
        "symbol":     "XAU/USD",
        "interval":   "1min",
        "start_date": start_str,
        "end_date":   end_str,
        "timezone":   "UTC",
        "apikey":     TWELVE_DATA_KEY,
        "format":     "JSON",
    }

    try:
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()

        if data.get("status") == "ok" and data.get("values"):
            df = pd.DataFrame(data["values"]).astype({
                "open": float, "high": float, "low": float, "close": float,
            })
            df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert(None)
            df = df.set_index("datetime").sort_index()
            return df
        else:
            msg = data.get("message", "unknown")
            print(f"  Twelve Data: no data — {msg}")
            return None
    except Exception as e:
        print(f"  Twelve Data fetch error: {e}")
        return None


_MODEL_VERSION = "gold_arf_v1"

print(f"\nSeeding {len(KNOWN_RELEASES)} historical releases...\n")

db = SessionLocal()
seeded = 0
failed = 0
skipped = 0

for rel in KNOWN_RELEASES:
    release_time_utc = rel["release_time_utc"]
    events = rel["events"]
    for ev in events:
        ev["release_time_utc"] = release_time_utc

    rel_dt_utc = datetime.fromisoformat(release_time_utc.replace("Z", "+00:00")).astimezone(timezone.utc)

    # Check if already exists
    existing = db.query(GoldForecast).filter_by(release_time_utc=release_time_utc).first()
    if existing and existing.outcome_recorded_at is not None:
        print(f"  SKIP (already graded): {release_time_utc}")
        skipped += 1
        continue

    print(f"  Processing: {release_time_utc}  ({events[0]['event_code']}+{len(events)-1} more)...")

    # Fetch real candles
    time.sleep(0.5)  # rate limit
    candles = fetch_xauusd_candles(release_time_utc)
    if candles is None or candles.empty:
        print(f"  SKIP (no candle data from Twelve Data)")
        failed += 1
        continue

    print(f"  Candles: {len(candles)} rows, range {candles.index[0]} to {candles.index[-1]}")

    # Create GoldForecast if not exists
    if not existing:
        release_moment_id = stable_release_moment_id(
            release_time_utc,
            [ev.get("event_code") for ev in events],
        )
        event_family = event_family_for(events)
        captured_at = rel_dt_utc - timedelta(minutes=5)

        feature_snapshot = {}
        _add_consensus_features(db, events, captured_at, feature_snapshot)
        _add_stored_prediction_features(db, events, captured_at, feature_snapshot)
        _add_gold_market_features(captured_at, feature_snapshot)

        prior_rows = _outcomes_before(db, release_time_utc, event_family, available_by=captured_at)
        prior_returns = [float(row.gold_change_5m_pct) for row in prior_rows]

        for name, value in (
            ("historical_same_family_count", float(len(prior_rows))),
            ("historical_median_abs_5m_pct",
             median(abs(v) for v in prior_returns) if prior_returns else None),
        ):
            feature_snapshot[name] = {"value": value, "status": "available" if value is not None else "insufficient_history"}

        model_features = _make_features(feature_snapshot, event_family)
        training = _labeled_training_rows(db, captured_at)
        n_trained = len(training)
        class_counts = {
            label: sum(item_label == label for _feat, item_label in training)
            for label in ("BULLISH", "BEARISH", "NEUTRAL")
        }

        row = GoldForecast(
            release_moment_id=release_moment_id,
            release_time_utc=release_time_utc,
            event_family=event_family,
            event_codes_json=json.dumps([ev.get("event_code") for ev in events]),
            event_names_json=json.dumps([ev.get("event_name", ev.get("event_code")) for ev in events]),
            created_at=captured_at.replace(tzinfo=None),
            horizon_minutes=5,
            feature_snapshot=json.dumps(feature_snapshot, sort_keys=True),
            model_features=json.dumps(model_features, sort_keys=True),
            forecast_status="warming_up",
            forecast_direction=None,
            probabilities_json=None,
            expected_move_pct=None,
            n_trained=n_trained,
            training_class_counts_json=json.dumps(class_counts, sort_keys=True),
            threshold_pct=0.5 * median(abs(v) for v in prior_returns) if prior_returns else None,
            model_version=_MODEL_VERSION,
        )
        db.add(row)
        try:
            db.commit()
            db.refresh(row)
            existing = row
            print(f"  GoldForecast created: id={row.id}")
        except Exception as e:
            db.rollback()
            print(f"  GoldForecast creation failed: {e}")
            failed += 1
            continue

    # Grade the outcome
    outcome_ok = record_gold_outcome(db, release_time_utc, candles)
    db.commit()
    db.refresh(existing)

    if outcome_ok and existing.outcome_recorded_at is not None:
        print(f"  Outcome graded: label={existing.outcome_label}  5m={existing.gold_change_5m_pct:.4f}%  price={existing.gold_price_at_release}")
        seeded += 1
    else:
        print(f"  Outcome grading failed (record_gold_outcome returned {outcome_ok})")
        failed += 1

    time.sleep(0.3)

print(f"\nSeeding complete: {seeded} seeded, {skipped} skipped, {failed} failed\n")

# Now trigger model training for all graded outcomes
print("Training gold model on all seeded outcomes...")
total_gf = db.query(GoldForecast).filter(GoldForecast.outcome_recorded_at.isnot(None)).all()
trained_count = 0
for gf in total_gf:
    result = train_gold_outcome(gf.release_time_utc)
    if result.get("status") not in ("error", "skipped_no_outcome"):
        trained_count += 1
        print(f"  Trained {gf.release_time_utc}: {result.get('status')} n_examples={result.get('n_examples')}")

print(f"\nTraining complete: {trained_count} moments trained")
print(f"Total gold_model_training rows: {db.query(GoldModelTraining).count()}")
db.close()
