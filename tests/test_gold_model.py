import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database
import gold_model


class GoldModelTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.engine = create_engine(
            "sqlite:///%s" % (Path(self.temp_dir.name) / "gold-test.db").as_posix()
        )
        database.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_threshold_uses_only_prior_same_family_returns(self):
        label, threshold = gold_model.classify_gold_return(0.15, [0.1, 0.3])
        self.assertEqual(label, "BULLISH")
        self.assertAlmostEqual(threshold, 0.1)
        self.assertEqual(gold_model.classify_gold_return(-0.1, [0.1, 0.3])[0], "BEARISH")
        self.assertEqual(gold_model.classify_gold_return(0.05, [0.1, 0.3])[0], "NEUTRAL")
        self.assertEqual(gold_model.classify_gold_return(0.5, [])[0], None)

    def test_release_moment_id_uses_normalized_time_and_constituent_event_codes(self):
        first = database.stable_release_moment_id(
            "2026-01-02T13:30:00Z",
            ["UNRATE", "NFP", "UNRATE"],
        )
        same_moment = database.stable_release_moment_id(
            "2026-01-02T08:30:00-05:00",
            ["NFP", "UNRATE"],
        )
        different_events = database.stable_release_moment_id(
            "2026-01-02T13:30:00Z",
            ["NFP"],
        )

        self.assertEqual(first, same_moment)
        self.assertNotEqual(first, different_events)

    def test_cot_requires_a_fresh_report_captured_before_prediction_time(self):
        db = self.sessions()
        try:
            as_of = datetime(2026, 6, 10, tzinfo=timezone.utc)
            fresh = database.CotSnapshot(
                report_date="2026-06-02",
                captured_at=datetime(2026, 6, 5),
                currency="XAU",
                net_long=100,
                open_interest=1000,
                net_long_pct=0.1,
                positioning="LONG",
            )
            future = database.CotSnapshot(
                report_date="2026-06-09",
                captured_at=datetime(2026, 6, 11),
                currency="XAU",
                net_long=200,
                open_interest=1000,
                net_long_pct=0.2,
                positioning="LONG",
            )
            stale = database.CotSnapshot(
                report_date="2026-05-01",
                captured_at=datetime(2026, 5, 2),
                currency="XAU",
                net_long=300,
                open_interest=1000,
                net_long_pct=0.3,
                positioning="LONG",
            )
            db.add_all([fresh, future, stale])
            db.commit()

            self.assertEqual(gold_model._latest_cot(db, "XAU", as_of).id, fresh.id)
            self.assertIsNone(
                gold_model._latest_cot(
                    db, "XAU", datetime(2026, 5, 20, tzinfo=timezone.utc)
                )
            )
        finally:
            db.close()

    def test_forecast_is_one_immutable_row_per_release_and_keeps_missing_values_missing(self):
        db = self.sessions()
        try:
            now = datetime(2026, 1, 1, tzinfo=timezone.utc)
            events = [{
                "event_code": "NFP",
                "event_name": "Nonfarm Payrolls",
                "currency": "USD",
                "release_time_utc": "2026-01-02T13:30:00Z",
                "forecast": 250.0,
                "previous": 220.0,
            }]

            def add_mock_market(_captured_at, snapshot):
                snapshot["gold_options_implied_volatility"] = {
                    "value": None,
                    "source": "CME gold options",
                    "observed_at": None,
                    "published_at": None,
                    "captured_at": now.isoformat(),
                    "status": "provider_not_integrated",
                }

            with patch.object(
                gold_model,
                "_add_gold_market_features",
                side_effect=add_mock_market,
            ):
                first = gold_model.create_gold_forecast(db, events, now=now)
                events[0]["forecast"] = 999.0
                second = gold_model.create_gold_forecast(db, events, now=now)

            row = db.query(database.GoldForecast).one()
            snapshot = json.loads(row.feature_snapshot)
            model_features = json.loads(row.model_features)
            self.assertEqual(first, second)
            self.assertEqual(row.event_family, "nfp")
            self.assertEqual(json.loads(row.event_codes_json), ["NFP"])
            self.assertEqual(
                snapshot["consensus_nfp_forecast"]["status"],
                "missing_stored_snapshot",
            )
            self.assertIsNone(snapshot["consensus_nfp_forecast"]["value"])
            self.assertEqual(model_features["available_consensus_nfp_forecast"], 0.0)
            self.assertNotIn("consensus_nfp_forecast", model_features)
            self.assertEqual(
                snapshot["gold_options_implied_volatility"]["status"],
                "provider_not_integrated",
            )
            self.assertEqual(row.n_trained, 0)
            self.assertIsNone(row.probabilities_json)
        finally:
            db.close()

    def test_gold_outcome_stores_horizons_excursions_and_training_only_threshold(self):
        db = self.sessions()
        try:
            release = datetime(2026, 1, 2, 13, 30, tzinfo=timezone.utc)
            previous_release = release - timedelta(days=30)
            db.add(database.GoldForecast(
                release_time_utc=previous_release.isoformat().replace("+00:00", "Z"),
                event_family="nfp",
                event_codes_json='["NFP"]',
                event_names_json='["Nonfarm Payrolls"]',
                created_at=(previous_release - timedelta(hours=1)).replace(tzinfo=None),
                feature_snapshot="{}",
                model_features='{"event_family_nfp": 1.0}',
                outcome_status="ok",
                gold_change_5m_pct=0.2,
                outcome_recorded_at=(previous_release + timedelta(minutes=65)).replace(tzinfo=None),
            ))
            db.add(database.GoldForecast(
                release_time_utc=release.isoformat().replace("+00:00", "Z"),
                event_family="nfp",
                event_codes_json='["NFP"]',
                event_names_json='["Nonfarm Payrolls"]',
                created_at=(release - timedelta(hours=1)).replace(tzinfo=None),
                feature_snapshot="{}",
                model_features='{"event_family_nfp": 1.0}',
                forecast_direction="BULLISH",
            ))
            db.commit()

            timestamps = pd.date_range(
                start=release.replace(tzinfo=None) - timedelta(minutes=1),
                end=release.replace(tzinfo=None) + timedelta(minutes=30),
                freq="min",
            )
            closes = [2000.0] * len(timestamps)
            for i, timestamp in enumerate(timestamps):
                if timestamp >= release.replace(tzinfo=None) + timedelta(minutes=1):
                    closes[i] = 2002.0
                if timestamp >= release.replace(tzinfo=None) + timedelta(minutes=5):
                    closes[i] = 2010.0
                if timestamp >= release.replace(tzinfo=None) + timedelta(minutes=15):
                    closes[i] = 2008.0
                if timestamp >= release.replace(tzinfo=None) + timedelta(minutes=30):
                    closes[i] = 2006.0
            candles = pd.DataFrame(
                {
                    "close": closes,
                    "high": [2020.0 if timestamp == release.replace(tzinfo=None) + timedelta(minutes=2)
                             else close + 1.0 for timestamp, close in zip(timestamps, closes)],
                    "low": [1990.0 if timestamp == release.replace(tzinfo=None) + timedelta(minutes=3)
                            else close - 1.0 for timestamp, close in zip(timestamps, closes)],
                },
                index=timestamps,
            )

            self.assertTrue(gold_model.record_gold_outcome(
                db, release.isoformat().replace("+00:00", "Z"), candles
            ))
            row = db.query(database.GoldForecast).filter_by(
                release_time_utc=release.isoformat().replace("+00:00", "Z")
            ).one()
            self.assertAlmostEqual(row.gold_change_1m_pct, 0.1)
            self.assertAlmostEqual(row.gold_change_5m_pct, 0.5)
            self.assertAlmostEqual(row.gold_change_15m_pct, 0.4)
            self.assertAlmostEqual(row.gold_change_30m_pct, 0.3)
            self.assertAlmostEqual(row.max_up_5m_pct, 1.0)
            self.assertAlmostEqual(row.max_down_5m_pct, -0.5)
            self.assertAlmostEqual(row.max_favorable_5m_pct, 1.0)
            self.assertAlmostEqual(row.max_adverse_5m_pct, 0.5)
            self.assertEqual(row.outcome_label, "BULLISH")
            self.assertAlmostEqual(row.outcome_threshold_pct, 0.1)
            self.assertFalse(gold_model.record_gold_outcome(
                db, release.isoformat().replace("+00:00", "Z"), candles
            ))
        finally:
            db.close()

    def test_training_counts_each_release_once_and_excludes_future_outcomes(self):
        db = self.sessions()
        try:
            origin = datetime(2026, 1, 1, tzinfo=timezone.utc)
            for index, value in enumerate((0.2, -0.4, 0.6, 0.0)):
                release = origin + timedelta(days=index * 30)
                db.add(database.GoldForecast(
                    release_time_utc=release.isoformat().replace("+00:00", "Z"),
                    event_family="cpi",
                    event_codes_json='["CPI"]',
                    event_names_json='["CPI"]',
                    created_at=(release - timedelta(hours=1)).replace(tzinfo=None),
                    feature_snapshot="{}",
                    model_features='{"event_family_cpi": 1.0}',
                    gold_change_5m_pct=value,
                    outcome_recorded_at=(release + timedelta(minutes=65)).replace(tzinfo=None),
                    outcome_status="ok",
                ))
            future_release = origin + timedelta(days=365)
            db.add(database.GoldForecast(
                release_time_utc=future_release.isoformat().replace("+00:00", "Z"),
                event_family="cpi",
                event_codes_json='["CPI"]',
                event_names_json='["CPI"]',
                created_at=(origin + timedelta(days=10)).replace(tzinfo=None),
                feature_snapshot="{}",
                model_features='{"event_family_cpi": 1.0}',
                gold_change_5m_pct=0.8,
                outcome_recorded_at=(origin + timedelta(days=11)).replace(tzinfo=None),
                outcome_status="ok",
            ))
            db.commit()
            samples = gold_model._labeled_training_rows(
                db, datetime(2026, 6, 15, tzinfo=timezone.utc)
            )
            self.assertEqual(len(samples), 3)
            self.assertTrue(all(len(features) > 0 for features, _label in samples))
        finally:
            db.close()

    def test_forecast_probabilities_are_generated_from_prior_gold_labels(self):
        db = self.sessions()
        try:
            now = datetime(2026, 7, 1, tzinfo=timezone.utc)
            moves = (0.2, -0.2, 0.0, 0.4, -0.4, 0.1, -0.1, 0.0, 0.5, -0.5, 0.05, -0.05, 0.3)
            for index, move in enumerate(moves):
                release = datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index * 30)
                db.add(database.GoldForecast(
                    release_time_utc=release.isoformat().replace("+00:00", "Z"),
                    event_family="nfp",
                    event_codes_json='["NFP"]',
                    event_names_json='["Nonfarm Payrolls"]',
                    created_at=(release - timedelta(hours=1)).replace(tzinfo=None),
                    feature_snapshot="{}",
                    model_features=json.dumps({
                        "event_family_nfp": 1.0,
                        "consensus_surprise_expectation": float(index % 2),
                    }),
                    gold_change_5m_pct=move,
                    outcome_recorded_at=(release + timedelta(minutes=65)).replace(tzinfo=None),
                    outcome_status="ok",
                ))
            db.commit()

            def add_mock_market(_captured_at, snapshot):
                snapshot["gold_realized_volatility_30m"] = {
                    "value": 0.2,
                    "source": "test candles",
                    "observed_at": now.isoformat(),
                    "published_at": None,
                    "captured_at": now.isoformat(),
                    "status": "available",
                }

            with patch.object(
                gold_model,
                "_add_gold_market_features",
                side_effect=add_mock_market,
            ):
                result = gold_model.create_gold_forecast(
                    db,
                    [{
                        "event_code": "NFP",
                        "event_name": "Nonfarm Payrolls",
                        "currency": "USD",
                        "release_time_utc": "2026-08-01T12:30:00Z",
                        "forecast": 200.0,
                    }],
                    now=now,
                )

            self.assertEqual(result["status"], "provisional")
            self.assertEqual(result["n_trained"], 12)
            self.assertEqual(
                set(result["probabilities"]),
                {"bullish", "bearish", "neutral"},
            )
            self.assertAlmostEqual(sum(result["probabilities"].values()), 1.0)
            self.assertEqual(result["training_class_counts"].keys(), {
                "BULLISH", "BEARISH", "NEUTRAL"
            })
            self.assertEqual(result["out_of_sample_performance"]["overall"]["n"], 0)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
