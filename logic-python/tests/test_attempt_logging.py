"""
V2 (docs/REVIEW.md): every attempt to notify a participant writes exactly one proactive_logs row,
whatever the outcome, and rows carry enough context to be analysed on their own.
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

from services import log_schema
from services import research_service as rs_module
from services.research_service import ResearchService

WEIGHTS = {"affective": 100, "temporal": 0, "behaviouralGap": 0, "generic": 0, "reactive": 0}
SCHEDULE = {"mode": "exact", "fireTimes": ["09:00", "13:00"], "randomWindows": [], "allowedDays": list(range(7))}
MESSAGE = {
    "trigger_source": "affective", "generated_message": "Hi, how are you?", "was_fallback": False,
    "memory_content": "a stressful exam", "language": "en", "topic_label": "affective",
}


class BuildLogEntry(unittest.TestCase):
    def test_sent_row_is_complete(self):
        e = log_schema.build_log_entry(
            cycle_id="c1", user_id="u1", status=log_schema.SENT, message=MESSAGE, notification_id="fcm-1",
            conversation_id="conv-1", experiment_id="exp", experiment_type="affective",
            heuristic_weights={"affective": 100}, llm_model="gpt-4o", llm_model_used="gpt-4o",
            daily_quota=2, sent_today_before=1)
        self.assertEqual(e["status"], "sent")
        self.assertEqual(e["heuristic_selected"], "affective")
        self.assertEqual(e["conversation_id"], "conv-1")
        self.assertEqual(e["was_fallback"], False)
        self.assertEqual((e["daily_quota"], e["sent_today_before"]), (2, 1))
        self.assertEqual(e["llm_model_used"], "gpt-4o")
        self.assertIsNone(e["reason"])

    def test_rows_without_a_message_do_not_invent_values(self):
        e = log_schema.build_log_entry(cycle_id="c1", user_id="u1", status=log_schema.SKIPPED_DAY, reason="closed")
        self.assertIsNone(e["was_fallback"], "None, not False: no message existed")
        self.assertIsNone(e["language"])
        self.assertIsNone(e["heuristic_selected"])
        self.assertEqual(e["generated_message"], "")
        self.assertEqual(e["reason"], "closed")

    def test_drawn_heuristic_is_recorded_even_when_nothing_was_generated(self):
        e = log_schema.build_log_entry(cycle_id="c", user_id="u", status=log_schema.REACTIVE, heuristic_selected="reactive")
        self.assertEqual(e["heuristic_selected"], "reactive")

    def test_reason_is_truncated_and_attempts_get_unique_ids(self):
        a = log_schema.build_log_entry(cycle_id="c", user_id="u", status=log_schema.ERROR, reason="x" * 1000)
        b = log_schema.build_log_entry(cycle_id="c", user_id="u", status=log_schema.ERROR)
        self.assertEqual(len(a["reason"]), 300)
        self.assertNotEqual(a["attempt_id"], b["attempt_id"])

    def test_statuses_are_unique(self):
        self.assertEqual(len(set(log_schema.ALL_STATUSES)), len(log_schema.ALL_STATUSES))


class LogProactiveEvent(unittest.TestCase):
    def test_writes_the_built_document_and_never_raises(self):
        svc = object.__new__(ResearchService)
        svc.llm_service = MagicMock(model="claude-x")
        with patch.object(rs_module, "mongodb_client") as db:
            db.connect.return_value = True
            svc.log_proactive_event("c1", "u1", MESSAGE, log_schema.SENT, "fcm-1", conversation_id="conv-1")
            doc = db.db["proactive_logs"].insert_one.call_args.args[0]
            self.assertEqual(doc["llm_model_used"], "claude-x")
            self.assertEqual(doc["conversation_id"], "conv-1")
            db.db["proactive_logs"].insert_one.side_effect = RuntimeError("db down")
            svc.log_proactive_event("c1", "u1", MESSAGE, log_schema.SENT)  # must not raise


class EveryAttemptIsLogged(unittest.TestCase):
    """Drive the real send loop through each outcome and count the rows written."""

    def setUp(self):
        self.user = {"_id": ObjectId(), "username": "dana", "fcmToken": "t" * 150, "experimentId": "exp1"}
        svc = object.__new__(ResearchService)
        svc.llm_service = MagicMock(model="gpt-4o")
        svc.fcm_service = MagicMock()
        svc.fcm_service.send_to_user.return_value = "projects/x/messages/1"
        svc._load_experiment_settings = MagicMock(return_value=(dict(WEIGHTS), {}, dict(SCHEDULE), "gpt-4o", "en"))
        svc._is_today_allowed = MagicMock(return_value=True)
        svc._count_sent_today = MagicMock(return_value=0)
        svc._select_heuristic = MagicMock(return_value="affective")
        self.heuristic = MagicMock(linked_memory_id="m1")
        svc._run_selected_heuristic = MagicMock(return_value=(dict(MESSAGE), self.heuristic))
        svc.inject_prompt = MagicMock(return_value=True)
        svc._create_conversation = MagicMock(return_value="conv-1")
        svc.clear_stale_fcm_token = MagicMock()
        svc.log_proactive_event = MagicMock()
        self.svc = svc
        patcher = patch.object(rs_module, "mongodb_client")
        self.db = patcher.start()
        self.addCleanup(patcher.stop)
        self.db.connect.return_value = True
        self.db.db.__getitem__.return_value.find_one.return_value = {"isProactive": True}

    def run_loop(self):
        self.svc.coordinated_send_and_inject([self.user], "cycle-1")
        calls = self.svc.log_proactive_event.call_args_list
        self.assertEqual(len(calls), 1, "exactly one row per attempt")
        call = calls[0]
        return call.args[3], call.kwargs

    def test_sent(self):
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.SENT)
        self.assertEqual(kw["conversation_id"], "conv-1")
        self.assertEqual((kw["daily_quota"], kw["sent_today_before"]), (2, 0))
        self.assertEqual(kw["heuristic_selected"], "affective")
        self.heuristic.clear_after_send.assert_called_once()

    def test_skipped_day(self):
        self.svc._is_today_allowed.return_value = False
        self.assertEqual(self.run_loop()[0], log_schema.SKIPPED_DAY)
        self.svc._run_selected_heuristic.assert_not_called()

    def test_skipped_quota(self):
        self.svc._count_sent_today.return_value = 2
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.SKIPPED_QUOTA)
        self.assertEqual((kw["daily_quota"], kw["sent_today_before"]), (2, 2))
        self.svc.fcm_service.send_to_user.assert_not_called()

    def test_quota_unverified(self):
        self.svc._count_sent_today.return_value = None
        self.assertEqual(self.run_loop()[0], log_schema.SKIPPED_QUOTA_UNVERIFIED)

    def test_reactive_control_draw(self):
        self.svc._select_heuristic.return_value = "reactive"
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.REACTIVE)
        self.assertEqual(kw["heuristic_selected"], "reactive")

    def test_heuristic_failed(self):
        self.svc._run_selected_heuristic.return_value = (None, None)
        self.assertEqual(self.run_loop()[0], log_schema.HEURISTIC_FAILED)

    def test_injection_failed(self):
        self.svc.inject_prompt.return_value = False
        self.assertEqual(self.run_loop()[0], log_schema.INJECTION_FAILED)

    def test_conversation_failed(self):
        self.svc._create_conversation.return_value = None
        self.assertEqual(self.run_loop()[0], log_schema.CONVERSATION_FAILED)

    def test_dropped_by_gatekeeper(self):
        self.db.db.__getitem__.return_value.find_one.return_value = {"isProactive": False}
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.DROPPED_GATEKEEPER)
        self.assertEqual(kw["conversation_id"], "conv-1")
        self.svc.fcm_service.send_to_user.assert_not_called()

    def test_fcm_exception_is_logged_with_its_reason(self):
        self.svc.fcm_service.send_to_user.side_effect = RuntimeError("quota exceeded")
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.FCM_FAILED)
        self.assertIn("quota exceeded", kw["reason"])
        self.assertEqual(kw["conversation_id"], "conv-1")
        self.svc.clear_stale_fcm_token.assert_not_called()
        self.heuristic.clear_after_send.assert_not_called()

    def test_unexpected_exception_before_fcm_is_logged_as_error(self):
        self.svc._create_conversation.side_effect = ValueError("boom")
        status, kw = self.run_loop()
        self.assertEqual(status, log_schema.ERROR)
        self.assertIn("conversation", kw["reason"])


if __name__ == "__main__":
    unittest.main()
