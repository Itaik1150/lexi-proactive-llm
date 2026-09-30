"""
Schedule helpers shared by scheduler.py (which registers jobs) and research_service.py
(which enforces the daily quota), so the two can never disagree about how many
notifications a participant should get per day.

The number of notifications per participant per day is defined by the experiment's
schedule, exactly as the admin configured it in the dashboard:

  exact     -> one notification per distinct fire time
  random    -> the sum of `count` over all (valid) random windows
  ai_agent  -> `count` of the first window ("Notifications per user")

There is no separate "daily limit" setting.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple

# Used when an experiment has proactive enabled but no fire times configured.
FALLBACK_FIRE_TIMES = ["13:45", "17:30", "21:15"]


def parse_hhmm(value) -> Optional[Tuple[int, int]]:
    """'8:05' -> (8, 5); returns None for anything that is not a valid 24h HH:MM."""
    try:
        h, m = str(value).split(":")
        h, m = int(h), int(m)
    except (ValueError, AttributeError):
        return None
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h, m
    return None


def valid_windows(random_windows: Optional[Iterable[dict]]) -> List[dict]:
    """Random windows whose start and end both parse as HH:MM (others are skipped by the scheduler)."""
    out = []
    for w in random_windows or []:
        if isinstance(w, dict) and parse_hhmm(w.get("start")) and parse_hhmm(w.get("end")):
            out.append(w)
    return out


def window_count(window: dict) -> int:
    """Notifications configured for one window; at least 1, as the scheduler registers."""
    try:
        return max(1, int(window.get("count") or 1))
    except (TypeError, ValueError):
        return 1


def effective_mode(mode: Optional[str], random_windows: Optional[Iterable[dict]]) -> str:
    """
    The mode the scheduler actually runs. 'ai_agent' and 'random' need at least one
    window; without one the scheduler falls back to exact fire times.
    """
    has_windows = bool(list(random_windows or []))
    if mode == "ai_agent" and has_windows:
        return "ai_agent"
    if mode == "random" and has_windows:
        return "random"
    return "exact"


def distinct_fire_times(fire_times: Optional[Iterable[str]]) -> List[Tuple[int, int]]:
    """Valid, de-duplicated fire times ('8:00' and '08:00' are the same time)."""
    seen = []
    for t in (fire_times or []) or FALLBACK_FIRE_TIMES:
        parsed = parse_hhmm(t)
        if parsed and parsed not in seen:
            seen.append(parsed)
    return seen


def daily_quota(mode: Optional[str], fire_times: Optional[Iterable[str]], random_windows: Optional[Iterable[dict]]) -> int:
    """
    Maximum notifications one participant may receive per day under this schedule.
    Mirrors scheduler.register_jobs: whatever it would register is what is allowed.
    """
    windows = list(random_windows or [])
    m = effective_mode(mode, windows)
    if m == "ai_agent":
        return window_count(windows[0])
    if m == "random":
        return sum(window_count(w) for w in valid_windows(windows))
    return len(distinct_fire_times(fire_times))
