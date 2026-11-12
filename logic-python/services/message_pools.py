"""
The fixed, hand-written notification pools (docs/REVIEW.md D18, protocol appendix A.5,
docs/MESSAGE_POOLS.md). Change them there and here together.

Drawing rule, per participant and per pool: random, each message used once before any message
repeats, and never the same message twice in a row (also not across the start of a new round).
The state is stored on the participant: proactiveMemory.pool_state.<pool> = {"used": [...], "last": i}.
"""
from __future__ import annotations

import random
from typing import Optional, Tuple

STANDARD_POOL = (
    "Feel like chatting?",
    "Do you have a few minutes to chat?",
    "Want to have a quick chat?",
    "Got a moment to talk?",
    "Would you like to chat for a bit?",
    "A good moment for a quick chat?",
    "Care to chat?",
    "Ready for a chat whenever you are.",
    "Lexi is here if you'd like to chat.",
    "Up for a conversation?",
    "Free for a short chat?",
    "How about a quick chat?",
    "Time for a chat?",
    "Want to chat for a few minutes?",
    "Open to a short chat now?",
    "Lexi is ready to chat.",
    "Shall we chat for a moment?",
    "Interested in a chat right now?",
    "Ready to chat?",
    "A short chat, if you have the time?",
)

AFFECTIVE_POOL = (
    "How are you feeling today? I'm here if you'd like to talk.",
    "Hope your day is going well. Want to tell me about it?",
    "How's your day been treating you? I'd love to hear.",
    "I'm here whenever you want to share how things are going.",
    "Just checking in. How are you doing today?",
    "How has your day been? I'm happy to listen.",
    "Anything on your mind today? I'm here to listen.",
    "Hope you're doing okay. Want to talk about your day?",
)

POOLS = {"standard": STANDARD_POOL, "affective": AFFECTIVE_POOL}


def pick(size: int, state: Optional[dict], rng=random) -> Tuple[int, dict]:
    """Choose the next index of a pool of `size` messages. Returns (index, new state)."""
    state = state or {}
    used = {i for i in (state.get("used") or []) if isinstance(i, int) and 0 <= i < size}
    last = state.get("last")
    remaining = [i for i in range(size) if i not in used]
    if not remaining:  # a new round starts, but not with the message that was sent last
        used = set()
        remaining = [i for i in range(size) if i != last] or list(range(size))
    index = rng.choice(remaining)
    return index, {"used": sorted(used | {index}), "last": index}


def state_path(pool: str) -> str:
    return f"proactiveMemory.pool_state.{pool}"


def take(mongodb_client, user_id, user_doc: dict, pool: str, rng=random) -> Tuple[str, Optional[dict]]:
    """
    Draw a message for one participant and store the new state.
    Returns (message, previous state) so a failed send can put the state back (restore()).
    """
    from bson import ObjectId

    messages = POOLS[pool]
    previous = ((user_doc.get("proactiveMemory") or {}).get("pool_state") or {}).get(pool)
    index, new_state = pick(len(messages), previous, rng)
    try:
        if mongodb_client.connect():
            mongodb_client.db[mongodb_client.users_collection].update_one(
                {"_id": ObjectId(str(user_id))}, {"$set": {state_path(pool): new_state}},
            )
    except Exception as e:
        print(f"⚠️  message_pools.take({pool}): could not store the pool state: {e}")
    finally:
        mongodb_client.disconnect()
    return messages[index], previous


def restore(mongodb_client, user_id, pool: str, previous: Optional[dict]) -> bool:
    """Put the pool state back after a failed send, so the message is not counted as used."""
    from bson import ObjectId

    try:
        if not mongodb_client.connect():
            return False
        update = {"$set": {state_path(pool): previous}} if previous else {"$unset": {state_path(pool): ""}}
        mongodb_client.db[mongodb_client.users_collection].update_one({"_id": ObjectId(str(user_id))}, update)
        return True
    except Exception as e:
        print(f"⚠️  message_pools.restore({pool}): {e}")
        return False
    finally:
        mongodb_client.disconnect()
