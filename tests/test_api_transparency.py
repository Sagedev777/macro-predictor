"""
Automated tests for MacroPredictor v4 API transparency endpoints:
- GET /api/gold/forecasts (pagination, filtering, search)
- GET /api/gold/forecast/{release_id} (detail, snapshot, training ledger, USD link)
- GET /api/gold/evaluation (walk-forward evaluation metrics)
- GET /api/gold/insights (empirical historical reaction summaries)
- GET /api/gold/activity (model lifecycle timeline)
- GET /api/sources/status (real source health, explicit unintegrated providers)
- GET /api/system/status (scheduler jobs, db metrics, alerts)
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from api import app
from database import (
    GoldForecast,
    GoldModelTraining,
    Prediction,
    AlertLog,
    PeriodicJobRun,
    CotSnapshot,
    SentimentSnapshot,
    PriceReaction,
    SessionLocal,
    init_db,
)


@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()
    db = SessionLocal()
    try:
        # Clear test data
        db.query(GoldForecast).delete()
        db.query(GoldModelTraining).delete()
        db.query(Prediction).delete()
        db.query(AlertLog).delete()
        db.query(PeriodicJobRun).delete()
        db.query(CotSnapshot).delete()
        db.query(SentimentSnapshot).delete()
        db.query(PriceReaction).delete()
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_gold_forecasts_list_and_filters(client):
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        # Create 3 records: one graded employment, one pending cpi, one unavailable gdp
        f1 = GoldForecast(
            release_moment_id="2026-10-01T12:30:00Z_employment",
            release_time_utc="2026-10-01T12:30:00Z",
            event_family="employment",
            event_codes_json=json.dumps(["NFP", "UNEMP"]),
            event_names_json=json.dumps(["Nonfarm Payrolls", "Unemployment Rate"]),
            feature_snapshot=json.dumps({"xauusd_return_1h": {"value": 0.12}}),
            model_features=json.dumps({"f_ret_1h": 0.12}),
            forecast_direction="BULLISH",
            probabilities_json=json.dumps({"BULLISH": 0.65, "BEARISH": 0.20, "NEUTRAL": 0.15}),
            forecast_status="ok",
            outcome_status="ok",
            outcome_label="BULLISH",
            gold_change_5m_pct=0.42,
            outcome_recorded_at=now,
            created_at=now - timedelta(hours=1),
        )
        f2 = GoldForecast(
            release_moment_id="2026-10-02T12:30:00Z_cpi",
            release_time_utc="2026-10-02T12:30:00Z",
            event_family="cpi",
            event_codes_json=json.dumps(["CPI_MOM"]),
            event_names_json=json.dumps(["CPI m/m"]),
            feature_snapshot=json.dumps({"xauusd_return_1h": {"value": -0.05}}),
            model_features=json.dumps({"f_ret_1h": -0.05}),
            forecast_direction="BEARISH",
            probabilities_json=json.dumps({"BULLISH": 0.15, "BEARISH": 0.70, "NEUTRAL": 0.15}),
            forecast_status="ok",
            outcome_status="pending",
            created_at=now - timedelta(minutes=30),
        )
        f3 = GoldForecast(
            release_moment_id="2026-10-03T12:30:00Z_gdp",
            release_time_utc="2026-10-03T12:30:00Z",
            event_family="gdp",
            event_codes_json=json.dumps(["GDP_QOQ"]),
            event_names_json=json.dumps(["GDP q/q"]),
            feature_snapshot=json.dumps({}),
            model_features=json.dumps({}),
            forecast_direction="NEUTRAL",
            forecast_status="degraded",
            outcome_status="unavailable",
            created_at=now - timedelta(minutes=10),
        )
        db.add_all([f1, f2, f3])
        db.commit()
    finally:
        db.close()

    # List all
    res = client.get("/api/gold/forecasts")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert len(data["forecasts"]) == 3

    # Filter by family
    res_fam = client.get("/api/gold/forecasts?event_family=cpi")
    assert res_fam.status_code == 200
    data_fam = res_fam.json()
    assert data_fam["total"] == 1
    assert data_fam["forecasts"][0]["event_family"] == "cpi"

    # Filter by status graded
    res_graded = client.get("/api/gold/forecasts?status=graded")
    assert res_graded.status_code == 200
    data_graded = res_graded.json()
    assert data_graded["total"] == 1
    assert data_graded["forecasts"][0]["release_moment_id"] == "2026-10-01T12:30:00Z_employment"

    # Search
    res_search = client.get("/api/gold/forecasts?search=Nonfarm")
    assert res_search.status_code == 200
    data_search = res_search.json()
    assert data_search["total"] == 1
    assert data_search["forecasts"][0]["event_family"] == "employment"


def test_gold_forecast_detail_endpoint(client):
    db = SessionLocal()
    rel_time = "2026-10-01T12:30:00Z"
    moment_id = f"{rel_time}_employment"
    try:
        now = datetime.now(timezone.utc)
        f1 = GoldForecast(
            release_moment_id=moment_id,
            release_time_utc=rel_time,
            event_family="employment",
            event_codes_json=json.dumps(["NFP"]),
            event_names_json=json.dumps(["Nonfarm Payrolls"]),
            feature_snapshot=json.dumps({"xauusd_return_1h": {"value": 0.2}}),
            model_features=json.dumps({"f_ret_1h": 0.2}),
            forecast_direction="BULLISH",
            probabilities_json=json.dumps({"BULLISH": 0.60, "BEARISH": 0.25, "NEUTRAL": 0.15}),
            forecast_status="ok",
            outcome_status="ok",
            outcome_label="BULLISH",
            gold_change_5m_pct=0.35,
            outcome_recorded_at=now,
            created_at=now,
        )
        t1 = GoldModelTraining(
            release_time_utc=rel_time,
            claimed_at=now - timedelta(minutes=10),
            trained_at=now,
            n_examples=1,
        )
        p1 = Prediction(
            event_code="NFP",
            release_time_utc=rel_time,
            lean_direction="MISS",
            forecast=180.0,
            actual=150.0,
            surprise=-30.0,
            confidence_pct=68.0,
        )
        db.add_all([f1, t1, p1])
        db.commit()
    finally:
        db.close()

    res = client.get(f"/api/gold/forecast/{moment_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["release_moment_id"] == moment_id
    assert data["training_ledger"]["is_trained"] is True
    assert len(data["linked_usd_predictions"]) == 1
    assert data["linked_usd_predictions"][0]["event_code"] == "NFP"
    assert data["linked_usd_predictions"][0]["surprise"] == -30.0


def test_gold_insights_insufficient_and_sufficient_data(client):
    # Insufficient data test (< 3 graded)
    res = client.get("/api/gold/insights")
    assert res.status_code == 200
    data = res.json()
    assert data["has_sufficient_data"] is False
    assert "Insufficient data" in data["message"]

    # Populate 3 graded observations
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        for i, (ret, fam, lbl) in enumerate([
            (0.40, "employment", "BULLISH"),
            (-0.35, "cpi", "BEARISH"),
            (0.10, "employment", "BULLISH"),
        ]):
            rel_time = f"2026-09-0{i+1}T12:30:00Z"
            f = GoldForecast(
                release_moment_id=f"{rel_time}_{fam}",
                release_time_utc=rel_time,
                event_family=fam,
                event_codes_json=json.dumps(["TEST"]),
                event_names_json=json.dumps(["Test Event"]),
                feature_snapshot=json.dumps({}),
                model_features=json.dumps({}),
                forecast_direction=lbl,
                probabilities_json=json.dumps({"BULLISH": 0.5, "BEARISH": 0.3, "NEUTRAL": 0.2}),
                outcome_status="ok",
                outcome_label=lbl,
                gold_change_5m_pct=ret,
                outcome_recorded_at=now,
                actual_release_json=json.dumps([{"actual": 100 + i, "forecast": 100}]),
            )
            db.add(f)
        db.commit()
    finally:
        db.close()

    res2 = client.get("/api/gold/insights")
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["has_sufficient_data"] is True
    assert data2["sample_size"] == 3
    assert "return_distribution" in data2
    assert data2["direction_frequencies"]["counts"]["BULLISH"] == 2
    assert "employment" in data2["by_family"]


def test_gold_evaluation_endpoint(client):
    res = client.get("/api/gold/evaluation")
    assert res.status_code == 200
    data = res.json()
    assert "n_evaluated" in data
    assert "overall" in data
    assert "by_event_family" in data
    assert "note" in data


def test_sources_status_endpoint(client):
    res = client.get("/api/sources/status")
    assert res.status_code == 200
    data = res.json()
    sources = data["sources"]
    names = [s["name"] for s in sources]
    assert "Twelve Data (XAU/USD)" in names
    assert "Forex Factory" in names
    assert "Federal Reserve Economic Data (FRED)" in names
    assert "CFTC COMEX Gold COT" in names
    assert "CME FedWatch" in names
    assert "CME Gold Options Implied Volatility" in names

    # Verify FedWatch and Options IV are explicitly unintegrated
    fedwatch = next(s for s in sources if s["name"] == "CME FedWatch")
    assert fedwatch["status"] == "provider_not_integrated"
    assert fedwatch["is_integrated"] is False

    gold_iv = next(s for s in sources if s["name"] == "CME Gold Options Implied Volatility")
    assert gold_iv["status"] == "provider_not_integrated"
    assert gold_iv["is_integrated"] is False


def test_system_status_endpoint(client):
    res = client.get("/api/system/status")
    assert res.status_code == 200
    data = res.json()
    assert "backend" in data
    assert data["backend"]["mode"] == "USD & XAU/USD Only"
    assert "database" in data
    assert "scheduler" in data
    assert len(data["scheduler"]["jobs"]) >= 3
    job_names = [j["name"] for j in data["scheduler"]["jobs"]]
    assert "auto_alert_job" in job_names
    assert "sentiment_job" in job_names
    assert "cot_job" in job_names
