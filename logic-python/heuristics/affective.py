"""
Affective Heuristic

Detects emotionally charged conversations and generates an empathetic
check-in referencing the user's shared emotional content.

create_memory() extracts emotional_memories via LLM; get_proactive_message()
picks the best unused memory (or falls back to a warm cold-start invitation)
and generates the check-in message. Memories are marked used as soon as they
are selected, so each one fires at most once.

MongoDB fields used (all inside proactiveMemory):
  emotional_memories: [{memory_id, content, affective_score, timestamp_iso, used}]
  affective_scanned_conversation_ids: List[str] — IDs of conversations already
    analyzed for emotional content. Mirrors the gap_scanned_conversation_ids
    pattern in BehaviouralGapHeuristic (Task 6.6).

Task 6.6 note: affective_scanned_conversation_ids is PRIVATE to AffectiveHeuristic.
  No other heuristic must read or write this field. Its name is intentionally
  prefixed with "affective_" to enforce isolation.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from bson import ObjectId as _ObjectId

from heuristics.base_heuristic import BaseHeuristic


class AffectiveHeuristic(BaseHeuristic):
    """
    Detects emotional content in recent conversations and generates an
    empathetic check-in. Always produces a message (cold-start fallback
    ensures there is always something to send when affective is selected).

    Memory field: proactiveMemory.emotional_memories
      List of {memory_id, content, affective_score (1-10), timestamp_iso, used: bool}

    Deduplication: affective_scanned_conversation_ids tracks which conversation
    IDs have already been analyzed; create_memory() skips them entirely.
    """

    # Task 6.5: researcher-facing prompt — persona/task only, no schema or output constraints.
    # Schema and "Return ONLY valid JSON" are injected automatically by _safe_memory_prompt().
    DEFAULT_MEMORY_PROMPT = (
        "You analyze conversation messages for deep emotional content.\n"
        "Extract emotional expressions, personal struggles, vulnerable shares, "
        "and meaningful life events shared by the user.\n\n"
        "Exclude casual mentions, surface-level topics, or purely factual statements."
    )

    # Task 6.5: structural part — injected by _safe_memory_prompt(), never shown in UI.
    # Note: conversationId, timestamp_iso, and used are added automatically by Python code.
    MEMORY_SCHEMA: str = (
        "For each genuine emotional share, produce an object with:\n"
        '  "content":        exact quote or close paraphrase of the emotional share\n'
        '  "affective_score": integer 1\u201310 (1=mildly emotional, 10=deeply personal/distressing)\n'
        '  "timestamp_iso":  use today\'s ISO datetime for all items\n'
        '  "used":           false\n\n'
        'Schema: {"emotional_memories": [{"content": str, "affective_score": int 1\u201310, '
        '"timestamp_iso": str, "used": false}]}\n'
        'Return {"emotional_memories": []} if no genuine emotional content is present.'
    )

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
    _CONV_SCAN_LIMIT: int = 3

    def create_memory(self) -> None:
        """
        Scan conversations NOT yet in affective_scanned_conversation_ids.
        Extract emotional_memories via LLM and push new ones to MongoDB.
        Mirrors the gap_scanned_conversation_ids pattern (Task 6.6): once a
        conversation is processed it is never re-analyzed, eliminating both the
        sliding-window miss bug and duplicate-extraction bug.
        """
        memory = self._memory
        scanned_ids: set = set(memory.get("affective_scanned_conversation_ids") or [])
        conversations_to_process: list = []  # [(conv_id, texts), ...]
        newly_scanned_ids: list = []

        # ── Phase A: Read messages from UNANALYZED conversations only ─────────
        try:
            if not self.mongodb_client.connect():
                return

            # Build an exclusion query so MongoDB returns only unscanned convs.
            scanned_oids = []
            for cid in scanned_ids:
                try:
                    scanned_oids.append(_ObjectId(cid))
                except Exception:
                    pass
            query: dict = {"userId": self.user_id}
            if scanned_oids:
                query["_id"] = {"$nin": scanned_oids}

            recent_metas = list(self.mongodb_client.db["metadata_conversations"].find(
                query,
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
                # Store conversation ID WITH its texts to maintain the link
                conversations_to_process.append((conv_id, texts))
                # Mark as scanned even if empty — avoids re-fetching every cycle.
                # Conversations with future messages will appear as a NEW conv doc.
                newly_scanned_ids.append(conv_id)
        except Exception as e:
            print(f"⚠️  AffectiveHeuristic.create_memory read ({self.username}): {e}")
            return
        finally:
            self.mongodb_client.disconnect()

        if not newly_scanned_ids:
            return  # Nothing new to process

        # Task 6.3: detect language from the messages collected above.
        _detected_lang = None
        all_texts = []
        for _, texts in conversations_to_process:
            all_texts.extend(texts)
        if all_texts:
            _detected_lang = self._detect_language(all_texts)
            if _detected_lang:
                self.language = _detected_lang

        # ── Phase B: LLM extraction per conversation (outside DB connection) ───
        new_memories: list = []
        today_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        
        for conv_id, texts in conversations_to_process:
            if not texts:
                continue
                
            joined = "\n".join(f"- {m}" for m in texts[-20:] if m)
            system = self._safe_memory_prompt(
                self.memory_prompt.replace("{today_iso}", today_iso)
            )
            try:
                raw_text = self.llm_service.call_with_prompt(
                    system=system,
                    user_content=f"User messages:\n{joined}",
                    json_mode=True,
                    max_tokens=600,
                )
                parsed = json.loads(raw_text)
                for item in (parsed.get("emotional_memories") or []):
                    content = (item.get("content") or "").strip()
                    if content:
                        new_memories.append({
                            "memory_id":       str(_ObjectId()),  # Unique ID for surgical mark-as-used
                            "content":         content,
                            "affective_score": max(1, min(10, int(item.get("affective_score") or 1))),
                            "conversationId":  conv_id,  # ✅ FIXED: Now correctly links to THIS conversation
                            "timestamp_iso":   today_iso,  # Added automatically: extraction time
                            "used":            False,  # Added automatically: tracking field
                        })
                        print(f"💛 [{self.username}] Extracted memory from conversation {conv_id[:8]}: '{content[:50]}'")
            except Exception as e:
                print(f"⚠️  AffectiveHeuristic.create_memory LLM ({self.username}) conv {conv_id[:8]}: {e}")

        # ── Phase C: Write to MongoDB ──────────────────────────────────────────
        try:
            if not self.mongodb_client.connect():
                return
            update: dict = {
                "$addToSet": {
                    "proactiveMemory.affective_scanned_conversation_ids": {
                        "$each": newly_scanned_ids
                    }
                }
            }
            if _detected_lang:
                update["$set"] = {"proactiveMemory.preferred_language": _detected_lang}
            if new_memories:
                update["$push"] = {
                    "proactiveMemory.emotional_memories": {"$each": new_memories}
                }
                print(f"💛 [{self.username}] Extracted {len(new_memories)} new emotional memory(ies)")
            self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                {"_id": _ObjectId(self.user_id)}, update
            )
        except Exception as e:
            print(f"⚠️  AffectiveHeuristic.create_memory write ({self.username}): {e}")
        finally:
            self.mongodb_client.disconnect()

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

    # No clear_after_send() override needed: the emotional memory is already
    # marked used the moment it is selected in get_proactive_message(), so
    # there is nothing left to clean up after a successful send.
