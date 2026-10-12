import contextlib
import io
import json
import os
import sqlite3
import sys
import types
import unittest
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import time

import run_tick


class RunTickTests(unittest.TestCase):
    def test_idle_fast_path_skips_heavy_imports_and_finishes_under_one_second(self):
        with TemporaryDirectory() as temp_dir:
            database_path = os.path.join(temp_dir, "idle.db")
            cache_path = os.path.join(temp_dir, "calendar.json")
            now = datetime.now(timezone.utc).replace(tzinfo=None)
            connection = sqlite3.connect(database_path)
            try:
                connection.executescript(
                    "CREATE TABLE predictions (result_15m TEXT, "
                    "price_graded_at TEXT, release_time_utc TEXT);"
                    "CREATE TABLE periodic_job_runs (job_name TEXT PRIMARY KEY, "
                    "last_run_at TEXT);"
                )
                connection.executemany(
                    "INSERT INTO periodic_job_runs (job_name, last_run_at) VALUES (?, ?)",
                    [
                        (name, now.isoformat())
                        for name in (
                            "auto_alert_job",
                            "rate_diff_job",
                            "strength_job",
                            "sentiment_job",
                            "cot_job",
                        )
                    ],
                )
                connection.commit()
            finally:
                connection.close()
            with open(cache_path, "w", encoding="utf-8") as cache_file:
                json.dump({"fetched_at": time.time(), "events": []}, cache_file)

            env = {
                "MACRO_PREDICTOR_DATABASE_URL": f"sqlite:///{database_path}",
                "MACRO_PREDICTOR_CALENDAR_CACHE": cache_path,
            }
            output = io.StringIO()
            with patch.dict(os.environ, env), \
                    patch.dict(sys.modules, {"scheduler": None, "database": None}), \
                    patch.object(run_tick, "_acquire_lock", return_value=io.BytesIO()), \
                    patch("dotenv.load_dotenv"), \
                    contextlib.redirect_stdout(output):
                self.assertTrue(run_tick._should_skip_idle_tick(now))
                exit_code = run_tick.main()
                self.assertEqual(exit_code, 0)
                self.assertIsNone(sys.modules["scheduler"])
                self.assertIsNone(sys.modules["database"])
            printed = output.getvalue().strip()
            self.assertIn("idle fast path", printed)
            self.assertLess(float(printed.rsplit("=", 1)[1][:-1]), 1.0)
            print("idle tick output:", printed)

    def test_tick_initializes_and_runs_from_project_root(self):
        original_cwd = os.getcwd()
        observed_cwd = []
        fake_database = types.ModuleType("database")
        fake_database.init_db = Mock()
        fake_scheduler = types.ModuleType("scheduler")
        fake_scheduler.run_cron_jobs = Mock(
            side_effect=lambda: observed_cwd.append(os.getcwd())
        )
        fake_scheduler.PERIODIC_JOB_CADENCES = {"auto_alert_job": "every minute"}

        try:
            with TemporaryDirectory() as outside_project, \
                    patch.dict(
                        sys.modules,
                        {"database": fake_database, "scheduler": fake_scheduler},
                    ), \
                    patch.object(run_tick, "_acquire_lock", return_value=io.BytesIO()), \
                    patch.object(run_tick, "_should_skip_idle_tick", return_value=False), \
                    patch("dotenv.load_dotenv"):
                os.chdir(outside_project)
                exit_code = run_tick.main()
        finally:
            os.chdir(original_cwd)

        self.assertEqual(exit_code, 0)
        fake_database.init_db.assert_called_once_with()
        fake_scheduler.run_cron_jobs.assert_called_once_with()
        self.assertEqual(observed_cwd, [str(run_tick.PROJECT_ROOT)])
        self.assertNotIn("torch", sys.modules)
        self.assertNotIn("transformers", sys.modules)

    def test_locked_tick_skips_without_running_cycle(self):
        original_cwd = os.getcwd()
        fake_database = types.ModuleType("database")
        fake_database.init_db = Mock()
        fake_scheduler = types.ModuleType("scheduler")
        fake_scheduler.run_cron_jobs = Mock()
        fake_scheduler.PERIODIC_JOB_CADENCES = {"auto_alert_job": "every minute"}

        try:
            with TemporaryDirectory() as outside_project, \
                    patch.dict(
                        sys.modules,
                        {"database": fake_database, "scheduler": fake_scheduler},
                    ), \
                    patch.object(run_tick, "_acquire_lock", return_value=None), \
                    patch("dotenv.load_dotenv"):
                os.chdir(outside_project)
                exit_code = run_tick.main()
        finally:
            os.chdir(original_cwd)

        self.assertEqual(exit_code, 0)
        fake_database.init_db.assert_not_called()
        fake_scheduler.run_cron_jobs.assert_not_called()


if __name__ == "__main__":
    unittest.main()
