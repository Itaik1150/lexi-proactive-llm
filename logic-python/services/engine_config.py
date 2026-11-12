"""
What the engine REALLY runs, published for the dashboard (docs/REVIEW.md D28, P9).

The prompts, pools and rules of the study are fixed in code so that the protocol prints exactly
what runs. To keep ONE source of truth, the engine writes them to MongoDB when it starts
(`system_config`, document "engine") and the dashboard shows that document read-only. Nothing here
is read back by the engine: changing the document changes nothing.
"""
from __future__ import annotations

from datetime import datetime, timezone

DOC_ID = "engine"


def build() -> dict:
    from heuristics import affective, registry
    from services import memory_pipeline, message_pools, random_schedule, schedule_utils

    return {
        "_id": DOC_ID,
        "published_at": datetime.now(timezone.utc),
        "language": "English only",
        "heuristics": [
            {"name": info.name, "active": info.active, "note": info.note}
            for info in registry.REGISTRY.values()
        ],
        "memory": {
            "who": "every participant of every condition, identically",
            "when": f"after the Finish button or {memory_pipeline.INACTIVITY_MINUTES} minutes without a message; "
                    f"checked every 2 minutes",
            "model": memory_pipeline.DEFAULT_MEMORY_MODEL,
            "temperature": memory_pipeline.TEMPERATURE,
            "max_events_per_conversation": memory_pipeline.MAX_EVENTS,
            "prompt": memory_pipeline.MEMORY_PROMPT,
        },
        "affective_notification": {
            "sources": "event (best unused event: highest score, then most recent; no expiry; each event once) "
                       "-> summary (recent dated notes) -> pool (no notes yet, or the model failed)",
            "event_prompt": affective.EVENT_PROMPT,
            "summary_prompt": affective.SUMMARY_PROMPT,
            "max_words_before_retry": affective.MAX_WORDS,
            "recent_notes_given": affective.RECENT_NOTES,
            "temperature": affective.TEMPERATURE,
            "pool": list(message_pools.AFFECTIVE_POOL),
        },
        "standard_notification": {
            "sources": "fixed pool only: no model, no name, no memory",
            "pool": list(message_pools.STANDARD_POOL),
        },
        "pool_rule": "random; every message once before any repeats; never the same message twice in a row",
        "timing": {
            "rule": "Random window mode: each participant gets their own random times inside the window, "
                    f"at least {random_schedule.MIN_GAP_MINUTES} minutes apart, drawn daily at 00:01 "
                    "(and for the rest of the day after a restart). The same rule for every proactive condition.",
            "min_gap_minutes": random_schedule.MIN_GAP_MINUTES,
            "timezone": schedule_utils.STUDY_TIMEZONE,
            "study_window": dict(schedule_utils.STUDY_WINDOW),
        },
    }


def publish(mongodb_client) -> bool:
    """Store the current configuration. Best effort: the engine runs the same if this fails."""
    try:
        if not mongodb_client.connect():
            return False
        doc = build()
        mongodb_client.db["system_config"].replace_one({"_id": DOC_ID}, doc, upsert=True)
        print("📋 Engine configuration published for the dashboard")
        return True
    except Exception as e:
        print(f"⚠️  Could not publish the engine configuration: {e}")
        return False
    finally:
        try:
            mongodb_client.disconnect()
        except Exception:
            pass
