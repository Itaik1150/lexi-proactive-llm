"""
Notification timing for the study (docs/REVIEW.md D20, decided 12 Nov: option 1).

Both proactive conditions use the SAME rule: every participant gets their own independent random
times inside the experiment's daily window, at least MIN_GAP_MINUTES apart. Nothing about the
participant (activity, memory, condition) influences the times, so only the content of the
notification differs between the Standard and the Affective group.

The times are drawn once a day per participant (and again for the rest of the day after a restart),
registered as one-off jobs, and stored in `notification_plans` so the analysis can show that timing
did not differ between the groups.
"""
from __future__ import annotations

import random
from datetime import datetime
from typing import Iterable, List, Optional

MIN_GAP_MINUTES = 120  # between two notifications of the same participant on the same day


def to_minutes(hhmm: str) -> int:
    h, m = str(hhmm).strip().split(":")
    h, m = int(h), int(m)
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"not a time of day: {hhmm}")
    return h * 60 + m


def to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def draw_times(start: int, end: int, count: int, rng=random, min_gap: int = MIN_GAP_MINUTES,
               not_before: Optional[int] = None) -> List[int]:
    """
    `count` random minutes-of-the-day in [start, end) (or [not_before, end) if later), sorted and at
    least `min_gap` apart. Every allowed arrangement is equally likely: draw `count` points in the
    window shortened by the gaps, sort them, and add the gaps back. If the window is too short for
    the gap, the gap shrinks so that all `count` times still fit.
    """
    low = max(start, not_before) if not_before is not None else start
    span = end - low
    if count <= 0 or span <= 0:
        return []
    gap = min_gap if (count - 1) * min_gap < span else span // count if count > 1 else 0
    free = span - (count - 1) * gap
    points = sorted(rng.uniform(0, free) for _ in range(count))
    return [min(end - 1, int(low + p + i * gap)) for i, p in enumerate(points)]


def plan_for_participant(windows: Iterable[dict], rng=random, now_minutes: Optional[int] = None,
                         already_sent: int = 0) -> List[str]:
    """
    The participant's times for one day, as "HH:MM". `windows` are the experiment's random windows
    ({"start", "end", "count"}). After a restart (`now_minutes` given) only future times are drawn,
    and no more than the day's total minus what was already sent.
    """
    times: List[int] = []
    total = 0
    for w in windows:
        try:
            start, end = to_minutes(w["start"]), to_minutes(w["end"])
        except (KeyError, ValueError):
            continue
        count = max(1, int(w.get("count") or 1))
        total += count
        times += draw_times(start, end, count, rng, not_before=now_minutes)
    times.sort()
    if now_minutes is not None:
        times = times[: max(0, total - already_sent)]
    return [to_hhmm(t) for t in times]


def plan_document(experiment_id: str, user_id: str, day: datetime, times: List[str], replanned: bool) -> dict:
    """What is stored in `notification_plans` for one participant and one day."""
    return {
        "experiment_id": experiment_id,
        "user_id": user_id,
        "date": day.strftime("%Y-%m-%d"),
        "times": times,
        "rule": f"random in window, min gap {MIN_GAP_MINUTES} min",
        "replanned_after_restart": replanned,
        "created_at": datetime.utcnow(),
    }
