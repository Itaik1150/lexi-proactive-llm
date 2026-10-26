"""Only the study's heuristics are active; the older ones are dormant but still registered."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from heuristics import registry


class Registry(unittest.TestCase):
    def test_only_affective_is_active_for_now(self):
        self.assertEqual([n for n, i in registry.REGISTRY.items() if i.active], ["affective"])

    def test_dormant_heuristics_stay_registered_so_they_can_return(self):
        for name in ("temporal", "behaviouralGap", "generic"):
            self.assertIn(name, registry.REGISTRY)
            self.assertFalse(registry.is_active(name))
            self.assertIsNone(registry.get_class(name))

    def test_the_active_class_can_be_loaded(self):
        self.assertEqual(registry.get_class("affective").__name__, "AffectiveHeuristic")

    def test_every_registered_class_exists(self):
        from importlib import import_module
        for info in registry.REGISTRY.values():
            self.assertTrue(hasattr(import_module(info.module), info.class_name), info.name)

    def test_unknown_name_is_not_active(self):
        self.assertFalse(registry.is_active("nope"))
        self.assertIsNone(registry.get_class("nope"))


class SenderUsesTheRegistry(unittest.TestCase):
    def setUp(self):
        from services.research_service import ResearchService
        self.svc = object.__new__(ResearchService)

    def test_a_dormant_heuristic_in_the_weights_is_never_drawn(self):
        for _ in range(50):
            self.assertEqual(self.svc._select_heuristic({"temporal": 60, "generic": 40}), "reactive")

    def test_active_and_reactive_are_still_drawn(self):
        seen = {self.svc._select_heuristic({"affective": 50, "reactive": 30, "temporal": 20}) for _ in range(300)}
        self.assertEqual(seen, {"affective", "reactive"})

    def test_asking_to_run_a_dormant_heuristic_sends_nothing(self):
        self.assertEqual(self.svc._run_selected_heuristic("temporal", {}, {}), (None, None))


if __name__ == "__main__":
    unittest.main()
