import unittest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database
import price_data


class PriceReactionRetryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{self.temp_dir.name}/test.db")
        database.Base.metadata.create_all(self.engine)
        self.test_sessions = sessionmaker(bind=self.engine)
        self.session_local_patch = patch.object(
            database, "SessionLocal", self.test_sessions
        )
        self.session_local_patch.start()

    def tearDown(self):
        self.session_local_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_failed_fetch_waits_then_retries_and_grades_after_recovery(self):
        release_time = "2026-10-02T08:30:00Z"
        release_dt = datetime(2026, 10, 2, 8, 30)
        db = self.test_sessions()
        prediction = database.Prediction(
            created_at=release_dt - timedelta(minutes=30),
            event_code="NFP",
            event_display_name="Nonfarm Payrolls",
            release_time_utc=release_time,
            lean_direction="BEAT",
            confidence_pct=70.0,
            currency="USD",
            is_late=False,
            is_sample=False,
        )
        db.add(prediction)
        db.commit()
        prediction_id = prediction.id
        db.close()

        attempts = {}
        def simulated_get(_url, params, timeout):
            symbol = params["symbol"]
            attempts[symbol] = attempts.get(symbol, 0) + 1
            if symbol in ("USD/JPY", "XAU/USD") and attempts[symbol] == 1:
                class FailedResponse:
                    def raise_for_status(self):
                        return None

                    def json(self):
                        return {"status": "error", "message": "simulated outage"}

                return FailedResponse()

            start = release_dt - timedelta(hours=4)
            end = release_dt + timedelta(minutes=65)
            times = pd.date_range(start, end, freq="min")
            if symbol == "USD/JPY":
                times = times[times != release_dt - timedelta(minutes=1)]

            baseline = 100.0
            direction = 1.0 if symbol == "USD/JPY" else -1.0
            values = []
            for timestamp in times:
                close = baseline
                if timestamp >= release_dt + timedelta(minutes=5):
                    close += direction
                values.append({
                    "datetime": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "open": close,
                    "high": close + 0.01,
                    "low": close - 0.01,
                    "close": close,
                })

            class SuccessfulResponse:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"status": "ok", "values": values}

            return SuccessfulResponse()

        def fake_atr(high, low, close, length):
            return pd.Series(0.1, index=close.index)

        with patch.object(price_data.requests, "get", side_effect=simulated_get):
            with patch.object(price_data, "_rate_limit_wait"):
                with patch.object(price_data, "_calculate_atr", side_effect=fake_atr):
                    first = price_data.process_and_grade_event_price_reactions(
                        "NFP", release_time, pred_id=prediction_id
                    )
                    self.assertEqual(first["status"], "unavailable")
                    self.assertEqual(first["graded_predictions"], [])
                    self.assertEqual(attempts["USD/JPY"], 1)
                    self.assertEqual(attempts["EUR/USD"], 1)
                    self.assertEqual(attempts["XAU/USD"], 1)

                    db = self.test_sessions()
                    stored_prediction = db.get(database.Prediction, prediction_id)
                    self.assertIsNone(stored_prediction.price_graded_at)
                    retry_rows = db.query(database.PriceReaction).filter(
                        database.PriceReaction.status == "unavailable"
                    ).all()
                    self.assertEqual(len(retry_rows), 2)
                    self.assertTrue(all(row.attempt_count == 1 for row in retry_rows))
                    db.close()

                    waiting = price_data.fetch_and_record_price_reactions("NFP", release_time)
                    self.assertEqual(waiting["status"], "unavailable")
                    self.assertEqual(attempts["USD/JPY"], 1)
                    self.assertEqual(attempts["XAU/USD"], 1)

                    db = self.test_sessions()
                    retry_rows = db.query(database.PriceReaction).filter(
                        database.PriceReaction.status == "unavailable"
                    ).all()
                    for row in retry_rows:
                        row.last_attempt_at = (
                            datetime.now(timezone.utc).replace(tzinfo=None)
                            - timedelta(minutes=11)
                        )
                    db.commit()
                    db.close()

                    recovered = price_data.process_and_grade_event_price_reactions(
                        "NFP", release_time, pred_id=prediction_id
                    )

        self.assertEqual(recovered["status"], "ok")
        self.assertTrue(recovered["graded_predictions"])
        self.assertEqual(attempts["USD/JPY"], 2)
        self.assertEqual(attempts["XAU/USD"], 2)
        self.assertEqual(recovered["usd_moves"]["15m"], "UP")

        db = self.test_sessions()
        stored_prediction = db.get(database.Prediction, prediction_id)
        self.assertIsNotNone(stored_prediction.price_graded_at)
        self.assertEqual(stored_prediction.result_15m, "CORRECT")
        nearest_candle_row = db.query(database.PriceReaction).filter_by(
            release_time_utc=release_time,
            symbol="USDJPY",
        ).one()
        self.assertEqual(nearest_candle_row.status, "ok")
        self.assertEqual(nearest_candle_row.attempt_count, 2)
        db.close()

    def test_unavailable_symbol_is_limited_to_five_attempts(self):
        release_time = "2026-10-02T08:30:00Z"

        class FailedResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"status": "error", "message": "simulated outage"}

        with patch.object(
            price_data.requests, "get", return_value=FailedResponse()
        ) as mocked_get:
            with patch.object(price_data, "_rate_limit_wait"):
                for attempt_number in range(5):
                    price_data.fetch_and_record_price_reactions("NFP", release_time)
                    if attempt_number < 4:
                        db = self.test_sessions()
                        rows = db.query(database.PriceReaction).all()
                        for row in rows:
                            row.last_attempt_at = (
                                datetime.now(timezone.utc).replace(tzinfo=None)
                                - timedelta(minutes=11)
                            )
                        db.commit()
                        db.close()

                db = self.test_sessions()
                rows = db.query(database.PriceReaction).all()
                for row in rows:
                    row.last_attempt_at = (
                        datetime.now(timezone.utc).replace(tzinfo=None)
                        - timedelta(minutes=11)
                    )
                db.commit()
                db.close()
                price_data.fetch_and_record_price_reactions("NFP", release_time)

        self.assertEqual(mocked_get.call_count, 15)
        db = self.test_sessions()
        rows = db.query(database.PriceReaction).all()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row.attempt_count == 5 for row in rows))
        self.assertTrue(all(row.status == "unavailable" for row in rows))
        db.close()


if __name__ == "__main__":
    unittest.main()
