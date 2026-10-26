"""
The shared memory pipeline (docs/REVIEW.md M1, decisions D2, D13, D17, D22).

ONE pipeline builds the participant's memory, identically for every condition (Reactive, Standard
and Affective): after a conversation is finished (the Finish button) or has been quiet for
INACTIVITY_MINUTES, ONE LLM call writes

  * a short summary of the conversation (-> proactiveMemory.conversation_notes.<conversationId>)
  * 0-5 scored personal events         (-> proactiveMemory.emotional_memories, same shape the
                                          Affective notification and the chat context already read)

The condition only decides how the memory is USED later; nothing here looks at it.
The prompt is the one printed in the protocol, appendix A.2.

Progress lives on the conversation itself (metadata_conversations.memory_scan), so the pipeline
needs no list of participants: it asks the database for conversations that are ready and not yet
analysed (or that grew after they were analysed). A short lock makes concurrent runs safe, and a
failed LLM call is retried after a back-off, never silently dropped.

The pipeline owns its LLM client and its database client. The scheduler runs jobs in several
threads and the shared ones switch model and connection per participant, so sharing them would
let this job change what another job is using.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from bson import ObjectId

from services import scan_progress

INACTIVITY_MINUTES = 30   # a conversation without a new message for this long counts as finished
LOCK_MINUTES = 10         # one run owns a conversation for this long
FAILURE_BACKOFF_MINUTES = 30
MAX_EVENTS = 5
CONTEXT_MESSAGES = 4      # earlier messages shown as context when a conversation is analysed again
MAX_TRANSCRIPT_CHARS = 20000
BATCH_LIMIT = 25          # conversations per run (bounds LLM cost per cycle)
TEMPERATURE = 0
MAX_TOKENS = 1200

# The text of protocol appendix A.2. Change it there and here together.
MEMORY_PROMPT = (
    "You are the memory of a warm companion app. You read one finished conversation between a person "
    "and Lexi, and write notes that Lexi will use later. Use only what the person said (Lexi's lines "
    "are context only). Never invent anything. Do not include anything that only Lexi said, such as her "
    "reassurance or guesses. Do not infer or speculate: write only what the person actually said, "
    "with no interpretation (no \"indicating\", \"suggesting\" or \"seems to\"). If the person did not say when "
    "something happens, set when and when_date to null; never take a date from another line.\n\n"
    "1. Summary (2-4 sentences, third person: \"The user ...\"): what they talked about, with the "
    "concrete details a caring friend would remember: names of people and pets, places, plans, events, "
    "how they felt, and anything left open or worth asking about later. Neutral and factual, no "
    "judgement, no advice.\n\n"
    "2. Events (0 to 5): each specific personal event, situation or feeling the person shared that "
    "Lexi could later follow up on. For each give:\n"
    "- event: one neutral sentence (\"The user is nervous about a presentation on Friday.\")\n"
    "- feeling: one or two words if they said or clearly showed how they felt, else null\n"
    "- when: when it happened or will happen, as stated (\"tomorrow\", \"last night\"), and the "
    "resolved calendar date when you can work it out from the conversation date\n"
    "- reason: one short sentence on why this event is or is not meaningful to follow up on\n"
    "- score (1-10), given after the reason: how meaningful it is for Lexi to remember and follow up on.\n"
    "  1-3: a passing remark, small talk\n"
    "  4-6: an ordinary event or a mild feeling\n"
    "  7-8: a significant personal event or a clearly felt emotion\n"
    "  9-10: a major life event or strong vulnerability (loss, fear, illness, a big decision)\n\n"
    "Skip small talk, general opinions and anything with no personal event or feeling. If there is "
    "nothing worth keeping, return an empty list. Output JSON only, in English, in this form:\n"
    "{\"summary\": \"...\", \"events\": [{\"event\": \"...\", \"feeling\": \"...\", \"when\": \"...\", "
    "\"when_date\": \"YYYY-MM-DD\", \"reason\": \"...\", \"score\": 0}]}"
)


# ── Pure helpers (no database, no LLM; unit-tested) ──────────────────────────

def _aware(dt) -> Optional[datetime]:
    """pymongo returns naive UTC datetimes; make them comparable with aware ones."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def is_ready(meta: dict, now: datetime) -> bool:
    """Finished with the button, or quiet for INACTIVITY_MINUTES."""
    if meta.get("isFinished"):
        return True
    last = _aware(meta.get("lastMessageDate"))
    return bool(last) and last <= now - timedelta(minutes=INACTIVITY_MINUTES)


def new_part(messages: List[dict], last_message_number: int) -> Tuple[List[dict], int]:
    """
    The part of a conversation to show the model, and where the NEW messages start.

    First analysis: the whole conversation. Continued conversation: the new messages plus a few
    earlier ones as context (the previous summary already covers the rest).
    Returns (messages_to_show, index of the first new message inside that list).
    """
    ordered = sorted(messages, key=lambda m: int(m.get("messageNumber") or 0))
    first_new = next(
        (i for i, m in enumerate(ordered) if int(m.get("messageNumber") or 0) > last_message_number),
        len(ordered),
    )
    start = max(0, first_new - CONTEXT_MESSAGES) if last_message_number else 0
    return ordered[start:], first_new - start


def has_new_participant_text(messages: List[dict], last_message_number: int) -> bool:
    return any(
        m.get("role") == "user" and m.get("content") and int(m.get("messageNumber") or 0) > last_message_number
        for m in messages
    )


def conversation_date(messages: List[dict], fallback: datetime) -> datetime:
    """Date used to resolve 'tomorrow' etc.: when the newest participant message was written."""
    dates = [_aware(m.get("createdAt")) for m in messages if m.get("role") == "user" and m.get("createdAt")]
    return max(dates) if dates else fallback


def format_transcript(messages: List[dict], first_new_index: int = 0) -> str:
    lines = []
    for i, m in enumerate(messages):
        if first_new_index and i == first_new_index:
            lines.append("--- new messages start here ---")
        text = " ".join(str(m.get("content") or "").split())
        if not text:
            continue
        who = "Participant" if m.get("role") == "user" else "Lexi"
        lines.append(f"{who}: {text}")
    text = "\n".join(lines)
    return text[-MAX_TRANSCRIPT_CHARS:]


def build_user_content(date: datetime, transcript: str, previous_summary: str = "") -> str:
    parts = [f"Conversation date: {date.strftime('%Y-%m-%d (%A)')}"]
    if previous_summary:
        parts.append(
            "Previous summary of this conversation (it continued after that was written; the lines "
            "before the marker are already covered by it; write ONE updated summary that covers "
            "everything, and list events only from the new messages):\n" + previous_summary
        )
    parts.append("Transcript:\n" + transcript)
    return "\n\n".join(parts)


def _valid_date(value) -> Optional[str]:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _score(value) -> int:
    """1-10; anything that is not a number counts as 1 instead of failing the whole conversation."""
    try:
        return max(1, min(10, int(round(float(value)))))
    except (TypeError, ValueError):
        return 1


def parse_result(raw_text: str) -> Tuple[str, List[dict]]:
    """Validate the model's JSON. Raises ValueError when it is not usable (so the run is retried)."""
    try:
        data = json.loads(raw_text)
    except (TypeError, ValueError) as e:
        raise ValueError(f"not JSON: {e}")
    if not isinstance(data, dict):
        raise ValueError("JSON is not an object")
    summary = str(data.get("summary") or "").strip()
    events = []
    for item in (data.get("events") or []):
        if not isinstance(item, dict):
            continue
        event = str(item.get("event") or "").strip()
        if not event:
            continue
        feeling = item.get("feeling")
        events.append({
            "event": event,
            "feeling": str(feeling).strip() if feeling else None,
            "when": str(item.get("when") or "").strip(),
            "when_date": _valid_date(item.get("when_date")),
            "reason": str(item.get("reason") or "").strip(),
            "score": _score(item.get("score")),
        })
    events.sort(key=lambda e: -e["score"])
    return summary, events[:MAX_EVENTS]


def make_event_docs(events: List[dict], conv_id: str, conv_date: datetime, now: datetime,
                    already_stored: set) -> List[dict]:
    """
    Event documents in the shape the rest of the system already reads (content, affective_score,
    memory_id, conversationId, timestamp_iso, used), plus the new fields. An event that is already
    stored for this conversation is skipped.
    """
    docs = []
    for e in events:
        key = (conv_id, scan_progress.normalize(e["event"]))
        if key in already_stored:
            continue
        already_stored.add(key)
        docs.append({
            "memory_id":       str(ObjectId()),
            "content":         e["event"],
            "feeling":         e["feeling"],
            "when":            e["when"],
            "when_date":       e["when_date"],
            "reason":          e["reason"],
            "affective_score": e["score"],
            "conversationId":  conv_id,
            "conversation_date": conv_date.date().isoformat(),
            "timestamp_iso":   now.replace(microsecond=0).isoformat(),
            "used":            False,
        })
    return docs


def ready_query(now: datetime, only_user_id: Optional[str] = None) -> dict:
    """Conversations that are ready, not locked, and new or changed since they were analysed."""
    cutoff = now - timedelta(minutes=INACTIVITY_MINUTES)
    query = {
        "messagesNumber": {"$gt": 0},
        "$and": [
            {"$or": [{"isFinished": True}, {"lastMessageDate": {"$lte": cutoff}}]},
            {"$or": [
                {"memory_scan.scanned_at": {"$exists": False}},
                {"$expr": {"$gt": ["$lastMessageDate", "$memory_scan.scanned_at"]}},
            ]},
            {"$or": [
                {"memory_scan.lock_until": {"$exists": False}},
                {"memory_scan.lock_until": {"$lt": now}},
            ]},
        ],
    }
    if only_user_id:
        query["userId"] = str(only_user_id)
    return query


# ── One conversation ─────────────────────────────────────────────────────────

def _claim(db, meta: dict, now: datetime) -> bool:
    res = db["metadata_conversations"].update_one(
        {"_id": meta["_id"], "$or": [
            {"memory_scan.lock_until": {"$exists": False}},
            {"memory_scan.lock_until": {"$lt": now}},
        ]},
        {"$set": {"memory_scan.lock_until": now + timedelta(minutes=LOCK_MINUTES)}},
    )
    return res.modified_count == 1


def _fail(db, meta: dict, now: datetime) -> None:
    db["metadata_conversations"].update_one(
        {"_id": meta["_id"]},
        {"$set": {"memory_scan.lock_until": now + timedelta(minutes=FAILURE_BACKOFF_MINUTES)},
         "$inc": {"memory_scan.failures": 1}},
    )


class _AlreadyDone(Exception):
    """Another run analysed these messages first; this run's results must not be stored."""


def _in_transaction(db, fn):
    """
    Run fn(session) as ONE database transaction, so the memory and the progress mark are stored
    together or not at all. Without a client (the test doubles) fn runs without a session.
    """
    try:
        client = db.client
    except AttributeError:
        return fn(None)
    with client.start_session() as session:
        return session.with_transaction(fn)


def _mark_scanned(db, meta: dict, now: datetime, newest: int, extra_events: int, expected: int, session=None) -> None:
    """
    Record that the conversation was analysed up to message `newest`, ONLY if nobody did it since this
    run started (compare-and-set on the progress). Raises _AlreadyDone otherwise, which aborts the
    transaction, so the same messages can never be stored twice.
    """
    if expected:
        guard = {"memory_scan.last_message_number": expected}
    else:
        guard = {"$or": [{"memory_scan.last_message_number": 0},
                         {"memory_scan.last_message_number": {"$exists": False}}]}
    total = int((meta.get("memory_scan") or {}).get("event_count") or 0) + extra_events
    res = db["metadata_conversations"].update_one(
        {"_id": meta["_id"], **guard},
        {"$set": {
            "memory_scan.last_message_number": newest,
            # The time the run started, not the time it finished: a message that arrives while the
            # model is working is newer than this and is picked up by the next run.
            "memory_scan.scanned_at": now,
            "memory_scan.lock_until": now,
            "memory_scan.event_count": total,
        }},
        session=session,
    )
    if res.matched_count != 1:
        raise _AlreadyDone()


def process_conversation(db, llm, meta: dict, now: datetime) -> str:
    """
    Analyse one ready conversation. Returns "analysed", "nothing_new", "locked", "already_done" or "failed".

    Each batch of messages is stored exactly once: a short lock keeps runs apart, and the memory and
    the progress mark are written in one transaction that only succeeds if the progress is still what
    this run started from. A failure stores nothing and is retried after a back-off.
    """
    if not _claim(db, meta, now):
        return "locked"

    conv_id = str(meta["_id"])
    scan = meta.get("memory_scan") or {}
    last_number = int(scan.get("last_message_number") or 0)
    try:
        messages = list(db["conversations"].find({"conversationId": conv_id}).sort("messageNumber", 1))
        newest = max((int(m.get("messageNumber") or 0) for m in messages), default=0)

        if not has_new_participant_text(messages, last_number):
            # e.g. the opener the engine created for a notification, before the participant replied
            _in_transaction(db, lambda s: _mark_scanned(db, meta, now, newest, 0, last_number, s))
            return "nothing_new"

        shown, first_new = new_part(messages, last_number)
        date = conversation_date(messages, now)
        previous = ((_user_notes(db, meta).get(conv_id) or {}).get("summary") or "") if last_number else ""
        raw = llm.call_with_prompt(
            system=MEMORY_PROMPT,
            user_content=build_user_content(date, format_transcript(shown, first_new), previous),
            json_mode=True,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
        )
        summary, events = parse_result(raw)

        user_id = ObjectId(str(meta["userId"]))
        stored = _stored_keys(db, user_id)
        docs = make_event_docs(events, conv_id, date, now, stored)
        update: dict = {}
        if summary:
            update["$set"] = {f"proactiveMemory.conversation_notes.{conv_id}": {
                "summary": summary,
                "conversation_date": date.date().isoformat(),
                "updated_at": now.replace(microsecond=0).isoformat(),
            }}
        if docs:
            update["$push"] = {"proactiveMemory.emotional_memories": {"$each": docs}}

        def store(session):
            if update:
                res = db["users"].update_one({"_id": user_id}, update, session=session)
                if res.matched_count != 1:
                    raise RuntimeError(f"participant {user_id} not found")
            _mark_scanned(db, meta, now, newest, len(docs), last_number, session)

        _in_transaction(db, store)
        print(f"🧠 memory: conversation {conv_id[:8]} -> {len(docs)} event(s), summary={'yes' if summary else 'no'}")
        return "analysed"
    except _AlreadyDone:
        print(f"ℹ️  memory pipeline: conversation {conv_id[:8]} was analysed by another run; nothing stored twice")
        return "already_done"
    except Exception as e:
        print(f"⚠️  memory pipeline, conversation {conv_id[:8]}: {e}")
        try:
            _fail(db, meta, now)
        except Exception as e2:
            print(f"⚠️  memory pipeline could not record the failure: {e2}")
        return "failed"


def _user_notes(db, meta: dict) -> dict:
    user = db["users"].find_one({"_id": ObjectId(str(meta["userId"]))}, {"proactiveMemory.conversation_notes": 1}) or {}
    return (user.get("proactiveMemory") or {}).get("conversation_notes") or {}


def _stored_keys(db, user_id) -> set:
    user = db["users"].find_one({"_id": user_id}, {"proactiveMemory.emotional_memories": 1}) or {}
    return {
        (m.get("conversationId"), scan_progress.normalize(m.get("content")))
        for m in ((user.get("proactiveMemory") or {}).get("emotional_memories") or [])
    }


# ── Runs ─────────────────────────────────────────────────────────────────────

def run_pipeline(db, llm, now: Optional[datetime] = None, only_user_id: Optional[str] = None,
                 limit: int = BATCH_LIMIT) -> Dict[str, int]:
    """Analyse every ready conversation (optionally one participant's). Returns counts per outcome."""
    now = now or datetime.now(timezone.utc)
    counts = {"analysed": 0, "nothing_new": 0, "locked": 0, "already_done": 0, "failed": 0}
    metas = list(
        db["metadata_conversations"].find(ready_query(now, only_user_id)).sort("lastMessageDate", 1).limit(limit)
    )
    for meta in metas:
        counts[process_conversation(db, llm, meta, now)] += 1
    return counts


_llm = None


def _own_llm():
    """A private LLM client, the same model for every participant (default: the protocol's GPT-4o)."""
    global _llm
    if _llm is None:
        from services.llm_service import ProactiveLogic
        _llm = ProactiveLogic()
        # MEMORY_LLM_MODEL lets the memory step use another model than the chat; unset = the default.
        _llm.use_model(os.getenv("MEMORY_LLM_MODEL"))
        print(f"🧠 memory pipeline model: {_llm.provider} / {_llm.model}")
    return _llm


def run_job(only_user_id: Optional[str] = None) -> Dict[str, int]:
    """Entry point for the scheduler job and for the catch-up before a notification is written."""
    from utils.mongodb_client import MongoDBClient
    client = MongoDBClient()
    if not client.connect():
        return {"analysed": 0, "nothing_new": 0, "locked": 0, "already_done": 0, "failed": 0}
    try:
        return run_pipeline(client.db, _own_llm(), only_user_id=only_user_id)
    except Exception as e:
        print(f"⚠️  memory pipeline run failed: {e}")
        return {"analysed": 0, "nothing_new": 0, "locked": 0, "already_done": 0, "failed": 1}
    finally:
        client.disconnect()
