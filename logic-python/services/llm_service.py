from __future__ import annotations

import os
import json
from typing import List, Dict, Any

import requests

from dotenv import load_dotenv
load_dotenv()



class ProactiveLogic:
    """
    Simple LLM-based service for deciding if news headlines are socially proactive
    """
    
    def __init__(self):
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self.model    = os.getenv("LLM_MODEL",    "gpt-4o")
        self.api_url  = "https://api.openai.com/v1/chat/completions"

        if self.provider == "anthropic":
            self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not self.anthropic_api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY not found in environment variables "
                    "(required when LLM_PROVIDER=anthropic)"
                )
            self.api_key = ""
        else:
            self.api_key = os.getenv("OPENAI_API_KEY", "")
            if not self.api_key:
                raise ValueError("OPENAI_API_KEY not found in environment variables")

        # Remembered so a per-experiment override can be undone for the next participant.
        self._default_provider = self.provider
        self._default_model    = self.model

        print(f"🤖 LLM engine: {self.provider.upper()} / {self.model}")
        self._log_api_key_status()

    def use_model(self, model=None):
        """
        Select the model for the next calls: the experiment's `model`, or the environment
        default (LLM_PROVIDER / LLM_MODEL) when the experiment sets none.

        Call this for EVERY participant. override_model() alone leaves the previous
        participant's model active, so one experiment's choice would leak into others.
        """
        model = (model or "").strip()
        if not model:
            self.provider = self._default_provider
            self.model    = self._default_model
            return
        self.override_model(model)

    def _log_api_key_status(self) -> None:
        """
        Print a startup summary of which API keys are configured.
        Both keys can coexist in the environment (e.g. OpenAI default,
        Anthropic available for override_model() mid-cycle).
        Called once at __init__ and once after each override_model() switch.
        """
        openai_key    = os.getenv("OPENAI_API_KEY", "")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        print(
            f"   🔑 API keys: "
            f"OpenAI={'✅ set' if openai_key else '❌ missing'} | "
            f"Anthropic={'✅ set' if anthropic_key else '❌ missing'}"
        )

    def override_model(self, model: str):
        """
        Temporarily switch the active model for the current proactive cycle.
        If the model prefix implies a different provider (claude-* → anthropic,
        gpt-* / o* → openai), the provider is switched as well.
        Called once per user when the experiment's proactiveSettings.llmModel
        differs from the env-configured default.
        """
        if model == self.model:
            return  # nothing to do

        if model.startswith("claude"):
            self.provider = "anthropic"
            self.anthropic_api_key = os.getenv("ANTHROPIC_API_KEY", "")
        else:
            self.provider = "openai"
            self.api_key  = os.getenv("OPENAI_API_KEY", "")

        self.model = model
        print(f"🔄 LLM overridden by experiment settings: {self.provider.upper()} / {self.model}")
        self._log_api_key_status()

    def _call_llm(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 120,
        json_mode: bool = False,
    ) -> str:
        """
        Single dispatch point for all LLM calls in ProactiveLogic.
        Routes to OpenAI or Anthropic based on self.provider / self.model.
        Raises on HTTP or network errors — callers handle their own fallbacks.
        """
        if self.provider == "anthropic":
            # Anthropic Messages API — system is a separate top-level field
            system_content = ""
            anthropic_messages = []
            for m in messages:
                if m["role"] == "system":
                    system_content = m["content"]
                else:
                    anthropic_messages.append(m)

            headers = {
                "x-api-key": self.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            if json_mode:
                system_content = (system_content + "\n\nReturn ONLY valid JSON, no other text.").strip()

            body: Dict[str, Any] = {
                "model": self.model,
                "max_tokens": max_tokens,
                "messages": anthropic_messages,
            }
            if system_content:
                body["system"] = system_content

            resp = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
                timeout=45,
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"].strip()

        else:
            # OpenAI-compatible API
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            }
            body = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}

            resp = requests.post(self.api_url, headers=headers, json=body, timeout=45)
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

    def call_with_prompt(
        self,
        system: str,
        user_content: str,
        json_mode: bool = False,
        temperature: float = 0.4,
        max_tokens: int = 400,
    ) -> str:
        """
        Generic LLM dispatch used by all heuristic classes (Task 3.2).

        Heuristic classes pass their memory_prompt or message_prompt as `system`,
        and the relevant context (messages, event info, etc.) as `user_content`.
        All calls still route through _call_llm() — single dispatch point.

        Raises on LLM failure so callers can provide their own fallback.
        """
        msgs = [
            {"role": "system", "content": system},
            {"role": "user",   "content": user_content},
        ]
        return self._call_llm(
            msgs,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
        )

    def check_intent_completion(
        self,
        intent_text: str,
        recent_messages: List[str],
        language: str = "he",
    ) -> Dict[str, Any]:
        """
        Phase 4.5: Determine if a user's recent messages indicate they followed
        through on a previously stated intent.

        Returns:
            {
            "resolved": bool,
            "outcome": "positive" | "negative" | "unknown"
            }
        - positive:  user mentioned doing it / completing it
        - negative:  user explicitly mentioned NOT doing it / cancelling
        - unknown:   messages give no signal either way → triggers the nudge

        Returns {"resolved": False, "outcome": "unknown"} on any failure.
        """
        default: Dict[str, Any] = {"resolved": False, "outcome": "unknown"}
        if not intent_text or not recent_messages:
            return default

        joined = "\n".join(f"- {m}" for m in recent_messages[-30:] if m)

        system_prompt = (
            f"A user previously intended to: '{intent_text}'.\n\n"
            "Based on their recent messages, determine whether they followed through:\n"
            "- outcome: 'positive' if they mentioned doing it or completing it\n"
            "- outcome: 'negative' if they explicitly mentioned NOT doing it or cancelling\n"
            "- outcome: 'unknown' if their messages give no clear signal either way\n"
            "- resolved: true only when outcome is 'positive' or 'negative'\n\n"
            "Return ONLY valid JSON with exactly two keys: resolved, outcome."
        )
        user_prompt = f"Recent messages:\n{joined}"

        msgs = [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ]
        try:
            text   = self._call_llm(msgs, temperature=0.1, max_tokens=80, json_mode=True)
            parsed = json.loads(text)
            outcome = str(parsed.get("outcome", "unknown"))
            if outcome not in ("positive", "negative", "unknown"):
                outcome = "unknown"
            return {
                "resolved": bool(parsed.get("resolved", False)),
                "outcome":  outcome,
            }
        except Exception as e:
            print(f"⚠️  check_intent_completion: error: {e}")
            return default

