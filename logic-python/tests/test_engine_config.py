"""P9 (docs/REVIEW.md D28): the dashboard shows what the engine really runs."""
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from heuristics import affective
from services import engine_config, memory_pipeline, message_pools, random_schedule


class PublishedConfiguration(unittest.TestCase):
    def setUp(self):
        self.doc = engine_config.build()

    def test_it_carries_the_exact_prompts_the_code_uses(self):
        self.assertEqual(self.doc["memory"]["prompt"], memory_pipeline.MEMORY_PROMPT)
        self.assertEqual(self.doc["affective_notification"]["event_prompt"], affective.EVENT_PROMPT)
        self.assertEqual(self.doc["affective_notification"]["summary_prompt"], affective.SUMMARY_PROMPT)

    def test_it_carries_the_exact_pools(self):
        self.assertEqual(self.doc["standard_notification"]["pool"], list(message_pools.STANDARD_POOL))
        self.assertEqual(self.doc["affective_notification"]["pool"], list(message_pools.AFFECTIVE_POOL))

    def test_it_carries_the_settings(self):
        self.assertEqual(self.doc["memory"]["model"], memory_pipeline.DEFAULT_MEMORY_MODEL)
        self.assertEqual(self.doc["timing"]["min_gap_minutes"], random_schedule.MIN_GAP_MINUTES)
        active = sorted(h["name"] for h in self.doc["heuristics"] if h["active"])
        self.assertEqual(active, ["affective", "generic"])

    def test_publishing_replaces_one_document(self):
        mc = MagicMock()
        mc.connect.return_value = True
        self.assertTrue(engine_config.publish(mc))
        args = mc.db.__getitem__.return_value.replace_one.call_args
        self.assertEqual(args.args[0], {"_id": "engine"})
        self.assertTrue(args.kwargs["upsert"])

    def test_a_database_problem_does_not_stop_the_engine(self):
        mc = MagicMock()
        mc.connect.side_effect = RuntimeError("db down")
        self.assertFalse(engine_config.publish(mc))


if __name__ == "__main__":
    unittest.main()
