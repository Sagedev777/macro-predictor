"""
database.py — SQLite database setup using SQLAlchemy.

Tables:
  - indicator_snapshots: raw pulled values for each leading indicator
  - predictions: composite score + confidence for each upcoming event
  - releases: actual released numbers from Forex Factory / FRED
  - alert_logs: records sent telegram alerts to prevent duplicate notifications
"""

from sqlalchemy import (
    create_engine, Column, Integer, Float, String, DateTime, Boolean, Text,
    inspect, text,
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

Base = declarative_base()
engine = create_engine("sqlite:///macro_predictor.db", echo=False)
SessionLocal = sessionmaker(bind=engine)


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
    __tablename__ = "predictions"

    id                  = Column(Integer, primary_key=True, autoincrement=True)
    created_at          = Column(DateTime, default=datetime.utcnow)
    event_code          = Column(String(20), nullable=False)  # NFP, CPI, etc.
    event_display_name  = Column(String(100))
    release_time_utc    = Column(String(50), nullable=True)
    composite_score     = Column(Float)
    lean_direction      = Column(String(10))  # BEAT, MISS, INLINE
    confidence_pct      = Column(Float)
    indicator_breakdown = Column(Text)
    forecast            = Column(Float, nullable=True)
    previous            = Column(Float, nullable=True)
    actual              = Column(Float, nullable=True)
    surprise            = Column(Float, nullable=True)
    was_correct         = Column(Boolean, nullable=True)
    actual_surprise     = Column(Float, nullable=True)
    is_sample           = Column(Boolean, nullable=False, default=False)


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
    alert_type       = Column(String(20))  # PRE_RELEASE, POST_RELEASE


def init_db():
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        prediction_columns = {
            column["name"] for column in inspect(engine).get_columns("predictions")
        }
        if "is_sample" not in prediction_columns:
            connection.execute(
                text("ALTER TABLE predictions ADD COLUMN is_sample BOOLEAN NOT NULL DEFAULT 0")
            )
    _mark_legacy_sample_history()


_SAMPLE_HISTORY_SIGNATURES = {
    ("NFP", "BEAT", 76.5, 165.0, 216.0, True),
    ("CPI", "BEAT", 72.0, 3.1, 3.2, True),
    ("CORE_CPI", "MISS", 64.0, 3.8, 3.7, True),
    ("PPI", "BEAT", 68.0, 0.2, 0.3, True),
    ("JOBLESS_CLAIMS", "MISS", 74.0, 222.0, 215.0, True),
    ("UNEMPLOYMENT_RATE", "INLINE", 52.0, 4.1, 4.2, False),
    ("RETAIL_SALES", "BEAT", 70.0, 0.3, 0.4, True),
    ("CONSUMER_CONFIDENCE", "BEAT", 67.5, 99.0, 100.3, True),
}


def _mark_legacy_sample_history():
    """Hide the complete legacy demo batch from reported accuracy without deleting it."""
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
            signature = (
                row.event_code,
                row.lean_direction,
                row.confidence_pct,
                row.forecast,
                row.actual,
                row.was_correct,
            )
            if signature in _SAMPLE_HISTORY_SIGNATURES:
                row.is_sample = True
        db.commit()
    finally:
        db.close()


def is_pre_release_prediction(prediction: Prediction) -> bool:
    """Return whether a prediction is linked to, and predates, its release."""
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
