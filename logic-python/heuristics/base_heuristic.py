"""
BaseHeuristic — Abstract base class for all proactive heuristics.

Each concrete subclass is responsible for:
  create_memory()          — extract and persist heuristic-relevant memories
                             from recent conversations into proactiveMemory (MongoDB).
  get_proactive_message()  — call create_memory(), reload fresh state, then generate
                             and return a proactive message string.  Returns None if
                             this heuristic has nothing to send this cycle.
  clear_after_send()       — post-FCM cleanup hook (default: no-op).

Prompts are loaded in priority order:
  1. experiments.proactiveSettings.heuristicPrompts (researcher override via dashboard)
  2. DEFAULT_MEMORY_PROMPT / DEFAULT_MESSAGE_PROMPT class attributes (hardcoded fallback)

Task 6.5 — Prompt Safety & Separation:
  Structural formatting rules (JSON schema, output constraints) are NEVER part of the
  researcher-facing prompts. They are appended automatically by _safe_memory_prompt()
  and _safe_message_prompt() before every LLM call. Researchers only write the
  persona/task description in the dashboard prompt editors.

Task 6.6 — Independent Conversation Analysis:
  TRACKING FIELD CONVENTION: Each subclass MUST use its own namespaced tracking field
  inside proactiveMemory. Prefix all tracking fields with the heuristic name
  (e.g., affective_, gap_, temporal_). Never read or write a sibling heuristic's
  tracking field.

All LLM calls go through llm_service._call_llm() via llm_service.call_with_prompt().
No heuristic file makes direct HTTP requests.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from bson import ObjectId


class BaseHeuristic(ABC):
    """Abstract base for all proactive heuristics (Task 3.2)."""

    DEFAULT_MEMORY_PROMPT: str = ""
    DEFAULT_MESSAGE_PROMPT: str = ""

    # ── Task 6.5: Per-heuristic schema (structural, not researcher-facing) ────
    # Subclasses define the exact JSON schema and empty-return instruction here.
    # Kept out of DEFAULT_MEMORY_PROMPT so researchers never see or need to
    # maintain schema lines in the dashboard prompt editor.
    MEMORY_SCHEMA: str = ""

    # ── Task 6.5: Structural safety suffixes ──────────────────────────────────
    # Appended by _safe_memory_prompt() / _safe_message_prompt() before every
    # LLM call so researchers cannot accidentally break output formatting by
    # omitting these lines when editing the persona/task prompt in the dashboard.

    STRUCTURAL_JSON_SUFFIX: str = (
        "\n\n--- SYSTEM FORMATTING RULE (do not modify) ---\n"
        "Return ONLY valid JSON matching the schema above. "
        "Do not include any text, explanation, or markdown outside the JSON object."
    )

    STRUCTURAL_MESSAGE_SUFFIX: str = (
        "\n\n--- SYSTEM OUTPUT RULE (do not modify) ---\n"
        "Return ONLY the final notification message text. "
        "No labels, no quotes, no explanations. Maximum 20 words."
    )

    def __init__(
        self,
        user: dict,
        llm_service,
        mongodb_client,
        prompts_from_db: dict = None,
        default_language: str = "he",
    ):
        self.user           = user
        self.user_id        = str(user["_id"])
        self.username       = user.get("username", "Unknown")
        self.llm_service    = llm_service
        self.mongodb_client = mongodb_client

        memory = user.get("proactiveMemory") or {}
        self.name = (memory.get("demographics") or {}).get("name") or self.username

        # ── Task 6.3: 3-level language cascade ────────────────────────────────
        # Level 1: explicit field in proactiveMemory (written by previous cycles)
        # Level 2: top-level user document field (set at registration)
        # Level 3: experiment-level default passed from _load_experiment_settings()
        # Level 4: absolute hardcoded fallback "en"
        self.language: str = (
            memory.get("preferred_language")
            or user.get("language")
            or default_language
            or "en"
        )
        print(f"🌐 [{self.username}] Language resolved: {self.language}")

        # Prompt loading: DB override takes priority over hardcoded default
        prompts = prompts_from_db or {}
        self.memory_prompt  = prompts.get("memoryPrompt")  or self.DEFAULT_MEMORY_PROMPT
        self.message_prompt = prompts.get("messagePrompt") or self.DEFAULT_MESSAGE_PROMPT

        # ── Task 6.7: Logging metadata ────────────────────────────────────────
        # Subclasses set these before returning from get_proactive_message() so
        # research_service can include them in the proactive_logs document.
        self.used_fallback: bool = False  # True when cold-start / fallback path taken
        self.memory_content: str = ""     # snippet of memory that drove the message
        self.linked_memory_id: str = None  # ID of specific memory/event used (for context injection)
        self.linked_conversation_id: str = None  # conversation where memory originated

    # ── Convenience properties ─────────────────────────────────────────────────

    @property
    def _memory(self) -> dict:
        """Live snapshot of the user's proactiveMemory sub-document."""
        return self.user.get("proactiveMemory") or {}

    @property
    def _target_lang(self) -> str:
        return "Hebrew" if self.language == "he" else "English"

    # ── Task 6.3: Language detection helpers ───────────────────────────────────

    @staticmethod
    def _detect_language(texts: list) -> Optional[str]:
        """
        Detect language from user message texts using Hebrew character analysis.
        Returns 'he' if Hebrew script is predominant (>15% of alphabetic chars),
        'en' otherwise.  Returns None if texts is empty or has no alphabetic chars.
        """
        if not texts:
            return None
        sample = " ".join(str(t) for t in texts[:20] if t)
        hebrew_count = sum(
            1 for c in sample
            if '\u05D0' <= c <= '\u05EA' or '\uFB1D' <= c <= '\uFB4E'
        )
        alpha_count = sum(1 for c in sample if c.isalpha())
        if alpha_count == 0:
            return None
        return "he" if hebrew_count / alpha_count > 0.15 else "en"

    def _ensure_language_detected(self) -> None:
        """
        Detect user language from recent conversation messages if preferred_language
        is not yet stored in proactiveMemory. Writes the detected value to MongoDB
        and updates self.language for the current cycle.

        Used by GenericHeuristic (which reads no messages in create_memory).
        Other heuristics call _detect_language() inline during create_memory() to
        piggyback on their already-open DB connection and already-read messages.
        """
        if (self.user.get("proactiveMemory") or {}).get("preferred_language"):
            return  # Already stored from a previous cycle

        texts: list = []
        try:
            if not self.mongodb_client.connect():
                return
            metas = list(self.mongodb_client.db["metadata_conversations"].find(
                {"userId": self.user_id},
                sort=[("createdAt", -1)],
                limit=2,
            ))
            for meta in metas:
                msgs = list(self.mongodb_client.db["conversations"].find(
                    {"conversationId": str(meta["_id"]), "role": "user"},
                    sort=[("messageNumber", 1)],
                    limit=20,
                ))
                texts.extend(m.get("content", "") for m in msgs if m.get("content"))

            detected = self._detect_language(texts)
            if detected:
                self.mongodb_client.db[self.mongodb_client.users_collection].update_one(
                    {"_id": ObjectId(self.user_id)},
                    {"$set": {"proactiveMemory.preferred_language": detected}},
                )
                if detected != self.language:
                    print(
                        f"🌐 [{self.username}] Language auto-detected from messages: "
                        f"{self.language} → {detected} ({('Hebrew' if detected == 'he' else 'English')})"
                    )
                    self.language = detected
        except Exception as e:
            print(f"⚠️  {self.__class__.__name__}._ensure_language_detected({self.username}): {e}")
        finally:
            self.mongodb_client.disconnect()

    # ── Task 6.5: Prompt safety helpers ───────────────────────────────────────

    def _safe_memory_prompt(self, researcher_prompt: str) -> str:
        """
        Build the full memory-extraction prompt for the LLM.

        Structure:
          [researcher_prompt]   ← persona / task description (editable in dashboard)
          [MEMORY_SCHEMA]       ← JSON schema + empty-return rule (system-managed, per heuristic)
          [STRUCTURAL_JSON_SUFFIX] ← "Return ONLY valid JSON" constraint (system-managed, shared)

        This keeps schema definitions and output-format constraints completely out of
        the researcher-facing text, satisfying Task 6.5.
        """
        schema_block = f"\n\n{self.MEMORY_SCHEMA}" if self.MEMORY_SCHEMA else ""
        return researcher_prompt + schema_block + self.STRUCTURAL_JSON_SUFFIX

    def _safe_message_prompt(self, researcher_prompt: str) -> str:
        """
        Build the full message-generation prompt for the LLM.

        Structure:
          [researcher_prompt]      ← persona / tone description (editable in dashboard, no {language})
          [language instruction]   ← "Write your response in Hebrew/English only." (system-managed)
          [STRUCTURAL_MESSAGE_SUFFIX] ← "Return ONLY the final message text..." (system-managed)

        Language is injected automatically from self._target_lang so researchers never need to
        write {language} placeholders in their prompts (Task 6.5 / user request).
        """
        lang_instruction = f"\n\nWrite your response in {self._target_lang} only."
        return researcher_prompt + lang_instruction + self.STRUCTURAL_MESSAGE_SUFFIX

    # ── Task 6.2: Cold-start helper ────────────────────────────────────────────

    def _cold_start_message(
        self,
        prompt: str,
        static_fallback: str,
        user_content: Optional[str] = None,
    ) -> str:
        """
        Generate a cold-start / fallback message via LLM.

        _safe_message_prompt() is applied automatically so the prompt passed here
        should NOT include any "Return ONLY..." structural instructions.

        Falls back to static_fallback if the LLM call fails or returns empty text.

        Args:
            prompt: Persona/task prompt (already with {language} substituted).
            static_fallback: Returned verbatim if LLM call fails.
            user_content: Optional custom user content; defaults to "USER NAME: {self.name}".
        """
        uc = user_content if user_content is not None else f"USER NAME: {self.name}"
        try:
            text = self.llm_service.call_with_prompt(
                system=self._safe_message_prompt(prompt),
                user_content=uc,
                temperature=0.7,
                max_tokens=80,
            )
            if text and len(text) >= 2 and text[0] in ('"', "'") and text[0] == text[-1]:
                text = text[1:-1].strip()
            return text or static_fallback
        except Exception as e:
            print(f"⚠️  {self.__class__.__name__}._cold_start_message({self.username}): {e}")
            return static_fallback

    # ── Shared helpers ─────────────────────────────────────────────────────────

    def _reload_user(self) -> None:
        """
        Re-read proactiveMemory from MongoDB into self.user.
        Must be called at the start of get_proactive_message() after create_memory()
        has written new data, so the message-generation step sees the fresh state.

        Task 6.3: also re-runs the language cascade so that any preferred_language
        written by create_memory() (language auto-detection) is picked up immediately
        for the current cycle's message generation.
        """
        try:
            if self.mongodb_client.connect():
                fresh = self.mongodb_client.db[
                    self.mongodb_client.users_collection
                ].find_one(
                    {"_id": ObjectId(self.user_id)},
                    {"proactiveMemory": 1},
                )
                if fresh:
                    self.user = {
                        **self.user,
                        "proactiveMemory": fresh.get("proactiveMemory") or {},
                    }
                    # Re-run language cascade with the freshly loaded proactiveMemory
                    fresh_memory = self.user.get("proactiveMemory") or {}
                    refreshed = (
                        fresh_memory.get("preferred_language")
                        or self.user.get("language")
                        or self.language
                    )
                    if refreshed != self.language:
                        print(f"🌐 [{self.username}] Language refreshed after reload: "
                              f"{self.language} → {refreshed}")
                        self.language = refreshed
        except Exception as e:
            print(f"⚠️  {self.__class__.__name__}._reload_user({self.username}): {e}")
        finally:
            self.mongodb_client.disconnect()

    # ── Abstract interface ─────────────────────────────────────────────────────

    @abstractmethod
    def create_memory(self) -> None:
        """
        Scan recent conversations and write heuristic-relevant memories to MongoDB.
        Uses self.memory_prompt for the LLM extraction call.
        Must be idempotent — use message counters or conversation IDs to deduplicate.
        """
        ...

    @abstractmethod
    def get_proactive_message(self) -> Optional[str]:
        """
        Refresh memory (create_memory → _reload_user), then generate and return
        the proactive message string.
        Returns None if this heuristic has nothing to send this cycle.
        """
        ...

    def clear_after_send(self) -> None:
        """
        Post-send cleanup called by research_service after a successful FCM send.
        Default: no-op.  Override in subclasses that write pending state to MongoDB.
        """
        pass

    def undo_selection(self) -> bool:
        """
        Reverse state this heuristic consumed when it picked its memory, for a send that failed
        afterwards, so the memory can be used on the next attempt. Returns True if something
        was undone. Default: nothing to undo (the heuristic only changes state after a send).
        """
        return False
