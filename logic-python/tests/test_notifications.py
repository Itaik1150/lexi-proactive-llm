"""
M4 / M5 (docs/REVIEW.md D13, D18, D19, D25): which event is used, where each notification comes
from (event / summary / pool), the fixed pools, and what is logged.
"""
import os
import random
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bson import ObjectId

from heuristics import affective as aff
from heuristics.affective import AffectiveHeuristic, choose_event, format_day, recent_notes
from heuristics.generic import GenericHeuristic
from services import log_schema, message_pools

TODAY = datetime.now(timezone.utc).date()


def day(offset):
    return (TODAY + timedelta(days=offset)).isoformat()


def event(mid, score, conv_date, used=False, **extra):
    return {"memory_id": mid, "content": f"event {mid}", "affective_score": score,
            "conversation_date": conv_date, "timestamp_iso": conv_date + "T10:00:00", "used": used,
            "conversationId": "c-" + mid, **extra}


# ── M4: which event ─────────────────────────────────────────────────────────

class ChoosingTheEvent(unittest.TestCase):
    def test_highest_score_wins(self):
        self.assertEqual(choose_event([event("a", 5, day(-1)), event("b", 8, day(-9))])["memory_id"], "b")

    def test_equal_scores_the_most_recent_wins(self):
        self.assertEqual(choose_event([event("a", 7, day(-5)), event("b", 7, day(-1))])["memory_id"], "b")

    def test_no_expiry_an_old_event_is_still_used(self):
        self.assertEqual(choose_event([event("old", 6, day(-30))])["memory_id"], "old")

    def test_used_events_and_events_without_id_are_never_chosen(self):
        events = [event("a", 9, day(-1), used=True), {"content": "no id", "affective_score": 10}]
        self.assertIsNone(choose_event(events))


# ── Pools ───────────────────────────────────────────────────────────────────

class Pools(unittest.TestCase):
    def test_sizes_agreed_with_the_owner(self):
        self.assertEqual(len(message_pools.STANDARD_POOL), 20)
        self.assertEqual(len(message_pools.AFFECTIVE_POOL), 8)
        self.assertEqual(len(set(message_pools.STANDARD_POOL)), 20, "no duplicates")

    def test_pools_match_the_documented_lists(self):
        path = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "MESSAGE_POOLS.md")
        with open(path, encoding="utf-8") as f:
            doc = f.read()
        for m in message_pools.STANDARD_POOL + message_pools.AFFECTIVE_POOL:
            self.assertIn(m, doc)

    def test_every_message_is_used_once_before_any_repeats(self):
        rng, state, seen = random.Random(1), None, []
        for _ in range(20):
            i, state = message_pools.pick(20, state, rng)
            seen.append(i)
        self.assertEqual(sorted(seen), list(range(20)))

    def test_never_the_same_message_twice_in_a_row_even_across_rounds(self):
        rng, state, last = random.Random(7), None, None
        for _ in range(500):
            i, state = message_pools.pick(8, state, rng)
            self.assertNotEqual(i, last)
            last = i

    def test_a_broken_state_does_not_break_the_draw(self):
        i, state = message_pools.pick(5, {"used": ["x", 99, -1], "last": "?"}, random.Random(0))
        self.assertIn(i, range(5))
        self.assertEqual(state["used"], [i])


# ── M5: the Affective notification ──────────────────────────────────────────

NOTES = {
    "c1": {"summary": "The user said their dog Rex is sick.", "conversation_date": day(-3)},
    "c2": {"summary": "The user has a big exam on Tuesday.", "conversation_date": day(-1)},
}


def affective(memory, replies=None, error=None):
    h = object.__new__(AffectiveHeuristic)
    h.user_id, h.username, h.name = str(ObjectId()), "dana", "Dana"
    h.user = {"proactiveMemory": memory}
    h.mongodb_client = MagicMock()
    h.mongodb_client.connect.return_value = True
    h.mongodb_client.users_collection = "users"
    h.llm_service = MagicMock()
    if error:
        h.llm_service.call_with_prompt.side_effect = error
    else:
        h.llm_service.call_with_prompt.side_effect = list(replies or [])
    h.used_fallback, h.memory_content = False, ""
    h.linked_memory_id = h.linked_conversation_id = None
    h.message_source, h.memory_age_days, h.llm_attempts = None, None, 0
    h._selected_memory_id, h._pool_previous, h._pool_taken = None, None, False
    h.create_memory = MagicMock()
    h._reload_user = MagicMock()
    return h


SHORT = "How did your exam on Tuesday go, Dana?"
LONG = " ".join(["word"] * 25)


class AffectiveSources(unittest.TestCase):
    def test_event_path_uses_the_agreed_prompt_and_logs_the_event(self):
        h = affective({"emotional_memories": [event("e1", 8, day(-2), when="Tuesday", when_date=day(-1), feeling="nervous")],
                       "conversation_notes": NOTES}, [SHORT])
        self.assertEqual(h.get_proactive_message(), SHORT)
        self.assertEqual(h.message_source, "event")
        self.assertFalse(h.used_fallback)
        self.assertEqual(h.linked_memory_id, "e1")
        self.assertEqual(h.memory_age_days, 2)
        self.assertEqual(h.llm_attempts, 1)
        kwargs = h.llm_service.call_with_prompt.call_args.kwargs
        self.assertEqual(kwargs["system"], aff.EVENT_PROMPT)
        self.assertEqual(kwargs["temperature"], 0.7)
        content = kwargs["user_content"]
        for part in (f"Today: {format_day(TODAY)}", "First name: Dana", "Event: event e1",
                     "Feeling they showed: nervous", "(2 days ago)", "as they said it: Tuesday",
                     "The user said their dog Rex is sick."):
            self.assertIn(part, content)
        self.assertNotIn("8/10", content, "the score is not shown to the model")
        self.assertNotIn("score", content.lower())

    def test_no_unused_event_but_notes_gives_a_summary_message(self):
        h = affective({"emotional_memories": [event("e1", 8, day(-2), used=True)], "conversation_notes": NOTES},
                      ["Hope Rex is feeling better, Dana. How are you?"])
        h.get_proactive_message()
        self.assertEqual(h.message_source, "summary")
        self.assertTrue(h.used_fallback)
        self.assertIsNone(h.linked_memory_id, "no event behind a summary message")
        self.assertEqual(h.llm_service.call_with_prompt.call_args.kwargs["system"], aff.SUMMARY_PROMPT)

    def test_no_notes_at_all_gives_a_pool_message_without_a_model_call(self):
        h = affective({})
        with patch.object(message_pools, "take", return_value=("Just checking in. How are you doing today?", None)) as take:
            text = h.get_proactive_message()
        self.assertEqual(text, "Just checking in. How are you doing today?")
        self.assertEqual(h.message_source, "pool")
        self.assertEqual(take.call_args.args[3], "affective")
        h.llm_service.call_with_prompt.assert_not_called()

    def test_too_long_is_asked_once_more(self):
        h = affective({"emotional_memories": [event("e1", 8, day(-2))]}, [LONG, SHORT])
        self.assertEqual(h.get_proactive_message(), SHORT)
        self.assertEqual(h.llm_attempts, 2)
        self.assertEqual(h.message_source, "event")

    def test_too_long_twice_gives_the_pool_and_the_event_back(self):
        h = affective({"emotional_memories": [event("e1", 8, day(-2))]}, [LONG, LONG])
        with patch.object(message_pools, "take", return_value=("pool text", None)):
            self.assertEqual(h.get_proactive_message(), "pool text")
        self.assertEqual(h.message_source, "pool")
        self.assertIsNone(h.linked_memory_id)
        unuse = [c for c in h.mongodb_client.db.__getitem__.return_value.update_one.call_args_list
                 if c.args[1] == {"$set": {"proactiveMemory.emotional_memories.$[elem].used": False}}]
        self.assertEqual(len(unuse), 1, "the event is given back for a later notification")

    def test_a_failing_model_gives_the_pool(self):
        h = affective({"emotional_memories": [event("e1", 8, day(-2))]}, error=RuntimeError("timeout"))
        with patch.object(message_pools, "take", return_value=("pool text", None)):
            self.assertEqual(h.get_proactive_message(), "pool text")
        self.assertEqual(h.message_source, "pool")

    def test_quotes_around_the_answer_are_removed(self):
        h = affective({"emotional_memories": [event("e1", 8, day(-2))]}, [f'"{SHORT}"'])
        self.assertEqual(h.get_proactive_message(), SHORT)


class TheAgreedPromptText(unittest.TestCase):
    def test_one_limit_15_words_and_the_rules(self):
        for p in (aff.EVENT_PROMPT, aff.SUMMARY_PROMPT):
            self.assertIn("at most 15 words", p)
            self.assertNotIn("20 words", p)
            self.assertIn("first name at most once", p)
            self.assertIn("Never mention memories, notes or summaries.", p)
        self.assertIn("Name the specific event", aff.EVENT_PROMPT)
        self.assertIn("No specific event is available today.", aff.SUMMARY_PROMPT)

    def test_recent_notes_are_dated_and_limited(self):
        notes = {f"c{i}": {"summary": f"s{i}", "conversation_date": day(-i)} for i in range(1, 9)}
        lines = recent_notes(notes)
        self.assertEqual(len(lines), aff.RECENT_NOTES)
        self.assertTrue(lines[-1].endswith("s1"), "newest last")


# ── Standard: the fixed pool ────────────────────────────────────────────────

class StandardPool(unittest.TestCase):
    def make(self):
        h = object.__new__(GenericHeuristic)
        h.user_id, h.username, h.name = str(ObjectId()), "dana", "Dana"
        h.user = {"proactiveMemory": {}}
        h.mongodb_client = MagicMock()
        h._pool_previous, h._pool_taken = None, False
        h.used_fallback, h.memory_content, h.message_source = False, "", None
        h.llm_service = MagicMock()
        return h

    def test_a_standard_message_comes_from_the_pool_without_a_model_or_a_name(self):
        h = self.make()
        text = h.get_proactive_message()
        self.assertIn(text, message_pools.STANDARD_POOL)
        self.assertNotIn("Dana", text)
        self.assertEqual(h.message_source, "pool")
        self.assertFalse(h.used_fallback)
        h.llm_service.call_with_prompt.assert_not_called()

    def test_a_failed_send_gives_the_pool_message_back(self):
        h = self.make()
        h.get_proactive_message()
        with patch.object(message_pools, "restore", return_value=True) as restore:
            self.assertTrue(h.undo_selection())
        self.assertEqual(restore.call_args.args[2], "standard")
        self.assertFalse(h.undo_selection(), "only once")


# ── Logging ─────────────────────────────────────────────────────────────────

class Logged(unittest.TestCase):
    def test_source_event_and_age_are_logged(self):
        entry = log_schema.build_log_entry(cycle_id="c", user_id="u", status="sent", message={
            "generated_message": "x", "message_source": "event", "memory_id": "e1",
            "memory_age_days": 3, "llm_attempts": 2})
        self.assertEqual((entry["message_source"], entry["memory_id"], entry["memory_age_days"], entry["llm_attempts"]),
                         ("event", "e1", 3, 2))

    def test_no_message_means_none_not_a_default(self):
        entry = log_schema.build_log_entry(cycle_id="c", user_id="u", status="reactive")
        self.assertIsNone(entry["message_source"])
        self.assertIsNone(entry["memory_id"])


class InjectionLinkage(unittest.TestCase):
    """A notification with no memory behind it must remove the link left by an earlier one."""

    def inject(self, **links):
        from services import research_service as rs
        svc = object.__new__(rs.ResearchService)
        mc = MagicMock()
        mc.connect.return_value = True
        mc.users_collection = "users"
        col = MagicMock()
        col.find_one.return_value = {"agent": {"firstChatSentence": "Hi"}}
        mc.db.__getitem__.return_value = col
        with patch.object(rs, "mongodb_client", mc):
            self.assertTrue(svc.inject_prompt(str(ObjectId()), "Feel like chatting?", **links))
        return col.update_one.call_args.args[1]

    def test_a_message_without_a_memory_removes_the_old_link(self):
        update = self.inject()
        self.assertEqual(update["$unset"], {"proactiveMemory.linked_memory_id": "",
                                            "proactiveMemory.linked_conversation_id": ""})

    def test_an_event_message_sets_the_link(self):
        update = self.inject(linked_memory_id="e1", linked_conversation_id="c1")
        self.assertEqual(update["$set"]["proactiveMemory.linked_memory_id"], "e1")
        self.assertNotIn("$unset", update)


if __name__ == "__main__":
    unittest.main()
