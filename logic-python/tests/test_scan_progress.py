"""
V6 (docs/REVIEW.md): conversations are analysed per participant message, not once and never again.
"""
import json
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# The engine prints emoji; a Windows console or pipe using cp1252 would crash on them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bson import ObjectId

from heuristics.behavioural_gap import BehaviouralGapHeuristic
from heuristics.temporal import TemporalHeuristic
from services import scan_progress


def msg(n, text, role="user"):
    return {"messageNumber": n, "role": role, "content": text}


class ScanProgressHelpers(unittest.TestCase):
    def test_user_messages_keeps_text_and_orders_by_number(self):
        raw = [msg(6, "c"), msg(2, "a"), {"messageNumber": 4, "content": ""}, msg(3, "b")]
        self.assertEqual([m["n"] for m in scan_progress.user_messages(raw)], [2, 3, 6])

    def test_only_messages_after_the_recorded_progress_are_new(self):
        msgs = scan_progress.user_messages([msg(2, "a"), msg(4, "b"), msg(6, "c")])
        new, migrate = scan_progress.plan_conversation("C1", msgs, {"C1": 4})
        self.assertEqual([m["n"] for m in new], [6])
        self.assertIsNone(migrate)

    def test_an_empty_conversation_has_nothing_to_analyse_and_nothing_to_record(self):
        new, migrate = scan_progress.plan_conversation("C1", [], {})
        self.assertEqual((new, migrate), ([], None))

    def test_a_conversation_from_the_old_scheme_is_migrated_not_reanalysed(self):
        msgs = scan_progress.user_messages([msg(2, "a"), msg(4, "b")])
        new, migrate = scan_progress.plan_conversation("C1", msgs, {}, legacy_ids=["C1"])
        self.assertEqual((new, migrate), ([], 4))
        # once migrated, later messages are new
        msgs.append({"n": 6, "text": "c"})
        new, migrate = scan_progress.plan_conversation("C1", msgs, {"C1": 4}, legacy_ids=["C1"])
        self.assertEqual([m["n"] for m in new], [6])
        self.assertIsNone(migrate)

    def test_normalize_ignores_case_and_spacing(self):
        self.assertEqual(scan_progress.normalize("  I FAILED   my exam "), scan_progress.normalize("i failed my exam"))


class FakeWorld:
    """In-memory stand-in for the three collections the heuristics read and write."""

    def __init__(self, conversations):
        # conversations: ordered NEWEST FIRST, [(conversation_id, [message docs incl. assistant ones])]
        self.order = [cid for cid, _ in conversations]
        self.messages = dict(conversations)
        self.users = MagicMock()
        self.users.find_one.return_value = {}
        metadata = MagicMock()
        metadata.find.side_effect = lambda filt, sort=None, limit=None: [{"_id": c} for c in self.order][:limit]
        convs = MagicMock()
        convs.find.side_effect = lambda filt, sort=None, **kw: [
            m for m in self.messages[filt["conversationId"]] if m["role"] == filt.get("role", m["role"])
        ]
        cols = {"metadata_conversations": metadata, "conversations": convs, "users": self.users}
        self.client = MagicMock()
        self.client.connect.return_value = True
        self.client.users_collection = "users"
        self.client.db.__getitem__.side_effect = lambda name: cols[name]

    def last_update(self):
        return self.users.update_one.call_args.args[1] if self.users.update_one.called else None


def make(cls, world, memory=None, llm_reply=None, llm_error=None):
    llm = MagicMock()
    if llm_error:
        llm.call_with_prompt.side_effect = llm_error
    else:
        llm.call_with_prompt.return_value = json.dumps(llm_reply or {})
    user = {"_id": ObjectId(), "username": "dana", "proactiveMemory": memory or {}}
    h = cls(user=user, llm_service=llm, mongodb_client=world.client, prompts_from_db={}, default_language="en")
    return h, llm


def sent_to_llm(llm, call=0):
    return llm.call_with_prompt.call_args_list[call].kwargs["user_content"]


EXAM = {"emotional_memories": [{"content": "failed my exam", "affective_score": 8}], "conversation_summary": "exam"}


class GapScanning(unittest.TestCase):
    INTENT = {"intents": [{"intent": "go to the gym"}]}

    def test_a_grown_conversation_is_rescanned_for_new_messages_only(self):
        world = FakeWorld([("C1", [msg(2, "old plan talk"), msg(4, "I will go to the gym tomorrow")])])
        h, llm = make(BehaviouralGapHeuristic, world, {"gap_scan_progress": {"C1": 2}}, llm_reply=self.INTENT)
        h.create_memory()
        content = sent_to_llm(llm)
        self.assertIn("go to the gym tomorrow", content)
        self.assertNotIn("old plan talk", content)
        update = world.last_update()
        self.assertEqual(update["$set"]["proactiveMemory.gap_scan_progress.C1"], 4)
        self.assertEqual(update["$set"]["proactiveMemory.open_intents"][0]["intent"], "go to the gym")

    def test_an_empty_conversation_is_not_marked_scanned(self):
        world = FakeWorld([("C1", [msg(1, "Hello", "assistant")])])
        h, llm = make(BehaviouralGapHeuristic, world, llm_reply=self.INTENT)
        h.create_memory()
        llm.call_with_prompt.assert_not_called()
        update = world.last_update() or {}
        self.assertFalse(any("gap_scan_progress" in k for k in update.get("$set", {})))

    def test_a_failed_extraction_is_retried_not_skipped(self):
        world = FakeWorld([("C1", [msg(2, "I will go to the gym")])])
        h, _ = make(BehaviouralGapHeuristic, world, llm_error=RuntimeError("timeout"))
        h.create_memory()
        update = world.last_update() or {}
        self.assertFalse(any("gap_scan_progress" in k for k in update.get("$set", {})))

    def test_old_scheme_conversations_are_migrated_without_new_llm_calls(self):
        world = FakeWorld([("C1", [msg(2, "I will go to the gym"), msg(4, "ok")])])
        h, llm = make(BehaviouralGapHeuristic, world, {"gap_scanned_conversation_ids": ["C1"]}, llm_reply=self.INTENT)
        h.create_memory()
        llm.call_with_prompt.assert_not_called()
        self.assertEqual(world.last_update()["$set"]["proactiveMemory.gap_scan_progress.C1"], 4)


class TemporalScanning(unittest.TestCase):
    EVENT = {"future_mentions": [{"text": "job interview", "when_iso": "2026-11-02T10:00:00+00:00"}]}

    def test_each_message_is_analysed_once(self):
        world = FakeWorld([("C1", [msg(2, "I have a job interview on Monday")])])
        h, llm = make(TemporalHeuristic, world, llm_reply=self.EVENT)
        h.create_memory()
        self.assertEqual(llm.call_with_prompt.call_count, 1)
        update = world.last_update()
        self.assertEqual(update["$set"]["proactiveMemory.temporal_scan_progress.C1"], 2)
        self.assertEqual(update["$push"]["proactiveMemory.future_mentions"]["$each"][0]["text"], "job interview")

        # next cycle: nothing new, so no LLM call at all (it used to re-read the newest 5 every time)
        h2, llm2 = make(TemporalHeuristic, world, {"temporal_scan_progress": {"C1": 2}}, llm_reply=self.EVENT)
        h2.create_memory()
        llm2.call_with_prompt.assert_not_called()

    def test_new_messages_in_an_old_conversation_are_picked_up(self):
        world = FakeWorld([("C1", [msg(2, "hi"), msg(4, "dentist on Friday")])])
        h, llm = make(TemporalHeuristic, world, {"temporal_scan_progress": {"C1": 2}}, llm_reply=self.EVENT)
        h.create_memory()
        self.assertIn("dentist on Friday", sent_to_llm(llm))
        self.assertNotIn("hi\n", sent_to_llm(llm) + "\n")

    def test_a_failed_extraction_keeps_the_messages_pending(self):
        world = FakeWorld([("C1", [msg(2, "interview Monday")])])
        h, _ = make(TemporalHeuristic, world, llm_error=RuntimeError("down"))
        h.create_memory()
        update = world.last_update() or {}
        self.assertFalse(any("temporal_scan_progress" in k for k in update.get("$set", {})))


if __name__ == "__main__":
    unittest.main()
