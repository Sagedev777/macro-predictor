"""
database.py — SQLite database setup using SQLAlchemy.

Tables (original, preserved):
  - indicator_snapshots: raw pulled values for each FRED leading indicator
  - predictions:         composite score + confidence per event (historical ledger)
  - releases:            actual released numbers from Forex Factory / FRED
  - alert_logs:          records sent Telegram alerts to prevent duplicate notifications

Tables (new — multi-currency upgrade):
  - currency_strengths:  per-currency strength score snapshot (all 8 currencies)
  - rate_differentials:  daily yield-spread snapshot per currency vs USD
  - cot_snapshots:       CFTC COT net-long positioning per currency per week
  - sentiment_snapshots: FinBERT-scored sentiment per currency per 48h window
  - river_model_state:   serialised River ARFClassifier state per currency
  - pair_suggestions:    ATR-based pending-order price suggestions per upcoming event
"""

import pickle
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, LargeBinary, String, Text,
    create_engine, inspect, text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()
engine = create_engine("sqlite:///macro_predictor.db", echo=False)
SessionLocal = sessionmaker(bind=engine)


# ── Original tables (unchanged) ───────────────────────────────────────────────

class IndicatorSnapshot(Base):
    __tablename__ = "indicator_snapshots"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    pulled_at       = Column(DateTime, default=datetime.utcnow)
    fred_series     = Column(String(50), nullable=False)
    description     = Column(String(200))
    latest_value    = Column(Float)
    prev_value      = Column(Float)
    trailing_6m_avg = Column(Float)
    trailing_6m_std = Column(Float)
    z_score         = Column(Float)
    signal          = Column(Integer)  # +1 BEAT, -1 MISS, 0 NEUTRAL


class Prediction(Base):
    """
    Historical predictions ledger — never wiped, is_sample flags demo rows.
    New columns added for multi-currency output; old rows have NULL there.
    """
    __tablename__ = "predictions"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    event_code          = Column(String(20), nullable=False)
    event_display_name  = Column(String(100))
    release_time_utc    = Column(String(50), nullable=True)
    composite_score     = Column(Float)
    lean_direction      = Column(String(10))   # BEAT / MISS / INLINE
    confidence_pct      = Column(Float)
    indicator_breakdown = Column(Text)         # JSON
    forecast            = Column(Float, nullable=True)
    previous            = Column(Float, nullable=True)
    actual              = Column(Float, nullable=True)
    surprise            = Column(Float, nullable=True)
    was_correct         = Column(Boolean, nullable=True)
    actual_surprise     = Column(Float, nullable=True)
    is_sample           = Column(Boolean, nullable=False, default=False)
    # ── new columns (NULL for old rows) ──────────────────────────────────────
    currency            = Column(String(3), nullable=True)   # USD / EUR / GBP …
    pair_signals        = Column(Text, nullable=True)        # JSON list of {pair, bias, confidence, order_level}
    model_version       = Column(String(20), nullable=True)  # "river_arf_v1" etc.


class Release(Base):
    __tablename__ = "releases"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    fetched_at       = Column(DateTime, default=datetime.utcnow)
    event_code       = Column(String(20))
    event_name       = Column(String(200))
    release_time_utc = Column(String(50), nullable=True)
    forecast         = Column(Float, nullable=True)
    previous         = Column(Float, nullable=True)
    actual           = Column(Float, nullable=True)
    surprise         = Column(Float, nullable=True)
    surprise_z_score = Column(Float, nullable=True)
    impact           = Column(String(10))


class AlertLog(Base):
    __tablename__ = "alert_logs"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    sent_at          = Column(DateTime, default=datetime.utcnow)
    event_code       = Column(String(20), nullable=False)
    release_time_str = Column(String(50), nullable=True)
    alert_type       = Column(String(20))   # PRE_RELEASE / POST_RELEASE


# ── New tables — multi-currency upgrade ───────────────────────────────────────

class CurrencyStrength(Base):
    """
    Per-currency composite strength score, refreshed each time the scheduler
    runs the full-pipeline update.  Scores are normalised to [-1.0, +1.0].
    """
    __tablename__ = "currency_strengths"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    recorded_at     = Column(DateTime, default=datetime.utcnow)
    currency        = Column(String(3), nullable=False)   # USD, EUR, GBP, JPY, AUD, CHF, CAD, NZD
    strength_score  = Column(Float, nullable=False)       # [-1, +1]
    indicator_score = Column(Float, nullable=True)        # z-score sub-component
    rate_diff_score = Column(Float, nullable=True)        # rate-differential sub-component
    cot_score       = Column(Float, nullable=True)        # COT net-long sub-component
    sentiment_score = Column(Float, nullable=True)        # FinBERT sub-component
    confidence_pct  = Column(Float, nullable=True)        # River model confidence 0–100


class RateDifferential(Base):
    """
    Daily yield-spread snapshot: foreign benchmark yield minus US 10Y Treasury.
    Positive value = foreign yield higher than US → foreign currency tailwind.
    """
    __tablename__ = "rate_differentials"

    id                = Column(Integer, primary_key=True, autoincrement=True)
    recorded_at       = Column(DateTime, default=datetime.utcnow)
    currency          = Column(String(3), nullable=False)
    local_yield_pct   = Column(Float, nullable=True)   # e.g. Bund 10Y, Gilt 10Y
    us_yield_pct      = Column(Float, nullable=True)   # FRED DGS10
    spread_pct        = Column(Float, nullable=True)   # local_yield - us_yield
    spread_3m_avg     = Column(Float, nullable=True)   # trailing 3-month average spread
    trend_direction   = Column(String(10), nullable=True)  # WIDENING / NARROWING / FLAT


class CotSnapshot(Base):
    """
    CFTC COT weekly net-long positioning per currency futures contract.
    net_long = non-commercial longs - non-commercial shorts.
    net_long_pct = net_long / open_interest — normalised positioning.
    """
    __tablename__ = "cot_snapshots"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    report_date     = Column(String(10), nullable=False)   # YYYY-MM-DD
    currency        = Column(String(3), nullable=False)
    net_long        = Column(Integer, nullable=True)       # raw contracts
    open_interest   = Column(Integer, nullable=True)
    net_long_pct    = Column(Float, nullable=True)         # net_long / open_interest
    prev_net_long   = Column(Integer, nullable=True)       # prior week for trend
    positioning     = Column(String(10), nullable=True)    # LONG / SHORT / NEUTRAL


class SentimentSnapshot(Base):
    """
    Aggregated FinBERT sentiment scores per currency over a 48-hour lookback window.
    Scored by sentiment.py, stored here for dashboard display and River feature input.
    """
    __tablename__ = "sentiment_snapshots"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    recorded_at     = Column(DateTime, default=datetime.utcnow)
    currency        = Column(String(3), nullable=False)
    article_count   = Column(Integer, nullable=True)
    bullish_pct     = Column(Float, nullable=True)   # 0.0–1.0
    bearish_pct     = Column(Float, nullable=True)
    neutral_pct     = Column(Float, nullable=True)
    net_score       = Column(Float, nullable=True)   # bullish_pct - bearish_pct → [-1, +1]
    source_breakdown = Column(Text, nullable=True)   # JSON: {gdelt: n, rss: n, cb_speech: n}


class RiverModelState(Base):
    """
    Serialised River ARFClassifier state per currency.
    One row per currency — upserted on every learn_one() call.
    blob stores pickle.dumps(model) so the live model survives restarts.
    """
    __tablename__ = "river_model_state"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    currency        = Column(String(3), nullable=False, unique=True)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    model_blob      = Column(LargeBinary, nullable=False)   # pickle.dumps(river_model)
    n_trained       = Column(Integer, default=0)            # total learn_one() calls
    live_accuracy   = Column(Float, nullable=True)          # river.metrics rolling accuracy
    feature_weights = Column(Text, nullable=True)           # JSON drift snapshot


class PairSuggestion(Base):
    """
    ATR-based pending-order price suggestion per upcoming event per pair.
    Calculated in price_data.py; displayed alongside confidence bar on dashboard.
    """
    __tablename__ = "pair_suggestions"

    id               = Column(Integer, primary_key=True, autoincrement=True)
    calculated_at    = Column(DateTime, default=datetime.utcnow)
    event_code       = Column(String(20), nullable=False)
    release_time_utc = Column(String(50), nullable=True)
    pair             = Column(String(10), nullable=False)   # EURUSD, GBPUSD, XAUUSD …
    bias             = Column(String(5), nullable=True)     # BUY / SELL
    current_price    = Column(Float, nullable=True)
    atr_14           = Column(Float, nullable=True)
    suggested_entry  = Column(Float, nullable=True)         # current_price ± 1×ATR
    suggested_sl     = Column(Float, nullable=True)         # ±1.5×ATR from entry
    suggested_tp     = Column(Float, nullable=True)         # ±2×ATR from entry (1:2 RR)
    confidence_pct   = Column(Float, nullable=True)
    is_reference_only = Column(Boolean, default=True)       # always True — not a guarantee


# ── Migration helper ───────────────────────────────────────────────────────────

def _add_column_if_missing(connection, table: str, column: str, col_def: str):
    """ALTER TABLE … ADD COLUMN if the column doesn't exist yet."""
    existing = {c["name"] for c in inspect(engine).get_columns(table)}
    if column not in existing:
        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}"))


def init_db():
    """
    Create all tables (new and existing) and apply incremental column migrations
    so this is safe to run against the live production database.
    """
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        # ── Predictions: legacy column additions ─────────────────────────────
        _add_column_if_missing(conn, "predictions", "is_sample",    "BOOLEAN NOT NULL DEFAULT 0")
        # ── Predictions: new multi-currency columns ───────────────────────────
        _add_column_if_missing(conn, "predictions", "currency",     "VARCHAR(3)")
        _add_column_if_missing(conn, "predictions", "pair_signals",  "TEXT")
        _add_column_if_missing(conn, "predictions", "model_version", "VARCHAR(20)")

    _mark_legacy_sample_history()


# ── Legacy sample-data detection (unchanged from original) ───────────────────

_SAMPLE_HISTORY_SIGNATURES = {
    ("NFP",               "BEAT",   76.5, 165.0, 216.0,  True),
    ("CPI",               "BEAT",   72.0,   3.1,   3.2,  True),
    ("CORE_CPI",          "MISS",   64.0,   3.8,   3.7,  True),
    ("PPI",               "BEAT",   68.0,   0.2,   0.3,  True),
    ("JOBLESS_CLAIMS",    "MISS",   74.0, 222.0, 215.0,  True),
    ("UNEMPLOYMENT_RATE", "INLINE", 52.0,   4.1,   4.2, False),
    ("RETAIL_SALES",      "BEAT",   70.0,   0.3,   0.4,  True),
    ("CONSUMER_CONFIDENCE","BEAT",  67.5,  99.0, 100.3,  True),
}


def _mark_legacy_sample_history():
    """Hide the complete legacy demo batch from accuracy stats without deleting it."""
    db = SessionLocal()
    try:
        rows = db.query(Prediction).filter(Prediction.was_correct.is_not(None)).all()
        signatures = {
            (
                row.event_code,
                row.lean_direction,
                row.confidence_pct,
                row.forecast,
                row.actual,
                row.was_correct,
            )
            for row in rows
        }
        if not _SAMPLE_HISTORY_SIGNATURES.issubset(signatures):
            return
        for row in rows:
            sig = (
                row.event_code,
                row.lean_direction,
                row.confidence_pct,
                row.forecast,
                row.actual,
                row.was_correct,
            )
            if sig in _SAMPLE_HISTORY_SIGNATURES:
                row.is_sample = True
        db.commit()
    finally:
        db.close()


# ── Convenience helpers ───────────────────────────────────────────────────────

def is_pre_release_prediction(prediction: Prediction) -> bool:
    """Return True if the prediction was made before the release time."""
    if not prediction.release_time_utc or not prediction.created_at:
        return False
    try:
        release_time = datetime.fromisoformat(
            prediction.release_time_utc.replace("Z", "+00:00")
        )
    except ValueError:
        return False
    if release_time.tzinfo is not None:
        release_time = release_time.astimezone(timezone.utc).replace(tzinfo=None)
    return prediction.created_at < release_time


def upsert_river_model(currency: str, model_obj, n_trained: int,
                       live_accuracy: float | None, feature_weights: str | None):
    """
    Serialise and upsert a River model to the river_model_state table.
    Called by learning.py after every learn_one() cycle.
    """
    db = SessionLocal()
    try:
        row = db.query(RiverModelState).filter_by(currency=currency).first()
        blob = pickle.dumps(model_obj)
        if row is None:
            row = RiverModelState(
                currency=currency,
                model_blob=blob,
                n_trained=n_trained,
                live_accuracy=live_accuracy,
                feature_weights=feature_weights,
            )
            db.add(row)
        else:
            row.model_blob      = blob
            row.n_trained       = n_trained
            row.live_accuracy   = live_accuracy
            row.feature_weights = feature_weights
            row.updated_at      = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def load_river_model(currency: str):
    """
    Deserialise and return the River model for a currency, or None if not found.
    Called by learning.py on startup.
    """
    db = SessionLocal()
    try:
        row = db.query(RiverModelState).filter_by(currency=currency).first()
        if row is None:
            return None, 0, None, None
        model = pickle.loads(row.model_blob)
        return model, row.n_trained, row.live_accuracy, row.feature_weights
    finally:
        db.close()
