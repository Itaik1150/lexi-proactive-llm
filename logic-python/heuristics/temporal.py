"""
Temporal Heuristic

Fires a nudge when a future event the user mentioned is approaching.

Signal source: proactiveMemory.future_mentions, each {"text": str, "when_iso": str | null},
written by TemporalHeuristic.create_memory() below.

Logic:
  - If any future mention has a when_iso that is 6–24 hours away (the lead-time
    window), and has not already been fired, generate a message about it.
  - After a successful FCM send, clear_after_send() stamps the mention so it never
    triggers a second time.
  - If no qualifying event exists this cycle, a warm cold-start invitation is
    generated instead (Task 6.2: guaranteed fallback — never returns None).

Task 6.6 note: TemporalHeuristic deduplicates by mention text stored in
  proactiveMemory.future_mentions and proactiveMemory.fired_temporal_mentions.
  Both fields are PRIVATE to TemporalHeuristic and must not be read or
  written by any other heuristic.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId as _ObjectId

from heuristics.base_heuristic import BaseHeuristic


class TemporalHeuristic(BaseHeuristic):
    """
    Detects upcoming events the user has mentioned and sends a timely reminder
    or question when the event falls within the lead-time window (6–24 hours).

    Memory field: proactiveMemory.future_mentions
      List of {text, when_iso}

    Fired-once: proactiveMemory.fired_temporal_mentions (set of keys) ensures
    each event triggers at most one notification.

    Task 6.2: get_proactive_message() always returns a message — if no qualifying
    event is found, a warm cold-start invitation is generated instead of None.
    """

    DEFAULT_MEMORY_PROMPT = (
        "You analyze conversation messages for mentions of upcoming events, "
        "plans, appointments, or activities."
    )

    # Task 6.5: structural part — injected by _safe_memory_prompt(), never shown in UI.
    # Note: conversationId and timestamp_iso are added automatically by Python code.
    # {today_iso} is substituted at runtime in create_memory() after assembly.
    MEMORY_SCHEMA: str = (
        "Today is {today_iso}. Resolve all relative dates against today.\n\n"
        "For each future event found, extract:\n"
        '  "text":     concise description (e.g. "job interview", "doctor appointment")\n'
        '  "when_iso": ISO 8601 datetime string if timing is mentioned, or null if unclear\n\n'
        'Schema: {"future_mentions": [{"text": str, "when_iso": str or null}]}\n'
        'Return {"future_mentions": []} if no future events are mentioned.'
    )

    DEFAULT_MESSAGE_PROMPT = (
        "You are a friendly assistant. Generate a warm, timely message "
        "(max 15 words) about the user's upcoming event or plan.\n"
        "If the event is still ahead: ask if they are ready or excited.\n"
        "If the event just passed: ask how it went.\n"
        "Never confuse past and future timing. "
        "You MAY use the user's name once."
    )

    _COLD_START_PROMPT = (
        "You are a friendly, curious assistant.\n"
        "Generate a warm, open-ended question (max 15 words) "
        "inviting the user to share any upcoming plans or events they are looking forward to.\n"
        "Use the user's name naturally."
    )

    _CONV_SCAN_LIMIT: int = 5
    _LEAD_TIME_MIN_HOURS: float = 6
    _LEAD_TIME_MAX_HOURS: float = 24

    def __init__(self, user, llm_service, mongodb_client, prompts_from_db=None, default_language="he"):
        super().__init__(user, llm_service, mongodb_client, prompts_from_db, default_language)
        self._fired_nudge: Optional[dict] = None  # set in get_proactive_message

    @staticmethod
    def _make_key(text: str, when_iso: str) -> str:
        """Stable key for a (mention, datetime) pair to track which mentions have fired."""
        return f"{text[:50].strip()}|{when_iso}"

    def create_memory(self) -> None:
        """
        Extract future_mentions from recent conversations and merge them into
        proactiveMemory.future_mentions, deduplicating by text.
        Already-fired mentions are not re-added.
        """
        conversations_to_process: list = []  # [(conv_id, texts), ...]

        # ── Phase A: Read messages ─────────────────────────────────────────────
        try:
            if not self.mongodb_client.connect():
                return
            recent_metas = list(self.mongodb_client.db["metadata_conversations"].find(
                {"userId": self.user_id},
                sort=[("createdAt", -1)],
                limit=self._CONV_SCAN_LIMIT,
            ))
            if not recent_metas:
                return
            for meta in recent_metas:
                conv_id = str(meta["_id"])
                raw = list(self.mongodb_client.db["conversations"].find(
                    {"conversationId": conv_id, "role": "user"},
                    sort=[("messageNumber", 1)],
                ))
                texts = [m.get("content", "") for m in raw if m.get("content")]
                conversations_to_process.append((conv_id, texts))
        except Exception as e:
            print(f"⚠️  TemporalHeuristic.create_memory read ({self.username}): {e}")
            return
        finally:
            self.mongodb_client.disconnect()

        if not conversations_to_process:
            return

        # Task 6.3: detect language from collected messages (character analysis,
        # no extra DB call). Applied to self.language immediately; persisted in
        # Phase C below so future cycles read from preferred_language (cascade lvl 1).
        all_texts = []
        for _, texts in conversations_to_process:
            all_texts.extend(texts)
        _detected_lang = self._detect_language(all_texts)
        if _detected_lang:
            self.language = _detected_lang

        # ── Phase B: LLM extraction per conversation ───────────────────────────
        today_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        new_mentions = []
        
        for conv_id, texts in conversations_to_process:
            if not texts:
                continue
                
            joined = "\n".join(f"- {m}" for m in texts[-40:] if m)
            # {today_iso} lives in MEMORY_SCHEMA; substitute on the fully assembled prompt.
            system = self._safe_memory_prompt(self.memory_prompt).replace("{today_iso}", today_iso)

            try:
                raw_text = self.llm_service.call_with_prompt(
                    system=system,
                    user_content=f"User messages:\n{joined}",
                    json_mode=True,
                    max_tokens=400,
                )
                parsed = json.loads(raw_text)
                for item in (parsed.get("future_mentions") or []):
                    if isinstance(item, dict):
                        text_val = (item.get("text") or "").strip()
                        if text_val:
                            new_mentions.append({
                                "text":            text_val,
                                "when_iso":        item.get("when_iso"),
                                "conversationId":  conv_id,  # ✅ FIXED: Now correctly links to THIS conversation
                                "timestamp_iso":   today_iso,  # Added automatically: extraction time
                            })
                            print(f"⏰ [{self.username}] Extracted future mention from conversation {conv_id[:8]}: '{text_val[:50]}'")
            except Exception as e:
                print(f"⚠️  TemporalHeuristic.create_memory LLM ({self.username}) conv {conv_id[:8]}: {e}")

        # ── Phase C: Merge into MongoDB ────────────────────────────────────────
        # Runs even when no new mentions are found so that the detected language
        # is always persisted to proactiveMemory.preferred_language.
        if not new_mentions and not _detected_lang:
            return

        try:
            if not self.mongodb_client.connect():
                return

            to_add: list = []
            if new_mentions:
                user_doc = self.mongodb_client.db[self.mongodb_client.users_collection].find_one(
                    {"_id": _ObjectId(self.user_id)},
                    {"proactiveMemory.future_mentions": 1,
                     "proactiveMemory.fired_temporal_mentions": 1},
                )
                existing = (user_doc or {}).get("proactiveMemory", {}).get("future_mentions") or []
                fired_keys = set(
                    (user_doc or {}).get("proactiveMemory", {}).get("fired_temporal_mentions") or []
                )
                existing_texts = {(m.get("text") or "").lower() for m in existing}
                to_add = [
                    m for m in new_mentions
                    if m["text"].lower() not in existing_texts
                    and self._make_key(m["text"], m.get("when_iso") or "") not in fired_keys
                ]

            update_doc: dict = {}
            if _detected_lang:
                update_doc["$set"] = {"proactiveMemory.preferred_language": _detected_lang}
            if to_add:
                update_doc["$push"] = {
                    "proactiveMemory.future_mentions": {"$each": to_add}
                }
                print(f"🕐 [{self.username}] Added {len(to_add)} new future mention(s)")

            if update_doc:
                self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                    {"_id": _ObjectId(self.user_id)},
                    update_doc,
                )
        except Exception as e:
            print(f"⚠️  TemporalHeuristic.create_memory write ({self.username}): {e}")
        finally:
            self.mongodb_client.disconnect()

    def get_proactive_message(self) -> Optional[str]:
        """
        Returns a message if a future mention falls in the 6–24h window.
        Task 6.2: if no qualifying event exists, generates a warm cold-start
        invitation instead of returning None (guaranteed fallback).
        """
        self.create_memory()
        self._reload_user()

        future_mentions = self._memory.get("future_mentions") or []
        fired_keys = set(self._memory.get("fired_temporal_mentions") or [])
        now = datetime.now(timezone.utc)

        for mention in future_mentions:
            if not isinstance(mention, dict):
                continue
            text     = (mention.get("text") or "").strip()
            when_iso = mention.get("when_iso")
            if not text or not when_iso:
                continue
            if self._make_key(text, when_iso) in fired_keys:
                continue
            try:
                when = datetime.fromisoformat(str(when_iso).replace("Z", "+00:00"))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            hours_until = (when - now).total_seconds() / 3600.0
            if self._LEAD_TIME_MIN_HOURS <= hours_until <= self._LEAD_TIME_MAX_HOURS:
                self._fired_nudge = {
                    "mention_text": text,
                    "when_iso":     str(when_iso),
                    "hours_until":  hours_until,
                }
                # Task 6.9: capture source conversation for context injection
                self.linked_conversation_id = mention.get("conversationId")
                break

        if not self._fired_nudge:
            # Task 6.2: cold-start — no event in lead-time window this cycle
            # Task 6.7: mark as fallback path
            print(f"🕐 [{self.username}] Temporal cold-start — no event in window")
            self.used_fallback  = True
            self.memory_content = ""
            prompt = self._COLD_START_PROMPT
            if self.language == "he":
                fallback = f"היי {self.name}, יש משהו מעניין שאתה מצפה לו בקרוב?"
            else:
                fallback = f"Hi {self.name}, anything exciting coming up soon?"
            return self._cold_start_message(
                prompt=prompt,
                static_fallback=fallback,
            )

        n = self._fired_nudge
        print(f"🕐 [{self.username}] Temporal event in window: '{n['mention_text'][:40]}' "
              f"({n['hours_until']:.1f}h away)")

        # Task 6.7: record which event drove this message
        self.memory_content = n["mention_text"][:120]
        self.used_fallback  = False

        system = self._safe_message_prompt(self.message_prompt)
        user_content = (
            f"USER NAME: {self.name}\n"
            f"EVENT: {n['mention_text']}\n"
            f"HOURS UNTIL EVENT (negative = already passed): {n['hours_until']:.1f}"
        )
        try:
            text = self.llm_service.call_with_prompt(
                system=system,
                user_content=user_content,
                temperature=0.6,
                max_tokens=80,
            )
            if text and len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
                text = text[1:-1].strip()
            if text:
                return text
            raise ValueError("empty LLM response")
        except Exception as e:
            print(f"⚠️  TemporalHeuristic message LLM ({self.username}): {e}")
            if self.language == "he":
                return f"היי {self.name}, האירוע שלך '{n['mention_text']}' מתקרב!"
            return f"Hi {self.name}, your event '{n['mention_text']}' is coming up!"

    def clear_after_send(self) -> None:
        """Mark the fired temporal mention so it never triggers again."""
        if not self._fired_nudge:
            return
        key = self._make_key(self._fired_nudge["mention_text"], self._fired_nudge["when_iso"])
        try:
            if not self.mongodb_client.connect():
                return
            self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                {"_id": _ObjectId(self.user_id)},
                {"$addToSet": {"proactiveMemory.fired_temporal_mentions": key}},
            )
            print(f"🕐 [{self.username}] Temporal mention marked as fired: "
                  f"'{self._fired_nudge['mention_text'][:40]}'")
        except Exception as e:
            print(f"⚠️  TemporalHeuristic.clear_after_send ({self.username}): {e}")
        finally:
            self.mongodb_client.disconnect()
