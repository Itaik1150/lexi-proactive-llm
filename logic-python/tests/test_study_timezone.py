"""I5 (docs/REVIEW.md): one study time zone, UK time, used for every clock time of the study."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SERVICE_ACCOUNT_JSON_CONTENT", "{}")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from services import memory_pipeline, schedule_utils


class StudyTimeZone(unittest.TestCase):
    def test_the_study_runs_on_uk_time(self):
        self.assertEqual(schedule_utils.STUDY_TIMEZONE, "Europe/London")

    def test_the_study_window_is_working_hours_plus_two(self):
        self.assertEqual(schedule_utils.STUDY_WINDOW, {"start": "09:00", "end": "19:00", "count": 2})

    def test_no_other_time_zone_is_hard_coded_in_the_engine(self):
        root = os.path.join(os.path.dirname(__file__), "..")
        for name in ("scheduler.py", os.path.join("services", "research_service.py"),
                     os.path.join("services", "memory_pipeline.py"), os.path.join("heuristics", "affective.py"),
                     os.path.join("services", "engine_config.py")):
            with open(os.path.join(root, name), encoding="utf-8") as f:
                self.assertNotIn("Jerusalem", f.read(), name)

    def test_a_late_evening_message_in_british_summer_time_belongs_to_the_uk_day(self):
        # 23:30 UTC on 1 July is 00:30 on 2 July in Britain (BST)
        msgs = [{"role": "user", "content": "hi", "createdAt": datetime(2026, 7, 1, 23, 30, tzinfo=timezone.utc)}]
        date = memory_pipeline.conversation_date(msgs, datetime(2026, 7, 2, tzinfo=timezone.utc))
        self.assertEqual(date.date().isoformat(), "2026-07-02")

    def test_in_winter_uk_time_equals_utc(self):
        msgs = [{"role": "user", "content": "hi", "createdAt": datetime(2026, 11, 12, 23, 30, tzinfo=timezone.utc)}]
        date = memory_pipeline.conversation_date(msgs, datetime(2026, 11, 13, tzinfo=timezone.utc))
        self.assertEqual(date.date().isoformat(), "2026-11-12")

    def test_the_dashboard_is_told_the_time_zone_and_window(self):
        from services import engine_config
        timing = engine_config.build()["timing"]
        self.assertEqual(timing["timezone"], "Europe/London")
        self.assertEqual(timing["study_window"]["start"], "09:00")


if __name__ == "__main__":
    unittest.main()
