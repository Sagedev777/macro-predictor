import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database
import scheduler
import calendar_feed
from sentiment import score_sentiment


class CronIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_engine(f"sqlite:///{self.db_path.as_posix()}")
        database.Base.metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX ux_alert_logs_release_type "
                "ON alert_logs (event_code, release_time_str, alert_type) "
                "WHERE release_time_str IS NOT NULL"
            )
        self.sessions = sessionmaker(bind=self.engine)
        self.session_patch = unittest.mock.patch.object(
            database, "SessionLocal", self.sessions
        )
        self.session_patch.start()
        self.scheduler_session_patch = unittest.mock.patch.object(
            scheduler, "SessionLocal", self.sessions
        )
        self.scheduler_session_patch.start()

    def tearDown(self):
        self.scheduler_session_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_periodic_jobs_run_once_and_persist_last_run(self):
        run_at = datetime(2026, 10, 2, 17, 0)  # Friday, after all UTC slots
        job_names = (
            "rate_diff_job",
            "strength_job",
            "sentiment_job",
            "cot_job",
            "auto_alert_job",
        )
        mocks = [
            unittest.mock.patch.object(scheduler, name)
            for name in (
                "check_and_alert_upcoming",
                "refresh_rate_differentials",
                "refresh_currency_strengths",
                "refresh_sentiment_cycle",
                "refresh_cot_cycle",
            )
        ]
        for mocked in mocks:
            mocked.start()
        try:
            first = scheduler.run_cron_jobs(run_at)
            second = scheduler.run_cron_jobs(run_at)
        finally:
            for mocked in mocks:
                mocked.stop()

        self.assertEqual(set(first), set(job_names))
        self.assertEqual(second, [])
        db = self.sessions()
        try:
            rows = {
                row.job_name: row.last_run_at
                for row in db.query(database.PeriodicJobRun).all()
            }
        finally:
            db.close()
        self.assertEqual(set(rows), set(job_names))
        self.assertTrue(all(value == run_at for value in rows.values()))
        print(
            "periodic job last_run_at:",
            [(name, rows[name].isoformat()) for name in job_names],
        )

    def test_actual_and_price_alerts_are_distinct_and_deduplicated(self):
        prediction = SimpleNamespace(
            event_code="NFP",
            event_display_name="Nonfarm Payrolls",
            release_time_utc="2026-10-02T08:30:00Z",
            lean_direction="BEAT",
            confidence_pct=68,
            result_15m="CORRECT",
            usd_move_15m="UP",
            price_graded_at=datetime.now(),
        )
        response = Mock()
        response.raise_for_status.return_value = None
        db = self.sessions()
        try:
            with patch.object(scheduler, "BOT_TOKEN", "test-token"), \
                    patch.object(scheduler, "CHAT_ID", "test-chat"), \
                    patch.object(
                        scheduler.requests, "post", return_value=response
                    ) as post:
                self.assertTrue(scheduler.send_actual_posted_alert(db, prediction, 250, 200))
                self.assertTrue(scheduler.send_price_result_alert(db, prediction))
                self.assertFalse(scheduler.send_actual_posted_alert(db, prediction, 250, 200))
                self.assertFalse(scheduler.send_price_result_alert(db, prediction))
            self.assertEqual(post.call_count, 2)
            self.assertEqual(
                {row.alert_type for row in db.query(database.AlertLog).all()},
                {"ACTUAL_POSTED", "PRICE_RESULT"},
            )
        finally:
            db.close()

    def test_local_sentiment_word_list_scores_article_counts(self):
        result = score_sentiment([
            "strong jobs growth beat expectations",
            "recession risk weak outlook",
            "markets await the next report",
        ])
        self.assertEqual(result["scored_count"], 3)
        self.assertAlmostEqual(result["bullish_pct"], 1 / 3, places=4)
        self.assertAlmostEqual(result["bearish_pct"], 1 / 3, places=4)
        self.assertAlmostEqual(result["neutral_pct"], 1 / 3, places=4)
        self.assertEqual(result["net_score"], 0)

    def test_training_marker_prevents_duplicate_training_across_processes(self):
        release_dt = datetime.now() - timedelta(minutes=70)
        release_str = release_dt.replace(microsecond=0).isoformat() + "Z"
        db = self.sessions()
        prediction = database.Prediction(
            created_at=release_dt - timedelta(minutes=15),
            event_code="NFP",
            release_time_utc=release_str,
            lean_direction="BEAT",
            confidence_pct=65,
            currency="USD",
            is_sample=False,
            is_late=False,
            result_15m="CORRECT",
            usd_move_15m="UP",
            price_graded_at=release_dt + timedelta(minutes=65),
        )
        db.add(prediction)
        db.flush()
        db.add(database.IndicatorSnapshot(
            fred_series="PREDICTION_INPUTS",
            prediction_id=prediction.id,
            indicator_score=0.6,
            rate_diff_score=0.2,
            cot_score=-0.1,
            sentiment_score=0.3,
        ))
        db.commit()
        db.close()

        code = (
            "from learning import train_release_moment; "
            f"print(train_release_moment({release_str!r}))"
        )
        env = os.environ.copy()
        env["MACRO_PREDICTOR_DATABASE_URL"] = (
            f"sqlite:///{self.db_path.as_posix()}"
        )
        env.pop("PYTHONPATH", None)
        results = []
        for _ in range(2):
            results.append(subprocess.run(
                [sys.executable, "-c", code],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip())

        db = self.sessions()
        try:
            marker = db.get(
                database.ReleaseMomentTraining, (release_str, "USD")
            )
            model = db.query(database.RiverModelState).filter_by(
                currency="USD"
            ).one()
        finally:
            db.close()
        self.assertIsNotNone(marker.trained_at)
        self.assertEqual(marker.n_predictions, 1)
        self.assertEqual(model.n_trained, 1)
        self.assertIn("'n_trained': 1", results[0])
        self.assertEqual(results[1], "{}")
        print(
            "training subprocess outputs:",
            json.dumps(results),
            "persisted n_trained:",
            model.n_trained,
        )

    def test_two_cron_processes_reuse_calendar_disk_cache(self):
        cache_path = Path(self.temp_dir.name) / "calendar-cache.json"
        cache_path.write_text(json.dumps({
            "fetched_at": time.time(),
            "events": [{"impact": "LOW", "event_code": "CACHE_PROBE"}],
        }), encoding="utf-8")
        db = self.sessions()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for job_name in scheduler.PERIODIC_JOB_CADENCES:
            if job_name == "auto_alert_job":
                continue
            db.add(database.PeriodicJobRun(job_name=job_name, last_run_at=now))
        db.commit()
        db.close()

        probe_dir = Path(self.temp_dir.name) / "probe"
        probe_dir.mkdir()
        (probe_dir / "sitecustomize.py").write_text(
            "import importlib.abc, json, os, sys\n"
            "from urllib.parse import urlparse\n"
            "import requests\n"
            "class OptionalNlpBlocker(importlib.abc.MetaPathFinder):\n"
            "    def find_spec(self, fullname, path=None, target=None):\n"
            "        if fullname.split('.')[0] in {'torch', 'transformers'}:\n"
            "            raise ModuleNotFoundError(fullname)\n"
            "sys.meta_path.insert(0, OptionalNlpBlocker())\n"
            "counter = os.environ['HTTP_COUNTER_FILE']\n"
            "def counted(url, *args, **kwargs):\n"
            "    host = urlparse(str(url)).hostname or ''\n"
            "    key = ('forex_factory' if 'faireconomy.media' in host else "
            "'fred' if 'stlouisfed.org' in host else "
            "'twelve_data' if 'twelvedata.com' in host else 'other')\n"
            "    counts = json.loads(open(counter, encoding='utf-8').read())\n"
            "    counts[key] = counts.get(key, 0) + 1\n"
            "    open(counter, 'w', encoding='utf-8').write(json.dumps(counts))\n"
            "    raise RuntimeError('network disabled by probe')\n"
            "requests.get = counted\n",
            encoding="utf-8",
        )
        counts_per_run = []
        outputs = []
        env = os.environ.copy()
        env["MACRO_PREDICTOR_DATABASE_URL"] = (
            f"sqlite:///{self.db_path.as_posix()}"
        )
        env["MACRO_PREDICTOR_CALENDAR_CACHE"] = str(cache_path)
        env["HTTP_COUNTER_FILE"] = str(Path(self.temp_dir.name) / "counts.json")
        env["PYTHONPATH"] = str(probe_dir)
        counter_path = Path(env["HTTP_COUNTER_FILE"])
        for run_number in (1, 2):
            counter_path.write_text(
                json.dumps({
                    "forex_factory": 0,
                    "fred": 0,
                    "twelve_data": 0,
                }),
                encoding="utf-8",
            )
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve().parents[1] / "run_tick.py")],
                cwd=self.temp_dir.name,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            outputs.append(result.stdout.strip())
            counts_per_run.append(json.loads(counter_path.read_text(encoding="utf-8")))
            self.assertIn("cycle complete", result.stdout)
            if run_number == 1:
                db = self.sessions()
                try:
                    auto_cycle = db.get(database.PeriodicJobRun, "auto_alert_job")
                    self.assertIsNotNone(auto_cycle)
                    auto_cycle.last_run_at = (
                        datetime.now(timezone.utc).replace(tzinfo=None)
                        - timedelta(minutes=1)
                    )
                    db.commit()
                finally:
                    db.close()

        self.assertEqual(
            counts_per_run,
            [
                {"forex_factory": 0, "fred": 0, "twelve_data": 0},
                {"forex_factory": 0, "fred": 0, "twelve_data": 0},
            ],
        )
        print("run_tick outputs:", json.dumps(outputs))
        print("HTTP requests (Forex Factory / FRED / Twelve Data):", counts_per_run)

    def test_expired_calendar_disk_cache_triggers_live_refresh_attempt(self):
        cache_path = Path(self.temp_dir.name) / "expired-calendar.json"
        cache_path.write_text(json.dumps({
            "fetched_at": time.time() - calendar_feed.CACHE_TTL_SECONDS - 1,
            "events": [{"impact": "LOW", "event_code": "STALE"}],
        }), encoding="utf-8")
        with patch.object(calendar_feed, "CACHE_FILE", str(cache_path)), \
                patch.object(
                    calendar_feed, "_in_memory_cache", {"timestamp": 0, "events": []}
                ), \
                patch.object(
                    calendar_feed.requests,
                    "get",
                    side_effect=calendar_feed.requests.ConnectionError("offline probe"),
                ) as mocked_get:
            result = calendar_feed.fetch_calendar_events()
        self.assertEqual(result[0]["event_code"], "STALE")
        self.assertEqual(mocked_get.call_count, len(calendar_feed.FF_URLS))
        print(
            "expired calendar cache: refreshed after TTL; "
            f"attempted {mocked_get.call_count} Forex Factory URLs"
        )

    def test_sqlite_wal_and_busy_timeout_allow_concurrent_process_writes(self):
        database_path = Path(self.temp_dir.name) / "concurrent-writes.db"
        writer_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
        database.Base.metadata.create_all(writer_engine)
        writer_engine.dispose()

        writer_code = (
            "from database import SessionLocal, CurrencyStrength, engine; "
            "connection=engine.raw_connection(); "
            "print(connection.execute('PRAGMA journal_mode').fetchone()[0], "
            "connection.execute('PRAGMA busy_timeout').fetchone()[0]); "
            "connection.close(); "
            "db=SessionLocal(); "
            "[(db.add(CurrencyStrength(currency='USD', strength_score=i)), "
            "db.commit()) for i in range(40)]; "
            "db.close()"
        )
        env = os.environ.copy()
        env["MACRO_PREDICTOR_DATABASE_URL"] = (
            f"sqlite:///{database_path.as_posix()}"
        )
        env.pop("PYTHONPATH", None)
        processes = [
            subprocess.Popen(
                [sys.executable, "-c", writer_code],
                cwd=Path(__file__).resolve().parents[1],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            for _ in range(2)
        ]
        outputs = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr)
            outputs.append(stdout.splitlines()[0])
        self.assertEqual(outputs, ["wal 30000", "wal 30000"])

        verification_engine = create_engine(
            f"sqlite:///{database_path.as_posix()}"
        )
        try:
            with verification_engine.connect() as connection:
                mode = connection.exec_driver_sql("PRAGMA journal_mode").scalar()
                row_count = connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM currency_strengths"
                ).scalar()
        finally:
            verification_engine.dispose()
        self.assertEqual(mode.lower(), "wal")
        self.assertEqual(row_count, 80)
        print(
            "concurrent SQLite writers: ",
            f"processes={len(processes)}; journal_mode={mode}; "
            f"busy_timeout_ms=30000; rows={row_count}; process_pragmas={outputs}",
        )


if __name__ == "__main__":
    unittest.main()
