"""
D20 option 1 (docs/REVIEW.md): independent random times per participant, inside the window,
at least MIN_GAP_MINUTES apart, the same rule for the Standard and the Affective group.
"""
import os
import random
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from services import random_schedule as rsch

START, END = rsch.to_minutes("10:00"), rsch.to_minutes("20:00")


class DrawingTimes(unittest.TestCase):
    def test_times_are_inside_the_window_sorted_and_apart(self):
        rng = random.Random(3)
        for _ in range(2000):
            times = rsch.draw_times(START, END, 2, rng)
            self.assertEqual(len(times), 2)
            self.assertTrue(START <= times[0] < times[1] < END)
            self.assertGreaterEqual(times[1] - times[0], rsch.MIN_GAP_MINUTES - 1)

    def test_never_before_the_window_starts(self):
        """The old jitter jobs could fire up to a whole window BEFORE its start."""
        rng = random.Random(5)
        earliest = min(rsch.draw_times(START, END, 2, rng)[0] for _ in range(3000))
        self.assertGreaterEqual(earliest, START)

    def test_the_whole_window_is_used(self):
        rng = random.Random(11)
        firsts = [rsch.draw_times(START, END, 1, rng)[0] for _ in range(3000)]
        self.assertLess(min(firsts), START + 15)
        self.assertGreater(max(firsts), END - 15)

    def test_a_short_window_shrinks_the_gap_instead_of_dropping_a_notification(self):
        times = rsch.draw_times(rsch.to_minutes("12:00"), rsch.to_minutes("13:00"), 2, random.Random(1))
        self.assertEqual(len(times), 2)
        self.assertGreaterEqual(times[1] - times[0], 30)

    def test_after_a_restart_only_future_times(self):
        now = rsch.to_minutes("15:00")
        rng = random.Random(9)
        for _ in range(500):
            self.assertTrue(all(t >= now for t in rsch.draw_times(START, END, 2, rng, not_before=now)))

    def test_nothing_left_after_the_window(self):
        self.assertEqual(rsch.draw_times(START, END, 2, random.Random(1), not_before=END + 5), [])

    def test_two_participants_get_different_times(self):
        rng = random.Random(2)
        a = rsch.plan_for_participant([{"start": "10:00", "end": "20:00", "count": 2}], rng)
        b = rsch.plan_for_participant([{"start": "10:00", "end": "20:00", "count": 2}], rng)
        self.assertNotEqual(a, b)


class OneParticipantsDay(unittest.TestCase):
    W = [{"start": "10:00", "end": "20:00", "count": 2}]

    def test_two_a_day(self):
        times = rsch.plan_for_participant(self.W, random.Random(4))
        self.assertEqual(len(times), 2)
        self.assertRegex(times[0], r"^\d\d:\d\d$")

    def test_after_a_restart_what_was_already_sent_is_subtracted(self):
        now = rsch.to_minutes("11:00")
        self.assertEqual(len(rsch.plan_for_participant(self.W, random.Random(4), now, already_sent=1)), 1)
        self.assertEqual(rsch.plan_for_participant(self.W, random.Random(4), now, already_sent=2), [])

    def test_a_malformed_window_is_skipped(self):
        self.assertEqual(rsch.plan_for_participant([{"start": "x"}, {"end": "10:00"}], random.Random(1)), [])

    def test_the_plan_is_stored_with_its_rule(self):
        from datetime import datetime
        doc = rsch.plan_document("e1", "u1", datetime(2026, 11, 12), ["11:00", "15:30"], False)
        self.assertEqual((doc["date"], doc["times"]), ("2026-11-12", ["11:00", "15:30"]))
        self.assertIn("min gap", doc["rule"])


class ThePlannerJob(unittest.TestCase):
    """random_daily_planner_job registers one job per participant and time, and stores the plans."""

    def run_planner(self, users, after_restart=False):
        import scheduler as sch
        fake_scheduler = MagicMock()
        rs = MagicMock()
        rs._count_sent_today.return_value = 0
        db = MagicMock()
        mc = MagicMock()
        mc.connect.return_value = True
        mc.db = db
        with patch.object(sch, "_get_experiment_users", return_value=users), \
                patch.object(sch, "get_research_service", return_value=rs), \
                patch.object(sch, "mongodb_client", mc):
            sch.random_daily_planner_job(fake_scheduler, "exp1", [{"start": "00:00", "end": "23:59", "count": 2}],
                                         after_restart=after_restart)
        return fake_scheduler, db

    def test_each_participant_gets_their_own_jobs(self):
        users = [{"_id": "u1", "username": "a"}, {"_id": "u2", "username": "b"}]
        s, db = self.run_planner(users)
        ids = [c.kwargs["id"] for c in s.add_job.call_args_list]
        self.assertTrue(all(i.startswith("rand_timed_exp1_") for i in ids))
        self.assertEqual({i.split("_")[3] for i in ids} <= {"u1", "u2"}, True)
        plans = db["notification_plans"].insert_many.call_args.args[0]
        self.assertEqual([p["user_id"] for p in plans], ["u1", "u2"])
        self.assertEqual([len(p["times"]) for p in plans], [2, 2])
        self.assertNotEqual(plans[0]["times"], plans[1]["times"], "independent draws")
        # only times still ahead today become jobs, never more than two per participant
        self.assertLessEqual(len(ids), 4)

    def test_the_hourly_reload_keeps_these_jobs(self):
        """reload_schedules removes only ids starting with 'proactive_'."""
        s, _ = self.run_planner([{"_id": "u1"}])
        for c in s.add_job.call_args_list:
            self.assertFalse(c.kwargs["id"].startswith("proactive_"))


if __name__ == "__main__":
    unittest.main()
