"""
Affective Heuristic

Writes an empathetic check-in that refers to a personal event the participant shared earlier.

Memory is built by the shared pipeline (services/memory_pipeline.py, docs/REVIEW.md M1), the same
for every condition. This class only READS it: get_proactive_message() picks the best unused event
(or falls back to a warm invitation) and generates the message. An event is marked used as soon as
it is selected, so each one fires at most once.

MongoDB fields read (inside proactiveMemory):
  emotional_memories: [{memory_id, content, affective_score, conversationId, timestamp_iso, used, ...}]
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId as _ObjectId

from heuristics.base_heuristic import BaseHeuristic


class AffectiveHeuristic(BaseHeuristic):
    """
    Empathetic check-in about a personal event from an earlier conversation. Always produces a
    message (the cold-start path ensures there is always something to send).

    Memory field: proactiveMemory.emotional_memories, written by the shared memory pipeline.
    """

    DEFAULT_MESSAGE_PROMPT = (
        "You are an empathetic assistant that encourages emotional sharing.\n"
        "Generate a warm, personal emotional check-in (max 15 words) "
        "that directly references the specific emotional memory the user shared.\n"
        "Acknowledge their feelings without being dramatic or clinical.\n"
        "Invite them to share how they are feeling about it now.\n"
        "You MAY use the user's name once if it feels natural."
    )

    _COLD_START_PROMPT = (
        "You are an empathetic assistant that encourages emotional sharing.\n"
        "Generate a gentle, warm invitation (max 15 words) "
        "focused on emotional support and being a listening ear today.\n"
        "Use the user's name naturally."
    )

    _MEMORY_EXPIRY_HOURS: int = 72
    # memory_id marked `used` by the current get_proactive_message() call (None until then).
    _selected_memory_id: Optional[str] = None

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

    def get_proactive_message(self) -> Optional[str]:
        """
        Always returns a message string:
        - context-rich path: picks the best unused emotional memory and generates
          a personalised empathetic check-in referencing it
        - cold-start path: no memories available → warm generic invitation to share
          (Task 6.2: guaranteed fallback — never returns None)
        """
        self.create_memory()
        self._reload_user()

        emotional_memories = list(self._memory.get("emotional_memories") or [])
        now = datetime.now(timezone.utc)
        expiry_threshold = now - timedelta(hours=self._MEMORY_EXPIRY_HOURS)

        # Expire stale unused memories so old content is never resurfaced
        try:
            if emotional_memories and self.mongodb_client.connect():
                self.mongodb_client.db[self.mongodb_client.users_collection].update_many(
                    {
                        "_id": _ObjectId(self.user_id),
                        "proactiveMemory.emotional_memories": {
                            "$elemMatch": {
                                "used": False,
                                "timestamp_iso": {"$lt": expiry_threshold.isoformat()},
                            }
                        },
                    },
                    {"$set": {"proactiveMemory.emotional_memories.$[elem].used": True}},
                    array_filters=[{
                        "elem.used": False,
                        "elem.timestamp_iso": {"$lt": expiry_threshold.isoformat()},
                    }],
                )
        except Exception as e:
            print(f"⚠️  AffectiveHeuristic expire memories ({self.username}): {e}")
        finally:
            self.mongodb_client.disconnect()

        # Pick best unused memory (highest affective_score, then most recent)
        unused = [m for m in emotional_memories if not m.get("used", False)]
        has_context = bool(unused)

        if has_context:
            best = max(unused, key=lambda m: (
                m.get("affective_score", 1),
                m.get("timestamp_iso", "1900-01-01"),
            ))
            content = best.get("content", "")
            score   = best.get("affective_score", 1)

            # Task 6.7: record which memory drove this message
            self.memory_content = content[:120]
            self.used_fallback  = False
            # Task 6.9: capture memory ID and source conversation for context injection
            self.linked_memory_id = best.get("memory_id")
            self.linked_conversation_id = best.get("conversationId")

            system = self._safe_message_prompt(self.message_prompt)
            user_content = (
                f"USER NAME: {self.name}\n"
                f"EMOTIONAL MEMORY: {content}\n"
                f"AFFECTIVE DEPTH: {score}/10\n\n"
                "Craft a highly personalised empathetic check-in referencing this memory."
            )
            # Mark ONLY this specific memory as used (surgical — keyed by memory_id).
            # memory_id guarantees a single-element update even if duplicate content
            # somehow exists in the array. Falls back to positional $ for legacy
            # memories created before memory_id was introduced.
            try:
                if self.mongodb_client.connect():
                    memory_id = best.get("memory_id")
                    if memory_id:
                        self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                            {"_id": _ObjectId(self.user_id)},
                            {"$set": {"proactiveMemory.emotional_memories.$[elem].used": True}},
                            array_filters=[{"elem.memory_id": memory_id}],
                        )
                        self._selected_memory_id = memory_id
                    else:
                        # Legacy fallback: match by content for pre-memory_id memories
                        self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                            {
                                "_id": _ObjectId(self.user_id),
                                "proactiveMemory.emotional_memories": {
                                    "$elemMatch": {"content": content, "used": False}
                                },
                            },
                            {"$set": {"proactiveMemory.emotional_memories.$.used": True}},
                        )
                    print(f"💛 [{self.username}] Marked emotional memory as used: '{content[:50]}'")
            except Exception as e:
                print(f"⚠️  AffectiveHeuristic mark-used ({self.username}): {e}")
            finally:
                self.mongodb_client.disconnect()

            try:
                text = self.llm_service.call_with_prompt(
                    system=system,
                    user_content=user_content,
                    temperature=0.7,
                    max_tokens=80,
                )
                if text and len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
                    text = text[1:-1].strip()
                if not text:
                    raise ValueError("empty LLM response")
                return text
            except Exception as e:
                print(f"⚠️  AffectiveHeuristic message LLM ({self.username}): {e}")
                # Language-aware static fallback
                if self.language == "he":
                    return f"היי {self.name}, חשבתי על מה ששיתפת. איך אתה מרגיש עם זה עכשיו?"
                return f"Hi {self.name}, I was thinking about what you shared. How are you feeling about it now?"
        else:
            # Cold start: no unused memories — Task 6.2: guaranteed fallback
            # Task 6.7: mark as fallback path
            self.memory_content = ""
            self.used_fallback  = True

            print(f"💛 [{self.username}] Affective cold-start — no unused memories")
            prompt = self._COLD_START_PROMPT
            uc = (
                f"USER NAME: {self.name}\n\n"
                "Generate a gentle emotional invitation letting them know you are "
                "here as a listening ear today."
            )
            # Language-aware static fallback if LLM fails
            if self.language == "he":
                fallback = f"היי {self.name}, רק בודק — אני כאן אם צריך אוזן קשבת."
            else:
                fallback = f"Hi {self.name}, just checking in — I'm here if you need a listening ear."
            return self._cold_start_message(
                prompt=prompt,
                static_fallback=fallback,
                user_content=uc,
            )

    def undo_selection(self) -> bool:
        """
        The memory is marked `used` the moment it is selected. If the send then fails, give it back
        so the participant still gets a message based on it next time.
        """
        memory_id = self._selected_memory_id
        if not memory_id:
            return False
        try:
            if not self.mongodb_client.connect():
                return False
            self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                {"_id": _ObjectId(self.user_id)},
                {"$set": {"proactiveMemory.emotional_memories.$[elem].used": False}},
                array_filters=[{"elem.memory_id": memory_id}],
            )
            self._selected_memory_id = None
            print(f"↩️  [{self.username}] Emotional memory {memory_id[:8]} un-used after a failed send")
            return True
        except Exception as e:
            print(f"⚠️  AffectiveHeuristic.undo_selection ({self.username}): {e}")
            return False
        finally:
            self.mongodb_client.disconnect()

    # No clear_after_send() override needed: the emotional memory is already
    # marked used the moment it is selected in get_proactive_message(), so
    # there is nothing left to clean up after a successful send.
