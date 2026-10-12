"""
Tests for scheduler integration with gold reaction outcome grading and River learning.
"""
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import (
    Base,
    GoldForecast,
    GoldModelTraining,
    Prediction,
)
import scheduler


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()
    yield db, TestingSessionLocal
    db.close()


def test_gold_sweep_grades_and_trains_pending_forecast(test_db, monkeypatch):
    db, SessionLocal = test_db
    monkeypatch.setattr("database.SessionLocal", SessionLocal)
    monkeypatch.setattr("scheduler.SessionLocal", SessionLocal)

    rel_time = (datetime.utcnow() - timedelta(minutes=45)).isoformat() + "Z"
    features = {"family_threshold_pct": 0.15, "us_surprise": 0.8}

    forecast = GoldForecast(
        release_moment_id="test-moment-1",
        release_time_utc=rel_time,
        event_family="EMPLOYMENT",
        event_codes_json=json.dumps(["NFP"]),
        event_names_json=json.dumps(["Nonfarm Payrolls"]),
        feature_snapshot=json.dumps(features),
        model_features=json.dumps(features),
        forecast_status="ready",
        forecast_direction="BEARISH",
        outcome_status="pending",
    )
    db.add(forecast)
    db.commit()

    trained_calls = []

    def mock_fetch_and_record_gold(rel_str, force_refresh=False, db=None):
        sess = db or SessionLocal()
        row = sess.query(GoldForecast).filter_by(release_time_utc=rel_str).first()
        if row:
            row.outcome_label = "BEARISH"
            row.gold_change_5m_pct = -0.32
            row.outcome_status = "graded"
            row.outcome_recorded_at = datetime.utcnow()
            sess.commit()
        return True

    def mock_train_gold_outcome(rel_str):
        trained_calls.append(rel_str)
        return {"was_trained": True}

    monkeypatch.setattr("price_data.fetch_and_record_gold_outcome", mock_fetch_and_record_gold)
    monkeypatch.setattr("gold_model.train_gold_outcome", mock_train_gold_outcome)

    graded = scheduler.process_and_grade_gold_outcomes(db=db)
    assert rel_time in graded
    assert rel_time in trained_calls

    db.refresh(forecast)
    assert forecast.outcome_status == "graded"
    assert forecast.outcome_label == "BEARISH"


def test_gold_sweep_skips_recent_releases(test_db, monkeypatch):
    db, SessionLocal = test_db
    monkeypatch.setattr("database.SessionLocal", SessionLocal)
    monkeypatch.setattr("scheduler.SessionLocal", SessionLocal)

    rel_time = (datetime.utcnow() - timedelta(minutes=10)).isoformat() + "Z"
    forecast = GoldForecast(
        release_moment_id="test-moment-recent",
        release_time_utc=rel_time,
        event_family="INFLATION",
        event_codes_json=json.dumps(["CPI"]),
        event_names_json=json.dumps(["CPI MoM"]),
        feature_snapshot=json.dumps({}),
        model_features=json.dumps({}),
        outcome_status="pending",
    )
    db.add(forecast)
    db.commit()

    trained_calls = []
    monkeypatch.setattr("gold_model.train_gold_outcome", lambda r: trained_calls.append(r))

    graded = scheduler.process_and_grade_gold_outcomes(db=db)
    assert graded == []
    assert trained_calls == []


def test_rebuild_models_invokes_both_usd_and_gold(monkeypatch):
    usd_rebuilt = []
    gold_rebuilt = []

    monkeypatch.setattr("learning.rebuild_model_from_history", lambda: usd_rebuilt.append(True) or {"rebuilt": True})
    monkeypatch.setattr("gold_model.rebuild_gold_model_from_history", lambda: gold_rebuilt.append(True) or {"rebuilt": True})

    scheduler._rebuild_models_from_history()
    assert len(usd_rebuilt) == 1
    assert len(gold_rebuilt) == 1
