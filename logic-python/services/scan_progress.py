"""
Per-conversation scan progress for the memory-building heuristics (docs/REVIEW.md V6).

Each heuristic remembers, per conversation, the highest participant `messageNumber` it has
analysed (e.g. proactiveMemory.affective_scan_progress = {"<conversationId>": 4}). Next time:

  * a conversation that has grown is analysed again for its NEW messages only;
  * a conversation with no participant messages yet (such as the opener the engine itself
    created for a notification) stays pending and is analysed once the participant replies;
  * a conversation the heuristic already scanned under the old scheme (a plain list of ids)
    is treated as done the first time it is seen, so the upgrade does not re-extract
    (and duplicate) old memories.

Progress only advances after a successful analysis, so a failed LLM call is retried next cycle.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Tuple


def user_messages(raw_docs: Iterable[dict]) -> List[dict]:
    """[{n: messageNumber, text: content}] for participant messages that have text, in order."""
    out = []
    for doc in raw_docs:
        text = doc.get("content")
        if text:
            out.append({"n": int(doc.get("messageNumber") or 0), "text": text})
    out.sort(key=lambda m: m["n"])
    return out


def last_number(messages: List[dict]) -> int:
    """Highest messageNumber in `messages` (0 if there are none)."""
    return max((m["n"] for m in messages), default=0)


def plan_conversation(
    conversation_id: str,
    messages: List[dict],
    progress: dict,
    legacy_ids: Iterable[str] = (),
) -> Tuple[List[dict], Optional[int]]:
    """
    Decide what to analyse for one conversation.

    Returns (new_messages, migrate_to):
      new_messages  participant messages not analysed yet
      migrate_to    if not None, store this as the conversation's progress WITHOUT analysing
                    (it was scanned under the old scheme)
    """
    if conversation_id not in progress and conversation_id in set(legacy_ids):
        return [], last_number(messages)
    last = int(progress.get(conversation_id) or 0)
    return [m for m in messages if m["n"] > last], None


def progress_path(field: str, conversation_id: str) -> str:
    """Mongo dotted path of one conversation's progress entry."""
    return f"proactiveMemory.{field}.{conversation_id}"


def normalize(text: str) -> str:
    """Lower-cased, whitespace-collapsed form used to spot a memory that was already extracted."""
    return " ".join(str(text or "").lower().split())
