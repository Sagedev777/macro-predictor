import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import calendar_feed
import database


class ConsensusSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.engine = create_engine(
            f"sqlite:///{(Path(self.temp_dir.name) / 'consensus.db').as_posix()}"
        )
        database.Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine)
        self.session_patch = patch.object(database, "SessionLocal", self.sessions)
        self.session_patch.start()
        self.cache_path = Path(self.temp_dir.name) / "calendar.json"
        self.cache_patch = patch.object(calendar_feed, "CACHE_FILE", str(self.cache_path))
        self.cache_patch.start()
        self.memory_patch = patch.object(
            calendar_feed, "_in_memory_cache", {"timestamp": 0, "events": []}
        )
        self.memory_patch.start()

    def tearDown(self):
        self.memory_patch.stop()
        self.cache_patch.stop()
        self.session_patch.stop()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_fetches_save_changed_consensus_and_actual_to_latest_row(self):
        from database import ConsensusSnapshot

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        release_time = (now + timedelta(hours=2)).replace(microsecond=0)
        release_string = release_time.isoformat() + "Z"
        db = self.sessions()
        try:
            db.add(ConsensusSnapshot(
                event_code="NFP",
                release_time_utc=release_string,
                captured_at=now - timedelta(minutes=5),
                forecast=1.0,
                previous=0.9,
                source="fixture",
            ))
            db.commit()
        finally:
            db.close()

        current = {"forecast": "1.0"}

        def response_for(url, **_kwargs):
            events = []
            if "thisweek" in url:
                events = [{
                    "country": "USD",
                    "impact": "High",
                    "title": "Non-Farm Employment Change",
                    "date": release_string,
                    "forecast": current["forecast"],
                    "previous": "0.9",
                    "actual": "",
                }]
            return SimpleNamespace(
                status_code=200,
                json=lambda: events,
                raise_for_status=lambda: None,
            )

        with patch.object(calendar_feed.requests, "get", side_effect=response_for):
            unchanged = calendar_feed.fetch_calendar_events(force_refresh=True)
            db = self.sessions()
            try:
                self.assertEqual(
                    db.query(ConsensusSnapshot)
                    .filter_by(event_code="NFP", release_time_utc=release_string)
                    .count(),
                    1,
                )
            finally:
                db.close()

            current["forecast"] = "1.2"
            changed = calendar_feed.fetch_calendar_events(force_refresh=True)

        self.assertEqual(unchanged[0]["forecast"], 1.0)
        self.assertEqual(changed[0]["forecast"], 1.2)
        actual_event = dict(changed[0], actual=2.1, previous_revised=1.0)
        calendar_feed._record_consensus_snapshots([actual_event])

        db = self.sessions()
        try:
            rows = (
                db.query(ConsensusSnapshot)
                .filter_by(event_code="NFP", release_time_utc=release_string)
                .order_by(ConsensusSnapshot.captured_at, ConsensusSnapshot.id)
                .all()
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].forecast, 1.0)
            self.assertIsNone(rows[0].actual)
            self.assertEqual(rows[1].forecast, 1.2)
            self.assertEqual(rows[1].actual, 2.1)
            self.assertEqual(rows[1].previous_revised, 1.0)
            self.assertIsNotNone(rows[1].data_as_of)
            print("consensus_snapshots rows:")
            print(
                "event_code | release_time_utc | captured_at | data_as_of | "
                "forecast | previous | previous_revised | actual | source"
            )
            for row in rows:
                print(
                    f"{row.event_code} | {row.release_time_utc} | "
                    f"{row.captured_at.isoformat()} | "
                    f"{row.data_as_of.isoformat() if row.data_as_of else None} | "
                    f"{row.forecast} | {row.previous} | {row.previous_revised} | "
                    f"{row.actual} | {row.source}"
                )
        finally:
            db.close()

    def test_inserts_final_pre_release_row_when_consensus_is_unchanged(self):
        from database import ConsensusSnapshot

        release_time = (
            datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
        )
        release_time = release_time.replace(second=0, microsecond=0)
        first_capture = release_time - timedelta(minutes=20)
        final_capture = release_time - timedelta(minutes=5)
        release_string = release_time.isoformat()
        db = self.sessions()
        try:
            db.add(ConsensusSnapshot(
                event_code="NFP",
                release_time_utc=release_string,
                captured_at=first_capture,
                forecast=1.0,
                previous=0.9,
                source="fixture",
            ))
            db.commit()
        finally:
            db.close()

        calendar_feed._record_consensus_snapshots(
            [{
                "event_code": "NFP",
                "currency": "USD",
                "release_time_utc": release_string,
                "forecast": 1.0,
                "previous": 0.9,
                "source": "fixture",
            }],
            captured_at=final_capture,
        )

        db = self.sessions()
        try:
            rows = (
                db.query(ConsensusSnapshot)
                .filter_by(event_code="NFP", release_time_utc=release_string)
                .order_by(ConsensusSnapshot.captured_at)
                .all()
            )
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[-1].captured_at, final_capture)
        finally:
            db.close()

    def test_429_fallback_uses_cache_fetch_time_and_honors_two_minute_backoff(self):
        from database import ConsensusSnapshot

        base_time = datetime.now(timezone.utc).timestamp()
        release_string = (
            datetime.fromtimestamp(base_time + 3600, timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        cached_event = {
            "event_code": "NFP",
            "event_name": "Non-Farm Employment Change",
            "currency": "USD",
            "release_time_utc": release_string,
            "forecast": 1.0,
            "previous": 0.9,
            "actual": None,
            "impact": "HIGH",
        }
        cache_fetched_at = base_time - 600
        self.cache_path.write_text(json.dumps({
            "fetched_at": cache_fetched_at,
            "retry_after": 0,
            "events": [cached_event],
        }), encoding="utf-8")
        response_429 = SimpleNamespace(status_code=429)
        response_ok = SimpleNamespace(
            status_code=200,
            json=lambda: [{
                "country": "USD",
                "impact": "High",
                "title": "Non-Farm Employment Change",
                "date": release_string,
                "forecast": "1.0",
                "previous": "0.9",
                "actual": "",
            }],
            raise_for_status=lambda: None,
        )
        clock = [base_time]
        request = Mock(side_effect=[response_429, response_ok, response_ok])

        with patch.object(calendar_feed.time, "time", side_effect=lambda: clock[0]), \
                patch.object(calendar_feed.requests, "get", request):
            first = calendar_feed.fetch_calendar_events(force_refresh=True)
            clock[0] += 30
            second = calendar_feed.fetch_calendar_events(force_refresh=True)
            clock[0] += 89
            third = calendar_feed.fetch_calendar_events(force_refresh=True)
            self.assertEqual(request.call_count, 1)
            clock[0] += 1
            recovered = calendar_feed.fetch_calendar_events(force_refresh=True)

        self.assertEqual(first[0]["source"], "fallback")
        self.assertEqual(second[0]["source"], "fallback")
        self.assertEqual(third[0]["source"], "fallback")
        expected_as_of = datetime.fromtimestamp(
            cache_fetched_at, timezone.utc
        ).replace(tzinfo=None)
        self.assertEqual(datetime.fromisoformat(first[0]["data_as_of"]), expected_as_of)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(recovered[0]["source"], "forex_factory")

        db = self.sessions()
        try:
            row = (
                db.query(ConsensusSnapshot)
                .filter_by(event_code="NFP", release_time_utc=release_string)
                .one()
            )
            self.assertEqual(row.source, "fallback")
            self.assertEqual(row.data_as_of, expected_as_of)
            print(
                "429 fallback row: "
                f"{row.event_code} | {row.release_time_utc} | "
                f"captured_at={row.captured_at.isoformat()} | "
                f"data_as_of={row.data_as_of.isoformat()} | "
                f"forecast={row.forecast} | previous={row.previous} | "
                f"previous_revised={row.previous_revised} | actual={row.actual} | "
                f"source={row.source}"
            )
            print(
                "429 backoff requests: 1 through t+119s; "
                f"retry at t+120s; total requests={request.call_count}"
            )
        finally:
            db.close()

    def test_simulated_release_window_request_count_and_hourly_rate(self):
        release_datetime = datetime(2026, 10, 12, 12, 15, tzinfo=timezone.utc)
        release_time = release_datetime.timestamp()
        release_string = release_datetime.isoformat()
        self.cache_path.unlink(missing_ok=True)
        event = {
            "country": "USD",
            "impact": "High",
            "title": "Non-Farm Employment Change",
            "date": release_string,
            "forecast": "1.0",
            "previous": "0.9",
            "actual": "",
        }

        request_offsets = []

        def success_response(url, **_kwargs):
            if "thisweek" in url:
                request_offsets.append((clock[0] - release_time) / 60)
            return SimpleNamespace(
                status_code=200,
                json=lambda: [event],
                raise_for_status=lambda: None,
            )

        clock = [release_time - 15 * 60]
        request = Mock(side_effect=success_response)
        with patch.object(calendar_feed.time, "time", side_effect=lambda: clock[0]), \
                patch.object(calendar_feed.requests, "get", request), \
                patch.object(calendar_feed, "_record_consensus_snapshots"):
            for _ in range(61):
                calendar_feed.fetch_calendar_events()
                clock[0] += 30

        print(f"calendar fetch offsets from release: {request_offsets}")
        expected_offsets = [-15.0] + [step / 2 for step in range(-6, 31)]
        self.assertEqual(request_offsets, expected_offsets)
        self.assertEqual(request.call_count, 76)
        baseline_requests_per_hour = (
            len(calendar_feed.FF_URLS) * 3600 / calendar_feed.CACHE_TTL_SECONDS
        )
        release_window_requests_per_hour = (
            len(calendar_feed.FF_URLS) * 3600
            / calendar_feed.RELEASE_CACHE_TTL_SECONDS
        )
        cron_window_requests_per_hour = len(calendar_feed.FF_URLS) * 60
        print(
            "simulated 30-minute release window: "
            f"{request.call_count} Forex Factory requests "
            f"({request.call_count // len(calendar_feed.FF_URLS)} fetches)"
        )
        print(
            "shared web+cron cache request rate (one refresh stream): "
            f"{baseline_requests_per_hour:.0f}/hour outside release window; "
            f"{cron_window_requests_per_hour:.0f}/hour at cron's 1-minute cadence "
            "during release window; "
            f"{release_window_requests_per_hour:.0f}/hour if requested every 30 seconds"
        )
        print(f"shared cache path: {calendar_feed.CACHE_FILE}")


if __name__ == "__main__":
    unittest.main()
