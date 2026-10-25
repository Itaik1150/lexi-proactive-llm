"""
Behavioural Gap Heuristic

Fires a gentle follow-up when a user stated an explicit intention
but hasn't mentioned whether they followed through after 24–48 hours.

BehaviouralGapHeuristic.create_memory() scans for new stated intents and
checks existing ones for completion; get_proactive_message() generates the
follow-up message if a gap is currently pending.

If no pending gap exists this cycle, a warm cold-start invitation is generated
instead (Task 6.2: guaranteed fallback — never returns None).

MongoDB fields used (inside proactiveMemory):
  open_intents:                  List[{intent, stated_at, checked}]
  pending_gap_followup:          {intent_text, stated_at}
  gap_scanned_conversation_ids:  List[str]  — IDs of conversations already scanned
                                             for intents (Task 6.6: replaces the old
                                             single-cursor last_intent_scan_conversation_id)

Task 6.6 note: gap_scanned_conversation_ids is PRIVATE to BehaviouralGapHeuristic.
  No other heuristic must read or write this field. The set-based approach ensures
  all recent conversations are eventually scanned while allowing other heuristics
  (Affective, Temporal) to independently process the same conversations.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, List

from bson import ObjectId as _ObjectId

from heuristics.base_heuristic import BaseHeuristic
from services import scan_progress


class BehaviouralGapHeuristic(BaseHeuristic):
    """
    Detects when a user stated an explicit intention but has not followed up.
    Generates a gentle follow-up asking if they went through with it.

    Task 6.6: Uses gap_scanned_conversation_ids (set) instead of a single
    last_intent_scan_conversation_id cursor. This ensures all recent unscanned
    conversations are processed, and other heuristics can still process any
    conversation that BehaviouralGap has already scanned.
    """

    # Task 6.5: researcher-facing prompt — persona/task only, no schema or output constraints.
    DEFAULT_MEMORY_PROMPT = (
        "You analyze conversation messages from a user.\n"
        "Extract only EXPLICIT, concrete plans or commitments the user expressed.\n\n"
        "Valid examples:\n"
        "  - 'I'll go to the gym tomorrow'\n"
        "  - 'I'm starting that online course next week'\n"
        "  - 'I plan to call my mom tonight'\n\n"
        "Invalid (too vague — do NOT include):\n"
        "  - 'I want to be healthier'\n"
        "  - 'Maybe I'll try that someday'\n"
        "  - 'I should exercise more'"
    )

    # Task 6.5: structural part — injected by _safe_memory_prompt(), never shown in UI.
    # Note: conversationId, timestamp_iso, and checked are added automatically by Python code.
    MEMORY_SCHEMA: str = (
        'Schema: {"intents": [{"intent": "concise English description"}]}\n'
        'Return {"intents": []} if no clear commitments are found.'
    )

    DEFAULT_MESSAGE_PROMPT = (
        "You are a supportive, caring assistant.\n"
        "Generate a gentle, friendly follow-up message (max 15 words) "
        "asking whether the user followed through on their stated plan.\n"
        "Do NOT assume success or failure — stay curious and supportive.\n"
        "You MAY use the user's name once."
    )

    _COLD_START_PROMPT = (
        "You are a supportive, encouraging assistant.\n"
        "Generate a warm, friendly check-in message (max 15 words) "
        "asking the user if they have been working towards any of their goals lately.\n"
        "Use the user's name naturally."
    )

    _GAP_MIN_HOURS: float = 24
    _GAP_MAX_HOURS: float = 48

    _CONV_SCAN_LIMIT: int = 3         # conversations analysed per cycle (bounds LLM cost)
    _CONV_LOOKBACK: int = 10          # newest conversations checked for unanalysed participant messages
    _RECENT_CONVERSATIONS: int = 3    # newest conversations whose messages feed the completion check

    def create_memory(self) -> None:
        """
        Extract intents from participant messages that have not been analysed yet, then check
        existing intents for completion.

        Progress is tracked per conversation (proactiveMemory.gap_scan_progress =
        {conversationId: highest participant messageNumber analysed}), see services/scan_progress.py:
        a growing conversation is analysed again for its NEW messages only, a conversation without
        participant messages yet is picked up once the participant replies, and progress advances
        only after a successful extraction (a failed LLM call is retried next cycle).
        """
        memory = self._memory
        progress: dict = dict(memory.get("gap_scan_progress") or {})
        legacy_ids: set = set(memory.get("gap_scanned_conversation_ids") or [])
        existing_intents: List[dict] = list(memory.get("open_intents") or [])

        # ── Phase A: Read ──────────────────────────────────────────────────────
        conversations_to_process: list = []  # [(conv_id, [new messages]), ...]
        progress_updates: dict = {}          # conv_id -> highest messageNumber now considered analysed
        recent_user_messages: List[str] = []  # for the completion check: the newest conversations

        try:
            if not self.mongodb_client.connect():
                return

            recent_metas = list(self.mongodb_client.db["metadata_conversations"].find(
                {"userId": self.user_id},
                sort=[("createdAt", -1)],
                limit=self._CONV_LOOKBACK,
            ))

            for position, meta in enumerate(recent_metas):
                conv_id = str(meta["_id"])
                raw = list(self.mongodb_client.db["conversations"].find(
                    {"conversationId": conv_id, "role": "user"},
                    sort=[("messageNumber", 1)],
                ))
                msgs = scan_progress.user_messages(raw)
                if position < self._RECENT_CONVERSATIONS:
                    recent_user_messages.extend(m["text"] for m in msgs)

                new_msgs, migrate_to = scan_progress.plan_conversation(conv_id, msgs, progress, legacy_ids)
                if migrate_to is not None:
                    progress_updates[conv_id] = migrate_to  # scanned under the old scheme: do not redo
                    continue
                if new_msgs and len(conversations_to_process) < self._CONV_SCAN_LIMIT:
                    conversations_to_process.append((conv_id, new_msgs))

        except Exception as e:
            print(f"⚠️  BehaviouralGapHeuristic.create_memory read ({self.username}): {e}")
            return
        finally:
            self.mongodb_client.disconnect()

        # Task 6.3: detect language from messages collected above (no extra DB call).
        # Persisted in Phase C below; self.language updated for use in this cycle.
        _detected_lang = self._detect_language(recent_user_messages)
        if _detected_lang:
            self.language = _detected_lang

        # ── Phase B-1: LLM intent extraction for conversations with new messages ──
        new_intents: List[dict] = []

        for conv_id, new_msgs in conversations_to_process:
            try:
                joined = "\n".join(f"- {m['text']}" for m in new_msgs[-30:])
                raw_text = self.llm_service.call_with_prompt(
                    system=self._safe_memory_prompt(self.memory_prompt),
                    user_content=f"Participant messages:\n{joined}",
                    json_mode=True,
                    max_tokens=300,
                )
                parsed = json.loads(raw_text)
                intents_raw = parsed.get("intents") or []
                existing_texts = {i.get("intent", "").lower() for i in existing_intents + new_intents}
                now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                for item in intents_raw:
                    text = (item.get("intent") or "").strip()
                    if text and text.lower() not in existing_texts:
                        new_intents.append({
                            "intent":          text,
                            "conversationId":  conv_id,  # Added automatically: source conversation
                            "stated_at":       now_iso,  # Added automatically: extraction time
                            "checked":         False,  # Added automatically: tracking field
                        })
                        existing_texts.add(text.lower())
                # Only a successful extraction advances progress; a failure is retried next cycle.
                progress_updates[conv_id] = scan_progress.last_number(new_msgs)
                if intents_raw:
                    print(f"   🔍 gap: scanned conv {conv_id[:8]}... "
                          f"({len(new_msgs)} new msgs, {len(intents_raw)} intent(s) found)")
            except Exception as e:
                print(f"⚠️  BehaviouralGapHeuristic intent extraction ({self.username}): {e}")

        # ── Phase B-2: Check completion for intents in the 24–48h window ──────
        all_intents              = existing_intents + new_intents
        now                      = datetime.now(timezone.utc)
        pending_gap: Optional[dict]  = None
        indices_to_mark: List[int]   = []

        for idx, intent in enumerate(all_intents):
            if intent.get("checked"):
                continue
            stated_at_raw = intent.get("stated_at")
            if not stated_at_raw:
                continue
            try:
                stated_at = datetime.fromisoformat(
                    str(stated_at_raw).replace("Z", "+00:00")
                )
                if stated_at.tzinfo is None:
                    stated_at = stated_at.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue

            hours_ago = (now - stated_at).total_seconds() / 3600.0

            if hours_ago < self._GAP_MIN_HOURS:
                continue
            if hours_ago > self._GAP_MAX_HOURS:
                indices_to_mark.append(idx)
                continue

            if not recent_user_messages:
                pending_gap = {
                    "intent_text": intent["intent"],
                    "stated_at":   intent["stated_at"],
                }
                indices_to_mark.append(idx)
                # Task 6.9: capture source conversation for context injection
                self.linked_conversation_id = intent.get("conversationId")
                break

            try:
                result  = self.llm_service.check_intent_completion(
                    intent["intent"], recent_user_messages, self.language
                )
                outcome = result.get("outcome", "unknown")
                indices_to_mark.append(idx)
                if outcome == "unknown":
                    pending_gap = {
                        "intent_text": intent["intent"],
                        "stated_at":   intent["stated_at"],
                    }
                    # Task 6.9: capture source conversation for context injection
                    self.linked_conversation_id = intent.get("conversationId")
                    break
            except Exception as e:
                print(f"⚠️  BehaviouralGapHeuristic completion check ({self.username}): {e}")

        # ── Phase C: Write ─────────────────────────────────────────────────────
        nothing_changed = (
            not new_intents
            and pending_gap is None
            and not indices_to_mark
            and not progress_updates
            and not _detected_lang  # Task 6.3: language detection is also a write reason
        )
        if nothing_changed:
            return

        for idx in indices_to_mark:
            if idx < len(all_intents):
                all_intents[idx]["checked"] = True

        try:
            if not self.mongodb_client.connect():
                return
            update: dict = {
                "$set": {
                    "proactiveMemory.open_intents": all_intents,
                }
            }
            # Task 6.3: persist detected language so future cycles cascade to level 1
            if _detected_lang:
                update["$set"]["proactiveMemory.preferred_language"] = _detected_lang
            for cid, n in progress_updates.items():
                update["$set"][scan_progress.progress_path("gap_scan_progress", cid)] = n
            if pending_gap:
                update["$set"]["proactiveMemory.pending_gap_followup"] = pending_gap
                print(f"🔍 Gap followup queued for {self.username}: "
                      f"'{pending_gap['intent_text'][:50]}'")
            self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                {"_id": _ObjectId(self.user_id)}, update
            )
        except Exception as e:
            print(f"⚠️  BehaviouralGapHeuristic.create_memory write ({self.username}): {e}")
        finally:
            self.mongodb_client.disconnect()

    def get_proactive_message(self) -> Optional[str]:
        """
        Returns a message if a pending gap followup exists.
        Task 6.2: if no pending gap, generates a warm cold-start invitation instead
        of returning None (guaranteed fallback).
        """
        self.create_memory()
        self._reload_user()

        followup = self._memory.get("pending_gap_followup")
        if not followup or not isinstance(followup, dict):
            # Task 6.2: cold-start — no pending gap this cycle
            # Task 6.7: mark as fallback path
            print(f"🔍 [{self.username}] Gap cold-start — no pending followup")
            self.used_fallback  = True
            self.memory_content = ""
            prompt = self._COLD_START_PROMPT
            if self.language == "he":
                fallback = f"היי {self.name}, איך מתקדם עם התוכניות שלך?"
            else:
                fallback = f"Hi {self.name}, how have you been doing with your plans lately?"
            return self._cold_start_message(
                prompt=prompt,
                static_fallback=fallback,
            )

        intent_text = (followup.get("intent_text") or "").strip()
        if not intent_text:
            print(f"🔍 [{self.username}] Gap cold-start — followup has no intent text")
            self.used_fallback  = True
            self.memory_content = ""
            prompt = self._COLD_START_PROMPT
            if self.language == "he":
                fallback = f"היי {self.name}, איך מתקדם עם התוכניות שלך?"
            else:
                fallback = f"Hi {self.name}, how have you been doing with your plans lately?"
            return self._cold_start_message(
                prompt=prompt,
                static_fallback=fallback,
            )

        # Task 6.7: record which intent drove this message
        self.memory_content = intent_text[:120]
        self.used_fallback  = False

        system = self._safe_message_prompt(self.message_prompt)
        user_content = (
            f"USER NAME: {self.name}\n"
            f"STATED PLAN: {intent_text}\n\n"
            "Generate a gentle follow-up asking if they went through with this plan."
        )
        try:
            text = self.llm_service.call_with_prompt(
                system=system,
                user_content=user_content,
                temperature=0.5,
                max_tokens=80,
            )
            if text and len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
                text = text[1:-1].strip()
            if text:
                return text
            raise ValueError("empty LLM response")
        except Exception as e:
            print(f"⚠️  BehaviouralGapHeuristic message LLM ({self.username}): {e}")
            if self.language == "he":
                return f"היי {self.name}, האם בסוף {intent_text}?"
            return f"Hi {self.name}, did you end up {intent_text}?"

    def clear_after_send(self) -> None:
        """Remove pending_gap_followup after a successful send."""
        try:
            if not self.mongodb_client.connect():
                return
            self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                {"_id": _ObjectId(self.user_id)},
                {"$unset": {"proactiveMemory.pending_gap_followup": ""}},
            )
            print(f"🔍 [{self.username}] Gap followup cleared")
        except Exception as e:
            print(f"⚠️  BehaviouralGapHeuristic.clear_after_send ({self.username}): {e}")
        finally:
            self.mongodb_client.disconnect()
