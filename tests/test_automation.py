import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from curator.automation import exclusive_run, mature_trip_data, next_weekly_run


class AutomationTests(unittest.TestCase):
    def test_settle_window_keeps_recent_trip_pending(self):
        data = {"trips": [
            {"trip_id": "old", "last_away_anchor": "2024-01-01T00:00:00+00:00"},
            {"trip_id": "recent", "last_away_anchor": "2024-01-09T00:00:00+00:00"},
        ]}
        result = mature_trip_data(
            data,
            now=datetime(2024, 1, 10, tzinfo=timezone.utc),
            settle_hours=72,
        )
        self.assertEqual([trip["trip_id"] for trip in result["trips"]], ["old"])
        self.assertEqual(result["automation"]["pending_trip_ids"], ["recent"])

    def test_weekly_schedule_moves_to_next_week_after_time_passes(self):
        sunday_after = datetime(2024, 1, 7, 7, 0, tzinfo=timezone.utc)
        result = next_weekly_run(sunday_after, weekday=6, hour=6, minute=0)
        self.assertEqual(result, datetime(2024, 1, 14, 6, 0, tzinfo=timezone.utc))

    def test_lock_rejects_overlapping_run(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / "worker.lock"
            with exclusive_run(lock):
                with self.assertRaisesRegex(RuntimeError, "already running"):
                    with exclusive_run(lock):
                        pass
            self.assertFalse(lock.exists())


if __name__ == "__main__":
    unittest.main()
