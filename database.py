"""
database.py — SQLite database setup using SQLAlchemy.

Tables:
  - indicator_snapshots: raw pulled values for each leading indicator
  - predictions: composite score + confidence for each upcoming event
  - releases: actual released numbers from Forex Factory / FRED
  - alert_logs: records sent telegram alerts to prevent duplicate notifications
"""

from sqlalchemy import (
    create_engine, Column, Integer, Float, String, DateTime, Boolean, Text
)
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime

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
