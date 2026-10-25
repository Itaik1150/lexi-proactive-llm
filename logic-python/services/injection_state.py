"""
Snapshot and restore of the user-document fields that a proactive injection overwrites, so a
send that fails after injection can be undone (docs/REVIEW.md V3).

inject_prompt() changes:
  agent.firstChatSentence                       <- the proactive message
  proactiveMemory.injected_prompt_original      <- the greeting to restore later
  proactiveMemory.linked_memory_id              <- memory behind the message
  proactiveMemory.linked_conversation_id        <- conversation created for it
Restoring puts each field back to what it was, or removes it if it did not exist.
"""
from __future__ import annotations

from typing import Optional, Tuple

PROJECTION = {
    "agent.firstChatSentence": 1,
    "proactiveMemory.injected_prompt_original": 1,
    "proactiveMemory.linked_memory_id": 1,
    "proactiveMemory.linked_conversation_id": 1,
}

_FIELDS = (
    ("first_chat_sentence",      "agent.firstChatSentence"),
    ("injected_prompt_original", "proactiveMemory.injected_prompt_original"),
    ("linked_memory_id",         "proactiveMemory.linked_memory_id"),
    ("linked_conversation_id",   "proactiveMemory.linked_conversation_id"),
)


def snapshot_from_user_doc(doc: Optional[dict]) -> Optional[dict]:
    """Extract the four fields from a user document (None if there is no document)."""
    if doc is None:
        return None
    agent = doc.get("agent") or {}
    memory = doc.get("proactiveMemory") or {}
    return {
        "first_chat_sentence":      agent.get("firstChatSentence"),
        "injected_prompt_original": memory.get("injected_prompt_original"),
        "linked_memory_id":         memory.get("linked_memory_id"),
        "linked_conversation_id":   memory.get("linked_conversation_id"),
    }


def restore_update(snapshot: dict) -> Tuple[dict, dict]:
    """($set, $unset) documents that put the user document back to the snapshot."""
    to_set, to_unset = {}, {}
    for key, path in _FIELDS:
        value = snapshot.get(key)
        if value is None:
            to_unset[path] = ""
        else:
            to_set[path] = value
    return to_set, to_unset
