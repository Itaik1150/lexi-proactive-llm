"""
V3 and V4 (docs/REVIEW.md): a send that fails after the opener was injected is rolled back, and the
model is selected per participant instead of leaking from the previous one.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("SERVICE_ACCOUNT_JSON_CONTENT", "{}")

# The engine prints emoji; a Windows console or pipe using cp1252 would crash on them.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from bson import ObjectId

from heuristics.affective import AffectiveHeuristic
from services import injection_state, log_schema
from services import research_service as rs_module
from services.llm_service import ProactiveLogic
from services.research_service import ResearchService

WEIGHTS = {"affective": 100, "temporal": 0, "behaviouralGap": 0, "generic": 0, "reactive": 0}
SCHEDULE = {"mode": "exact", "fireTimes": ["09:00"], "randomWindows": [], "allowedDays": list(range(7))}
MESSAGE = {"trigger_source": "affective", "generated_message": "Hi!", "was_fallback": False,
           "memory_content": "exam", "language": "en", "topic_label": "affective"}
SNAPSHOT = {"first_chat_sentence": "Hello!", "injected_prompt_original": None,
            "linked_memory_id": None, "linked_conversation_id": None}


class InjectionStateHelpers(unittest.TestCase):
    def test_snapshot_reads_the_four_fields(self):
        doc = {"agent": {"firstChatSentence": "Hi"}, "proactiveMemory": {"injected_prompt_original": "Old", "linked_memory_id": "m"}}
        snap = injection_state.snapshot_from_user_doc(doc)
        self.assertEqual(snap, {"first_chat_sentence": "Hi", "injected_prompt_original": "Old",
                                "linked_memory_id": "m", "linked_conversation_id": None})
        self.assertIsNone(injection_state.snapshot_from_user_doc(None))

    def test_restore_sets_what_existed_and_removes_what_did_not(self):
        to_set, to_unset = injection_state.restore_update(SNAPSHOT)
        self.assertEqual(to_set, {"agent.firstChatSentence": "Hello!"})
        self.assertEqual(set(to_unset), {
            "proactiveMemory.injected_prompt_original",
            "proactiveMemory.linked_memory_id",
            "proactiveMemory.linked_conversation_id",
        })


class RollbackOfFailedSends(unittest.TestCase):
    def setUp(self):
        self.user = {"_id": ObjectId(), "username": "dana", "fcmToken": "t" * 150, "experimentId": str(ObjectId())}
        svc = object.__new__(ResearchService)
        svc.llm_service = MagicMock(model="gpt-4o")
        svc.fcm_service = MagicMock()
        svc.fcm_service.send_to_user.return_value = "fcm-1"
        svc._load_experiment_settings = MagicMock(return_value=(dict(WEIGHTS), {}, dict(SCHEDULE), "gpt-4o", "en"))
        svc._is_today_allowed = MagicMock(return_value=True)
        svc._count_sent_today = MagicMock(return_value=0)
        svc._select_heuristic = MagicMock(return_value="affective")
        self.heuristic = MagicMock(linked_memory_id="m1")
        self.heuristic.undo_selection.return_value = True
        svc._run_selected_heuristic = MagicMock(return_value=(dict(MESSAGE), self.heuristic))
        svc.inject_prompt = MagicMock(return_value=True)
        svc._snapshot_injection_state = MagicMock(return_value=dict(SNAPSHOT))
        svc._restore_injection_state = MagicMock(return_value=True)
        svc._discard_conversation = MagicMock(return_value=True)
        svc._create_conversation = MagicMock(return_value="conv-1")
        svc.clear_stale_fcm_token = MagicMock()
        svc.log_proactive_event = MagicMock()
        self.svc = svc
        patcher = patch.object(rs_module, "mongodb_client")
        self.db = patcher.start()
        self.addCleanup(patcher.stop)
        self.db.connect.return_value = True
        self.db.db.__getitem__.return_value.find_one.return_value = {"isProactive": True}
        self.exp = self.user["experimentId"]

    def run_loop(self):
        self.svc.coordinated_send_and_inject([self.user], "cycle-1")
        self.assertEqual(self.svc.log_proactive_event.call_count, 1)
        call = self.svc.log_proactive_event.call_args
        return call.args[3], call.kwargs

    def test_successful_send_is_left_alone(self):
        status, _ = self.run_loop()
        self.assertEqual(status, log_schema.SENT)
        self.svc._restore_injection_state.assert_not_called()
        self.svc._discard_conversation.assert_not_called()
        self.heuristic.undo_selection.assert_not_called()
        self.heuristic.clear_after_send.assert_called_once()

    def test_fcm_exception_undoes_everything(self):
        self.svc.fcm_service.send_to_user.side_effect = RuntimeError("fcm down")
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.FCM_FAILED)
        self.svc._restore_injection_state.assert_called_once_with(str(self.user["_id"]), SNAPSHOT)
        self.svc._discard_conversation.assert_called_once_with(str(self.user["_id"]), self.exp, "conv-1")
        self.heuristic.undo_selection.assert_called_once()
        self.heuristic.clear_after_send.assert_not_called()
        for step in ("greeting restored", "conversation discarded", "memory un-used"):
            self.assertIn(step, kw["reason"])

    def test_fcm_returning_nothing_is_rolled_back_too(self):
        self.svc.fcm_service.send_to_user.return_value = None
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.FCM_FAILED)
        self.svc._discard_conversation.assert_called_once()
        self.assertIn("rolled back", kw["reason"])

    def test_gatekeeper_drop_restores_greeting_and_creates_no_conversation(self):
        self.db.db.__getitem__.return_value.find_one.return_value = {"isProactive": False}
        status, _ = self.run_loop()
        self.assertEqual(status, log_schema.DROPPED_GATEKEEPER)
        self.svc._create_conversation.assert_not_called()
        self.svc._restore_injection_state.assert_called_once()
        self.svc._discard_conversation.assert_not_called()
        self.heuristic.undo_selection.assert_called_once()

    def test_conversation_failure_restores_greeting(self):
        self.svc._create_conversation.return_value = None
        status, _ = self.run_loop()
        self.assertEqual(status, log_schema.CONVERSATION_FAILED)
        self.svc._restore_injection_state.assert_called_once()
        self.svc._discard_conversation.assert_not_called()
        self.heuristic.undo_selection.assert_called_once()

    def test_failed_injection_gives_the_memory_back(self):
        self.svc.inject_prompt.return_value = False
        status, _ = self.run_loop()
        self.assertEqual(status, log_schema.INJECTION_FAILED)
        self.heuristic.undo_selection.assert_called_once()

    def test_unreadable_user_state_means_no_send(self):
        self.svc._snapshot_injection_state.return_value = None
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.INJECTION_FAILED)
        self.svc.inject_prompt.assert_not_called()
        self.svc.fcm_service.send_to_user.assert_not_called()
        self.heuristic.undo_selection.assert_called_once()
        self.assertIn("snapshot", kw["reason"])

    def test_a_failing_rollback_step_never_breaks_the_cycle_and_others_still_run(self):
        self.svc.fcm_service.send_to_user.side_effect = RuntimeError("fcm down")
        self.svc._restore_injection_state.side_effect = RuntimeError("db hiccup")
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.FCM_FAILED)
        self.svc._discard_conversation.assert_called_once()
        self.heuristic.undo_selection.assert_called_once()
        self.assertNotIn("greeting restored", kw["reason"])
        self.assertIn("conversation discarded", kw["reason"])


class DiscardConversation(unittest.TestCase):
    def setUp(self):
        self.svc = object.__new__(ResearchService)
        patcher = patch.object(rs_module, "mongodb_client")
        self.mc = patcher.start()
        self.addCleanup(patcher.stop)
        self.mc.connect.return_value = True
        self.mc.users_collection = "users"
        self.cols = {n: MagicMock() for n in ("conversations", "metadata_conversations", "users", "experiments")}
        self.mc.db.__getitem__.side_effect = lambda name: self.cols[name]
        self.uid, self.eid, self.cid = str(ObjectId()), str(ObjectId()), str(ObjectId())

    def test_deletes_the_opener_and_reverses_the_counters(self):
        self.cols["conversations"].count_documents.return_value = 0
        self.assertTrue(self.svc._discard_conversation(self.uid, self.eid, self.cid))
        self.cols["conversations"].delete_many.assert_called_once_with({"conversationId": self.cid})
        self.cols["metadata_conversations"].delete_one.assert_called_once_with({"_id": ObjectId(self.cid)})
        users_args = self.cols["users"].update_one.call_args.args
        self.assertEqual(users_args[1], {"$inc": {"numberOfConversations": -1}})
        self.assertEqual(users_args[0]["numberOfConversations"], {"$gt": 0}, "never goes below zero")
        exp_args = self.cols["experiments"].update_one.call_args.args
        self.assertEqual(exp_args[1], {"$inc": {"totalSessions": -1, "openSessions": -1}})

    def test_never_deletes_a_conversation_the_participant_wrote_in(self):
        self.cols["conversations"].count_documents.return_value = 1
        self.assertFalse(self.svc._discard_conversation(self.uid, self.eid, self.cid))
        self.cols["conversations"].delete_many.assert_not_called()
        self.cols["metadata_conversations"].delete_one.assert_not_called()
        self.cols["users"].update_one.assert_not_called()


class AffectiveUndo(unittest.TestCase):
    def make(self):
        h = object.__new__(AffectiveHeuristic)
        h.mongodb_client = MagicMock()
        h.mongodb_client.connect.return_value = True
        h.mongodb_client.users_collection = "users"
        col = MagicMock()
        h.mongodb_client.db.__getitem__.return_value = col
        h.user_id = str(ObjectId())
        h.username = "dana"
        return h, col

    def test_gives_the_selected_memory_back_by_id(self):
        h, col = self.make()
        h._selected_memory_id = "abcdef1234567890"
        self.assertTrue(h.undo_selection())
        kwargs = col.update_one.call_args.kwargs
        self.assertEqual(kwargs["array_filters"], [{"elem.memory_id": "abcdef1234567890"}])
        self.assertEqual(col.update_one.call_args.args[1],
                         {"$set": {"proactiveMemory.emotional_memories.$[elem].used": False}})
        self.assertIsNone(h._selected_memory_id)

    def test_nothing_selected_means_nothing_to_undo(self):
        h, col = self.make()
        self.assertFalse(h.undo_selection())
        col.update_one.assert_not_called()


class ModelIsSelectedPerParticipant(unittest.TestCase):
    def make(self):
        env = {"LLM_PROVIDER": "openai", "LLM_MODEL": "gpt-4o", "OPENAI_API_KEY": "k", "ANTHROPIC_API_KEY": "a"}
        with patch.dict(os.environ, env):
            return ProactiveLogic()

    def test_experiment_model_does_not_leak_to_the_next_participant(self):
        llm = self.make()
        llm.use_model("claude-3-5-sonnet-20241022")
        self.assertEqual((llm.provider, llm.model), ("anthropic", "claude-3-5-sonnet-20241022"))
        llm.use_model(None)
        self.assertEqual((llm.provider, llm.model), ("openai", "gpt-4o"), "back to the default")
        llm.use_model("")
        self.assertEqual((llm.provider, llm.model), ("openai", "gpt-4o"))

    def test_switching_between_experiments_models(self):
        llm = self.make()
        llm.use_model("gpt-4o-mini")
        self.assertEqual((llm.provider, llm.model), ("openai", "gpt-4o-mini"))
        llm.use_model("claude-x")
        self.assertEqual(llm.provider, "anthropic")
        llm.use_model("gpt-4o-mini")
        self.assertEqual((llm.provider, llm.model), ("openai", "gpt-4o-mini"))

    def test_the_loop_selects_the_model_for_every_participant(self):
        svc = object.__new__(ResearchService)
        svc.llm_service = MagicMock(model="gpt-4o")
        svc._load_experiment_settings = MagicMock(side_effect=[
            (dict(WEIGHTS), {}, dict(SCHEDULE), "claude-x", "en"),   # experiment A sets a model
            (dict(WEIGHTS), {}, dict(SCHEDULE), None, "en"),         # experiment B sets none
        ])
        svc._is_today_allowed = MagicMock(return_value=True)
        svc._count_sent_today = MagicMock(return_value=0)
        svc._select_heuristic = MagicMock(return_value="reactive")  # stop right after model selection
        svc.log_proactive_event = MagicMock()
        users = [{"_id": ObjectId(), "username": n, "fcmToken": "t" * 150, "experimentId": "e"} for n in ("a", "b")]
        svc.coordinated_send_and_inject(users, "c")
        self.assertEqual([c.args[0] for c in svc.llm_service.use_model.call_args_list], ["claude-x", None])


if __name__ == "__main__":
    unittest.main()
