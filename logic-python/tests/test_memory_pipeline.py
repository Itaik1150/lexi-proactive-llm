"""
M1 (docs/REVIEW.md): ONE memory pipeline for every condition (D2, D17, D22).
"""
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bson import ObjectId

from services import memory_pipeline as mp

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)
USER_ID = ObjectId()
CONV_ID = ObjectId()


def msg(n, text, role="user", minutes_ago=60):
    return {"messageNumber": n, "role": role, "content": text, "createdAt": NOW - timedelta(minutes=minutes_ago)}


GOOD = {
    "summary": "The user talked about a presentation on Friday and their dog Rex.",
    "events": [
        {"event": "The user is nervous about a presentation on Friday.", "feeling": "nervous",
         "when": "Friday", "when_date": "2026-10-30", "reason": "Clearly felt and time-bound.", "score": 7},
        {"event": "The user walked their dog.", "feeling": None, "when": "today", "when_date": "2026-10-26",
         "reason": "Ordinary.", "score": 3},
    ],
}


class FakeSession:
    """Records that the pipeline stored its results inside ONE transaction."""
    def __init__(self):
        self.transactions = 0
        self.aborted = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def with_transaction(self, fn):
        self.transactions += 1
        try:
            return fn(self)
        except Exception:
            self.aborted += 1
            raise


class FakeDb(dict):
    def __init__(self):
        super().__init__()
        self.session = FakeSession()
        self.client = MagicMock()
        self.client.start_session.return_value = self.session


def make_db(messages, meta_scan=None, claim_ok=True, user_found=True, notes=None, stored=None):
    """A database double that records what the pipeline writes."""
    db = FakeDb()
    conversations = MagicMock()
    conversations.find.return_value.sort.return_value = messages
    users = MagicMock()
    users.find_one.side_effect = lambda flt, proj=None: {
        "proactiveMemory": {"conversation_notes": notes or {}, "emotional_memories": stored or []}
    }
    users.update_one.return_value = MagicMock(matched_count=1 if user_found else 0)
    metas = MagicMock()
    metas.update_one.return_value = MagicMock(modified_count=1 if claim_ok else 0, matched_count=1 if claim_ok else 0)
    db["conversations"], db["users"], db["metadata_conversations"] = conversations, users, metas
    meta = {"_id": CONV_ID, "userId": str(USER_ID), "isFinished": True, "memory_scan": meta_scan or {}}
    return db, meta


def llm_returning(payload):
    llm = MagicMock()
    llm.call_with_prompt.return_value = payload if isinstance(payload, str) else json.dumps(payload)
    return llm


def scan_updates(db):
    """The $set dicts written to the conversation's memory_scan, in order."""
    return [c.args[1].get("$set", {}) for c in db["metadata_conversations"].update_one.call_args_list]


class Readiness(unittest.TestCase):
    def test_finished_conversation_is_ready_at_once(self):
        self.assertTrue(mp.is_ready({"isFinished": True, "lastMessageDate": NOW}, NOW))

    def test_quiet_conversation_is_ready_after_the_inactivity_time(self):
        quiet = NOW - timedelta(minutes=mp.INACTIVITY_MINUTES + 1)
        self.assertTrue(mp.is_ready({"isFinished": False, "lastMessageDate": quiet}, NOW))

    def test_active_conversation_is_not_ready(self):
        self.assertFalse(mp.is_ready({"isFinished": False, "lastMessageDate": NOW - timedelta(minutes=5)}, NOW))

    def test_mongo_returns_naive_dates_and_they_still_compare(self):
        naive = (NOW - timedelta(hours=2)).replace(tzinfo=None)
        self.assertTrue(mp.is_ready({"isFinished": False, "lastMessageDate": naive}, NOW))

    def test_query_can_be_limited_to_one_participant(self):
        self.assertEqual(mp.ready_query(NOW, "abc")["userId"], "abc")
        self.assertNotIn("userId", mp.ready_query(NOW))


class WhatTheModelSees(unittest.TestCase):
    MSGS = [msg(i, f"m{i}", "user" if i % 2 else "assistant") for i in range(1, 11)]

    def test_first_analysis_shows_the_whole_conversation(self):
        shown, first_new = mp.new_part(self.MSGS, 0)
        self.assertEqual(len(shown), 10)
        self.assertEqual(first_new, 0)

    def test_continued_conversation_shows_new_messages_with_a_little_context(self):
        shown, first_new = mp.new_part(self.MSGS, 6)
        self.assertEqual([m["messageNumber"] for m in shown], [3, 4, 5, 6, 7, 8, 9, 10])
        self.assertEqual(first_new, 4)
        text = mp.format_transcript(shown, first_new)
        self.assertEqual(text.splitlines()[4], "--- new messages start here ---")

    def test_speakers_are_labelled(self):
        text = mp.format_transcript([msg(1, "hi"), msg(2, "hello", "assistant")])
        self.assertEqual(text, "Participant: hi\nLexi: hello")

    def test_only_new_participant_text_counts_as_new(self):
        msgs = [msg(1, "hi"), msg(2, "hello", "assistant")]
        self.assertTrue(mp.has_new_participant_text(msgs, 0))
        self.assertFalse(mp.has_new_participant_text(msgs, 1))
        self.assertFalse(mp.has_new_participant_text([msg(1, "opener", "assistant")], 0))

    def test_conversation_date_is_the_newest_participant_message(self):
        msgs = [msg(1, "a", minutes_ago=3000), msg(2, "b", minutes_ago=2000), msg(3, "c", "assistant", minutes_ago=1)]
        self.assertEqual(mp.conversation_date(msgs, NOW), NOW - timedelta(minutes=2000))

    def test_user_content_carries_the_date_and_the_previous_summary(self):
        text = mp.build_user_content(NOW, "Participant: hi", "The user said hi.")
        self.assertIn("Conversation date: 2026-10-26 (Monday)", text)
        self.assertIn("The user said hi.", text)
        self.assertNotIn("Previous summary", mp.build_user_content(NOW, "Participant: hi"))


class ReadingTheModelsAnswer(unittest.TestCase):
    def test_valid_answer(self):
        summary, events = mp.parse_result(json.dumps(GOOD))
        self.assertTrue(summary.startswith("The user talked"))
        self.assertEqual([e["score"] for e in events], [7, 3])
        self.assertEqual(events[0]["when_date"], "2026-10-30")
        self.assertIsNone(events[1]["feeling"])

    def test_a_score_that_is_not_a_number_counts_as_1_not_as_a_failure(self):
        _, events = mp.parse_result(json.dumps({"summary": "s", "events": [{"event": "x", "score": "7/10"}]}))
        self.assertEqual(events[0]["score"], 1)

    def test_scores_are_kept_between_1_and_10(self):
        _, events = mp.parse_result(json.dumps({"summary": "s", "events": [
            {"event": "a", "score": 99}, {"event": "b", "score": -4}]}))
        self.assertEqual(sorted(e["score"] for e in events), [1, 10])

    def test_at_most_five_events_and_the_best_ones(self):
        raw = {"summary": "s", "events": [{"event": f"e{i}", "score": i} for i in range(1, 9)]}
        _, events = mp.parse_result(json.dumps(raw))
        self.assertEqual([e["score"] for e in events], [8, 7, 6, 5, 4])

    def test_a_bad_date_is_dropped_and_an_empty_event_is_skipped(self):
        _, events = mp.parse_result(json.dumps({"summary": "s", "events": [
            {"event": "x", "when_date": "next week"}, {"event": "  "}, "junk"]}))
        self.assertEqual(len(events), 1)
        self.assertIsNone(events[0]["when_date"])

    def test_nothing_worth_keeping_is_fine(self):
        self.assertEqual(mp.parse_result('{"summary": "", "events": []}'), ("", []))

    def test_unusable_answers_raise_so_that_the_run_is_retried(self):
        for bad in ("not json", "[]", ""):
            with self.assertRaises(ValueError):
                mp.parse_result(bad)

    def test_event_documents_keep_the_shape_the_notification_and_the_chat_read(self):
        _, events = mp.parse_result(json.dumps(GOOD))
        docs = mp.make_event_docs(events, str(CONV_ID), NOW, NOW, set())
        d = docs[0]
        for field in ("memory_id", "content", "affective_score", "conversationId", "timestamp_iso", "used"):
            self.assertIn(field, d)
        self.assertFalse(d["used"])
        self.assertEqual(d["content"], "The user is nervous about a presentation on Friday.")
        self.assertEqual(d["conversation_date"], "2026-10-26")
        self.assertEqual(d["reason"], "Clearly felt and time-bound.")

    def test_an_event_already_stored_for_the_conversation_is_not_stored_twice(self):
        _, events = mp.parse_result(json.dumps(GOOD))
        seen = set()
        self.assertEqual(len(mp.make_event_docs(events, "C1", NOW, NOW, seen)), 2)
        self.assertEqual(len(mp.make_event_docs(events, "C1", NOW, NOW, seen)), 0)


class OneConversation(unittest.TestCase):
    def test_success_stores_note_and_events_then_records_progress(self):
        msgs = [msg(1, "hi lexi"), msg(2, "hello", "assistant"), msg(3, "I'm nervous about Friday")]
        db, meta = make_db(msgs)
        llm = llm_returning(GOOD)
        self.assertEqual(mp.process_conversation(db, llm, meta, NOW), "analysed")

        update = db["users"].update_one.call_args.args[1]
        note = update["$set"][f"proactiveMemory.conversation_notes.{CONV_ID}"]
        self.assertTrue(note["summary"].startswith("The user talked"))
        self.assertEqual(len(update["$push"]["proactiveMemory.emotional_memories"]["$each"]), 2)

        final = scan_updates(db)[-1]
        self.assertEqual(final["memory_scan.last_message_number"], 3)
        self.assertEqual(final["memory_scan.scanned_at"], NOW)
        self.assertEqual(final["memory_scan.event_count"], 2)

    def test_the_prompt_and_the_settings_are_the_agreed_ones(self):
        db, meta = make_db([msg(1, "hi")])
        llm = llm_returning(GOOD)
        mp.process_conversation(db, llm, meta, NOW)
        kwargs = llm.call_with_prompt.call_args.kwargs
        self.assertEqual(kwargs["system"], mp.MEMORY_PROMPT)
        self.assertEqual(kwargs["temperature"], 0)
        self.assertTrue(kwargs["json_mode"])
        self.assertIn("Participant: hi", kwargs["user_content"])

    def test_a_failing_model_stores_nothing_and_does_not_advance_progress(self):
        db, meta = make_db([msg(1, "hi")])
        llm = MagicMock()
        llm.call_with_prompt.side_effect = RuntimeError("rate limit")
        self.assertEqual(mp.process_conversation(db, llm, meta, NOW), "failed")
        db["users"].update_one.assert_not_called()
        writes = scan_updates(db)
        self.assertFalse(any("memory_scan.last_message_number" in w for w in writes))
        backoff = db["metadata_conversations"].update_one.call_args.args[1]
        self.assertEqual(backoff["$inc"], {"memory_scan.failures": 1})
        self.assertGreater(backoff["$set"]["memory_scan.lock_until"], NOW)

    def test_an_unusable_answer_is_retried_like_a_failure(self):
        db, meta = make_db([msg(1, "hi")])
        self.assertEqual(mp.process_conversation(db, llm_returning("sorry, I cannot"), meta, NOW), "failed")
        db["users"].update_one.assert_not_called()

    def test_missing_participant_is_a_failure_and_progress_is_not_advanced(self):
        db, meta = make_db([msg(1, "hi")], user_found=False)
        self.assertEqual(mp.process_conversation(db, llm_returning(GOOD), meta, NOW), "failed")
        self.assertFalse(any("memory_scan.last_message_number" in w for w in scan_updates(db)))

    def test_a_conversation_another_run_owns_is_left_alone(self):
        db, meta = make_db([msg(1, "hi")], claim_ok=False)
        llm = llm_returning(GOOD)
        self.assertEqual(mp.process_conversation(db, llm, meta, NOW), "locked")
        llm.call_with_prompt.assert_not_called()

    def test_an_opener_without_a_reply_costs_no_model_call_and_waits(self):
        db, meta = make_db([msg(1, "Feel like chatting?", "assistant")])
        llm = llm_returning(GOOD)
        self.assertEqual(mp.process_conversation(db, llm, meta, NOW), "nothing_new")
        llm.call_with_prompt.assert_not_called()
        self.assertEqual(scan_updates(db)[-1]["memory_scan.last_message_number"], 1)

    def test_a_continued_conversation_is_summarised_again_with_the_previous_summary(self):
        msgs = [msg(1, "hi"), msg(2, "hello", "assistant"), msg(3, "my exam went badly", minutes_ago=5)]
        db, meta = make_db(msgs, meta_scan={"last_message_number": 2, "event_count": 1},
                           notes={str(CONV_ID): {"summary": "The user said hi."}})
        llm = llm_returning({"summary": "The user said hi, then that an exam went badly.", "events": []})
        self.assertEqual(mp.process_conversation(db, llm, meta, NOW), "analysed")
        content = llm.call_with_prompt.call_args.kwargs["user_content"]
        self.assertIn("The user said hi.", content)
        self.assertIn("--- new messages start here ---", content)
        update = db["users"].update_one.call_args.args[1]
        self.assertEqual(update["$set"][f"proactiveMemory.conversation_notes.{CONV_ID}"]["summary"],
                         "The user said hi, then that an exam went badly.")
        self.assertNotIn("$push", update)

    def test_no_events_still_records_the_summary(self):
        db, meta = make_db([msg(1, "hi")])
        mp.process_conversation(db, llm_returning({"summary": "The user said hi.", "events": []}), meta, NOW)
        self.assertNotIn("$push", db["users"].update_one.call_args.args[1])


class ExactlyOnce(unittest.TestCase):
    def ok(self, n=1):
        return MagicMock(modified_count=n, matched_count=n)

    def test_memory_and_progress_are_stored_in_one_transaction(self):
        db, meta = make_db([msg(1, "hi")])
        mp.process_conversation(db, llm_returning(GOOD), meta, NOW)
        self.assertEqual(db.session.transactions, 1)
        self.assertEqual(db.session.aborted, 0)
        self.assertIsNotNone(db["users"].update_one.call_args.kwargs["session"])
        self.assertIsNotNone(db["metadata_conversations"].update_one.call_args.kwargs["session"])

    def test_progress_is_only_advanced_from_the_value_this_run_started_from(self):
        db, meta = make_db([msg(1, "hi"), msg(2, "x", "assistant"), msg(3, "more")], meta_scan={"last_message_number": 2})
        mp.process_conversation(db, llm_returning(GOOD), meta, NOW)
        flt = db["metadata_conversations"].update_one.call_args.args[0]
        self.assertEqual(flt["memory_scan.last_message_number"], 2)

    def test_first_analysis_accepts_a_conversation_with_no_progress_yet(self):
        db, meta = make_db([msg(1, "hi")])
        mp.process_conversation(db, llm_returning(GOOD), meta, NOW)
        flt = db["metadata_conversations"].update_one.call_args.args[0]
        self.assertIn("$or", flt)

    def test_when_another_run_got_there_first_nothing_is_stored_twice(self):
        db, meta = make_db([msg(1, "hi")])
        # claim succeeds, then the progress guard finds the conversation already analysed
        db["metadata_conversations"].update_one.side_effect = [self.ok(1), self.ok(0)]
        self.assertEqual(mp.process_conversation(db, llm_returning(GOOD), meta, NOW), "already_done")
        self.assertEqual(db.session.aborted, 1)   # the whole transaction, including the user write, is rolled back

    def test_a_crash_inside_the_transaction_stores_nothing_and_is_retried_later(self):
        db, meta = make_db([msg(1, "hi")])
        db["users"].update_one.side_effect = RuntimeError("connection lost")
        self.assertEqual(mp.process_conversation(db, llm_returning(GOOD), meta, NOW), "failed")
        self.assertEqual(db.session.aborted, 1)
        self.assertFalse(any("memory_scan.last_message_number" in w for w in scan_updates(db)))

    def test_running_the_same_conversation_twice_asks_the_model_once(self):
        """The second run finds progress == newest message and no new participant text."""
        msgs = [msg(1, "hi"), msg(2, "hello", "assistant")]
        db, meta = make_db(msgs)
        llm = llm_returning(GOOD)
        mp.process_conversation(db, llm, meta, NOW)
        again = dict(meta, memory_scan={"last_message_number": 2, "event_count": 2})
        self.assertEqual(mp.process_conversation(db, llm, again, NOW), "nothing_new")
        self.assertEqual(llm.call_with_prompt.call_count, 1)


class SameForEveryCondition(unittest.TestCase):
    def test_the_pipeline_cannot_see_the_condition(self):
        """It imports no heuristic and no experiment settings, and no function takes a condition."""
        import ast
        with open(mp.__file__, encoding="utf-8") as f:
            tree = ast.parse(f.read())
        imported = set()
        params = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.Import):
                imported.update(a.name for a in node.names)
            elif isinstance(node, ast.FunctionDef):
                params.update(a.arg for a in node.args.args)
        for forbidden in ("heuristics", "research_service", "heuristicWeights"):
            self.assertFalse([i for i in imported if forbidden in i], forbidden)
        self.assertFalse(params & {"condition", "heuristic", "weights", "experiment_id", "settings"})


class Batch(unittest.TestCase):
    def test_every_ready_conversation_is_processed_and_counted(self):
        db, meta = make_db([msg(1, "hi")])
        db["metadata_conversations"].find.return_value.sort.return_value.limit.return_value = [meta, dict(meta)]
        counts = mp.run_pipeline(db, llm_returning(GOOD), now=NOW)
        self.assertEqual(counts["analysed"], 2)


if __name__ == "__main__":
    unittest.main()
