"""
Affective Heuristic: the Affective Proactive condition (docs/REVIEW.md D13, D14, D16, D19, D25).

Memory is built by the shared pipeline (services/memory_pipeline.py, M1), the same for every
condition. This class only READS it and writes one notification from one of three sources,
logged per send as `message_source`:

  event    the best unused event (highest score, then the most recent; no expiry; each event used
           once) -> the model writes about it (protocol A.3, event prompt)
  summary  no unused event, but earlier conversation notes exist -> the model writes a continuity
           message from the recent dated notes (A.3, summary prompt)
  pool     no notes yet (the first days), or the model failed, or its answer was too long twice
           -> a message from the fixed warm pool (A.5)

The prompts are fixed here so that the protocol prints exactly what runs; the dashboard's message
prompt for this heuristic is ignored (docs/REVIEW.md P9).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from bson import ObjectId as _ObjectId

from heuristics.base_heuristic import BaseHeuristic
from zoneinfo import ZoneInfo

from services import message_pools
from services.schedule_utils import STUDY_TIMEZONE

# ── Protocol appendix A.3. Change it there and here together. ────────────────
_PROMPT_HEAD = "You write one push notification from Lexi, an AI companion, to a participant in a research study.\n\n"

_EVENT_TASK = (
    "Write ONE sentence of at most 15 words, in English. Name the specific event the participant shared, "
    "in their own terms (for example \"your presentation on Friday\"), and gently ask how it went or how "
    "they feel about it.\n\n"
)

_SUMMARY_TASK = (
    "No specific event is available today. Write ONE warm sentence of at most 15 words that shows you "
    "remember the participant's recent days, using the background summaries, and invites them to talk. "
    "Do not invent anything that is not in the summaries.\n\n"
)

_PROMPT_RULES = (
    "Rules:\n"
    "- Mild feeling wording is fine (\"you seemed stressed\"). Never claim to know how they feel. "
    "Never be dramatic or clinical.\n"
    "- If the topic is sensitive (health, family conflict, money), refer to it softly without details, "
    "for example \"what you shared the other day\".\n"
    "- Use today's date and the date of the event to phrase the timing naturally (\"yesterday\", "
    "\"last week\", \"before Friday\").\n"
    "- Use the participant's first name at most once, and only if it feels natural.\n"
    "- No advice, no emojis. Never mention memories, notes or summaries.\n\n"
    "Return only the message text, no quotes and no label."
)

EVENT_PROMPT = _PROMPT_HEAD + _EVENT_TASK + _PROMPT_RULES
SUMMARY_PROMPT = _PROMPT_HEAD + _SUMMARY_TASK + _PROMPT_RULES

MAX_WORDS = 20        # an answer longer than this is asked for once more, then the pool is used
RECENT_NOTES = 5      # how many of the newest conversation notes are given as background
TEMPERATURE = 0.7
MAX_TOKENS = 80


def format_day(value) -> str:
    """'Monday 26 October 2026' (same wording as the chat prompt); '' if it is not a date."""
    try:
        d = value if isinstance(value, date) else datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return ""
    return f"{d:%A} {d.day} {d:%B %Y}"


def _day(value) -> Optional[date]:
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def choose_event(events: List[dict]) -> Optional[dict]:
    """M4 (D13): the unused event with the highest score; among equal scores the most recent. No expiry."""
    unused = [e for e in events if not e.get("used") and e.get("memory_id") and e.get("content")]
    if not unused:
        return None
    return max(unused, key=lambda e: (
        int(e.get("affective_score") or 1),
        str(e.get("conversation_date") or e.get("timestamp_iso") or ""),
        str(e.get("timestamp_iso") or ""),
    ))


def recent_notes(notes: dict, limit: int = RECENT_NOTES) -> List[str]:
    """The newest conversation notes as dated lines, oldest first."""
    items = sorted(
        ((n.get("conversation_date") or "", n.get("updated_at") or "", str(n.get("summary") or "").strip())
         for n in (notes or {}).values() if isinstance(n, dict)),
    )
    items = [i for i in items if i[2]][-limit:]
    return [f"- {format_day(d) or 'Earlier'}: {text}" for d, _, text in items]


def _ago(days: Optional[int]) -> str:
    if days is None:
        return ""
    return "today" if days <= 0 else ("1 day ago" if days == 1 else f"{days} days ago")


class AffectiveHeuristic(BaseHeuristic):

    POOL = "affective"

    # memory_id marked `used` by the current get_proactive_message() call (None until then).
    _selected_memory_id: Optional[str] = None
    _pool_previous: Optional[dict] = None
    _pool_taken: bool = False

    def create_memory(self) -> None:
        """
        Memory is NOT built here any more (docs/REVIEW.md M1, D2): one shared pipeline
        (services/memory_pipeline.py) builds it for every participant of every condition, after a
        conversation has finished. This only makes sure that anything that finished since its last
        scheduled run is analysed before the notification is written.
        """
        from services import memory_pipeline
        try:
            memory_pipeline.run_job(only_user_id=self.user_id)
        except Exception as e:
            print(f"⚠️  AffectiveHeuristic memory catch-up ({self.username}): {e}")

    # ── Writing ──────────────────────────────────────────────────────────────

    def _write(self, system: str, user_content: str) -> Optional[str]:
        """Ask the model, at most twice; None if it failed or stayed over MAX_WORDS."""
        for _ in range(2):
            self.llm_attempts += 1
            try:
                text = (self.llm_service.call_with_prompt(
                    system=system, user_content=user_content, temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
                ) or "").strip()
            except Exception as e:
                print(f"⚠️  AffectiveHeuristic model call ({self.username}): {e}")
                return None
            if len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
                text = text[1:-1].strip()
            if text and len(text.split()) <= MAX_WORDS:
                return text
            print(f"⚠️  AffectiveHeuristic ({self.username}): answer of {len(text.split())} words, "
                  f"over {MAX_WORDS}{', asking once more' if self.llm_attempts < 2 else ''}")
        return None

    def _event_content(self, event: dict, today: date, notes: dict) -> str:
        shared = _day(event.get("conversation_date") or event.get("timestamp_iso"))
        self.memory_age_days = (today - shared).days if shared else None
        when = str(event.get("when") or "").strip()
        when_day = format_day(event.get("when_date"))
        lines = [
            f"Today: {format_day(today)}",
            f"First name: {self.name}",
            f"Event: {event.get('content')}",
        ]
        if event.get("feeling"):
            lines.append(f"Feeling they showed: {event['feeling']}")
        if shared:
            lines.append(f"Shared on: {format_day(shared)} ({_ago(self.memory_age_days)})")
        if when:
            lines.append(f"When it happens or happened, as they said it: {when}" + (f" ({when_day})" if when_day else ""))
        background = recent_notes(notes)
        if background:
            lines.append("Background, recent conversation notes (oldest first):\n" + "\n".join(background))
        return "\n".join(lines)

    def _summary_content(self, today: date, notes: dict) -> str:
        return "\n".join([
            f"Today: {format_day(today)}",
            f"First name: {self.name}",
            "Background, recent conversation notes (oldest first):\n" + "\n".join(recent_notes(notes)),
        ])

    # ── Main ─────────────────────────────────────────────────────────────────

    def get_proactive_message(self) -> Optional[str]:
        self.create_memory()
        self._reload_user()

        memory = self._memory
        notes = memory.get("conversation_notes") or {}
        today = datetime.now(ZoneInfo(STUDY_TIMEZONE)).date()
        self.llm_attempts = 0

        event = choose_event(list(memory.get("emotional_memories") or []))
        if event is not None:
            self._mark_used(event["memory_id"])
            text = self._write(EVENT_PROMPT, self._event_content(event, today, notes))
            if text:
                self.message_source = "event"
                self.used_fallback = False
                self.memory_content = str(event.get("content") or "")[:120]
                self.linked_memory_id = event.get("memory_id")
                self.linked_conversation_id = event.get("conversationId")
                return text
            # The model did not deliver: give the event back for a later notification.
            self.undo_selection()
            self.memory_age_days = None

        elif recent_notes(notes):
            text = self._write(SUMMARY_PROMPT, self._summary_content(today, notes))
            if text:
                self.message_source = "summary"
                self.used_fallback = True
                self.memory_content = ""
                return text

        self.message_source = "pool"
        self.used_fallback = True
        self.memory_content = ""
        text, self._pool_previous = message_pools.take(self.mongodb_client, self.user_id, self.user, self.POOL)
        self._pool_taken = True
        return text

    # ── State ────────────────────────────────────────────────────────────────

    def _mark_used(self, memory_id: str) -> None:
        """Mark the event used the moment it is chosen (by id, so exactly that one event)."""
        try:
            if self.mongodb_client.connect():
                self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                    {"_id": _ObjectId(self.user_id)},
                    {"$set": {"proactiveMemory.emotional_memories.$[elem].used": True}},
                    array_filters=[{"elem.memory_id": memory_id}],
                )
                self._selected_memory_id = memory_id
        except Exception as e:
            print(f"⚠️  AffectiveHeuristic mark-used ({self.username}): {e}")
        finally:
            self.mongodb_client.disconnect()

    def undo_selection(self) -> bool:
        """
        After a failed send (or a failed model call), give back what was taken: the event, so the
        participant still gets a message based on it next time, and the pool message.
        """
        undone = False
        if self._pool_taken:
            self._pool_taken = False
            undone = message_pools.restore(self.mongodb_client, self.user_id, self.POOL, self._pool_previous) or undone
        memory_id = self._selected_memory_id
        if not memory_id:
            return undone
        try:
            if not self.mongodb_client.connect():
                return undone
            self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                {"_id": _ObjectId(self.user_id)},
                {"$set": {"proactiveMemory.emotional_memories.$[elem].used": False}},
                array_filters=[{"elem.memory_id": memory_id}],
            )
            self._selected_memory_id = None
            print(f"↩️  [{self.username}] Emotional memory {memory_id[:8]} un-used")
            return True
        except Exception as e:
            print(f"⚠️  AffectiveHeuristic.undo_selection ({self.username}): {e}")
            return undone
        finally:
            self.mongodb_client.disconnect()
