"""Run every due scheduler job once for a cron-driven deployment."""

from __future__ import annotations

import logging
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime, time as datetime_time, timedelta, timezone
from urllib.parse import unquote

PROJECT_ROOT = Path(__file__).resolve().parent
LOCK_PATH = PROJECT_ROOT / ".run_tick.lock"


def _acquire_lock():
    lock_file = LOCK_PATH.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file


def _sqlite_database_path() -> Path | None:
    database_url = os.getenv(
        "MACRO_PREDICTOR_DATABASE_URL", "sqlite:///macro_predictor.db"
    )
    if not database_url.startswith("sqlite:///"):
        return None
    raw_path = unquote(database_url[len("sqlite:///"):])
    if raw_path == ":memory:":
        return None
    path = Path(raw_path)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _calendar_cache_has_nearby_release(now: datetime) -> bool:
    cache_name = os.getenv(
        "MACRO_PREDICTOR_CALENDAR_CACHE", "calendar_cache.json"
    )
    cache_path = Path(cache_name)
    if not cache_path.is_absolute():
        cache_path = PROJECT_ROOT / cache_path
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched_at = float(cache["fetched_at"])
        events = cache["events"]
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return True

    if time.time() - fetched_at >= 1800 or not isinstance(events, list):
        return True
    for event in events:
        if not isinstance(event, dict):
            return True
        release_time = event.get("release_time_utc")
        if not release_time:
            continue
        if not isinstance(release_time, str):
            return True
        try:
            release_dt = datetime.fromisoformat(
                release_time.replace("Z", "+00:00")
            )
        except (TypeError, ValueError):
            return True
        if release_dt.tzinfo is not None:
            release_dt = release_dt.astimezone(timezone.utc).replace(tzinfo=None)
        if timedelta(0) <= release_dt - now <= timedelta(minutes=15):
            return True
    return False


def _periodic_job_is_due(connection: sqlite3.Connection, now: datetime) -> bool:
    try:
        rows = {
            name: datetime.fromisoformat(last_run) if last_run else None
            for name, last_run in connection.execute(
                "SELECT job_name, last_run_at FROM periodic_job_runs"
            )
        }
    except (TypeError, ValueError):
        return True

    last_cycle = rows.get("auto_alert_job")
    if last_cycle is None or (now - last_cycle).total_seconds() >= 55:
        return True

    slots = {
        "rate_diff_job": [datetime.combine(now.date(), datetime_time(6, 0))],
        "strength_job": [datetime.combine(now.date(), datetime_time(7, 0))],
        "sentiment_job": [
            datetime.combine(now.date(), datetime_time(0, 30)),
            datetime.combine(now.date(), datetime_time(12, 30)),
        ],
        "cot_job": (
            [datetime.combine(now.date(), datetime_time(16, 0))]
            if now.weekday() == 4 else []
        ),
    }
    for job_name, run_slots in slots.items():
        last_run = rows.get(job_name)
        if any(now >= slot and (last_run is None or last_run < slot)
               for slot in run_slots):
            return True
    return False


def _should_skip_idle_tick(now: datetime | None = None) -> bool:
    """Check only SQLite and the persistent calendar cache before heavy imports."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    database_path = _sqlite_database_path()
    if database_path is None or not database_path.exists():
        return False
    if _calendar_cache_has_nearby_release(now):
        return False

    try:
        connection = sqlite3.connect(str(database_path), timeout=0.2)
        try:
            tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            required = {"predictions", "periodic_job_runs"}
            if not required.issubset(tables):
                return False
            pending = connection.execute(
                "SELECT release_time_utc FROM predictions "
                "WHERE result_15m IS NULL AND price_graded_at IS NULL "
                "AND release_time_utc IS NOT NULL"
            ).fetchall()
            for (release_time,) in pending:
                try:
                    release_dt = datetime.fromisoformat(
                        release_time.replace("Z", "+00:00")
                    )
                except (AttributeError, ValueError):
                    return False
                if release_dt.tzinfo is not None:
                    release_dt = release_dt.astimezone(timezone.utc).replace(tzinfo=None)
                if (now - release_dt).total_seconds() >= 65 * 60:
                    return False
            return not _periodic_job_is_due(connection, now)
        finally:
            connection.close()
    except sqlite3.Error:
        return False


def main() -> int:
    started_at = time.perf_counter()
    os.chdir(PROJECT_ROOT)
    root_string = str(PROJECT_ROOT)
    if root_string not in sys.path:
        sys.path.insert(0, root_string)

    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
    logging.basicConfig(level=logging.INFO)

    lock_file = _acquire_lock()
    if lock_file is None:
        elapsed = time.perf_counter() - started_at
        print(
            "run_tick: another cycle holds the lock; skipping this run. "
            f"wall_time={elapsed:.3f}s"
        )
        return 0

    try:
        if _should_skip_idle_tick():
            elapsed = time.perf_counter() - started_at
            print(f"run_tick: idle fast path; wall_time={elapsed:.3f}s")
            return 0

        from database import init_db

        init_db()
        from scheduler import PERIODIC_JOB_CADENCES, run_cron_jobs

        print(f"run_tick: processing due jobs from {PROJECT_ROOT}")
        completed = run_cron_jobs()
        print(f"run_tick: completed jobs: {', '.join(completed) if completed else 'none'}")
        print(f"run_tick: job cadences: {PERIODIC_JOB_CADENCES}")
        elapsed = time.perf_counter() - started_at
        print(f"run_tick: busy cycle complete; wall_time={elapsed:.3f}s")
        return 0
    finally:
        lock_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
