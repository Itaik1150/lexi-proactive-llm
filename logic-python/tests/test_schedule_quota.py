"""
The number of notifications per participant per day is whatever the schedule defines,
and scheduler.py registers exactly that many jobs (docs/REVIEW.md V1, R1).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# scheduler.py refuses to import without Firebase credentials; a dummy value is enough here.
os.environ.setdefault("SERVICE_ACCOUNT_JSON_CONTENT", "{}")

from apscheduler.schedulers.blocking import BlockingScheduler

from services.schedule_utils import FALLBACK_FIRE_TIMES, daily_quota, effective_mode


def W(start="12:00", end="14:00", count=1):
    return {"start": start, "end": end, "count": count}


class DailyQuota(unittest.TestCase):
    def test_exact_counts_distinct_fire_times(self):
        self.assertEqual(daily_quota("exact", ["09:00", "13:00", "20:30"], []), 3)

    def test_exact_treats_8_00_and_08_00_as_one_time(self):
        self.assertEqual(daily_quota("exact", ["8:00", "08:00"], []), 1)

    def test_exact_ignores_invalid_times(self):
        self.assertEqual(daily_quota("exact", ["09:00", "25:00", "abc", ""], []), 1)

    def test_exact_with_nothing_configured_uses_the_scheduler_fallback(self):
        self.assertEqual(daily_quota("exact", [], []), len(FALLBACK_FIRE_TIMES))

    def test_random_sums_counts_over_valid_windows(self):
        self.assertEqual(daily_quota("random", [], [W(count=2), W("16:00", "18:00", 3)]), 5)

    def test_random_skips_malformed_windows_and_defaults_count_to_one(self):
        windows = [W(count=2), {"start": "bad", "end": "14:00", "count": 9}, W("16:00", "18:00", None)]
        self.assertEqual(daily_quota("random", [], windows), 3)

    def test_ai_agent_uses_only_the_first_window_count(self):
        self.assertEqual(daily_quota("ai_agent", [], [W(count=4), W(count=9)]), 4)

    def test_modes_without_windows_fall_back_to_exact_like_the_scheduler(self):
        for mode in ("random", "ai_agent", "something-else", None):
            self.assertEqual(effective_mode(mode, []), "exact")
            self.assertEqual(daily_quota(mode, ["10:00", "11:00"], []), 2)


class SchedulerMatchesQuota(unittest.TestCase):
    """register_jobs() must register exactly as many jobs as the quota allows."""

    def _register(self, **sched):
        import scheduler
        s = BlockingScheduler(timezone="Asia/Jerusalem")
        base = {"experiment_id": "abc123", "allowed_days": [0, 1, 2, 3, 4, 5, 6],
                "mode": "exact", "fire_times": [], "random_windows": []}
        base.update(sched)
        count = scheduler.register_jobs(s, [base])
        return s, count

    def test_exact_registers_one_job_per_distinct_time(self):
        times = ["09:00", "13:00", "20:30"]
        s, count = self._register(mode="exact", fire_times=times)
        self.assertEqual(count, daily_quota("exact", times, []))

    def test_random_registers_one_job_per_notification(self):
        windows = [W(count=2), W("16:00", "18:00", 3)]
        s, count = self._register(mode="random", random_windows=windows)
        self.assertEqual(count, daily_quota("random", [], windows))

    def test_every_job_is_scoped_to_its_experiment(self):
        s, _ = self._register(mode="exact", fire_times=["09:00", "13:00"])
        jobs = s.get_jobs()
        self.assertTrue(jobs)
        for job in jobs:
            self.assertEqual(list(job.args), ["abc123"])


if __name__ == "__main__":
    unittest.main()
