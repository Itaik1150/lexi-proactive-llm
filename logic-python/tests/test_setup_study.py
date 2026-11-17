"""The study's three experiments are created from one template (docs/REVIEW.md P1, final check E1)."""
import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from tools import setup_study as ss

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


class FakeCollection:
    def __init__(self):
        self.docs = []

    def find_one(self, flt):
        return next((d for d in self.docs if all(d.get(k) == v for k, v in flt.items())), None)

    def insert_one(self, doc):
        self.docs.append(doc)


def fake_db():
    return {"agents": FakeCollection(), "forms": FakeCollection(), "experiments": FakeCollection()}


class StudySetup(unittest.TestCase):
    def test_a_dry_run_creates_nothing(self):
        db = fake_db()
        result = ss.setup(db, apply=False, now=NOW)
        self.assertEqual(len(result["created"]), 5)
        self.assertEqual([len(c.docs) for c in db.values()], [0, 0, 0])

    def test_apply_creates_one_agent_one_form_three_experiments(self):
        db = fake_db()
        ss.setup(db, apply=True, now=NOW)
        self.assertEqual([len(db[k].docs) for k in ("agents", "forms", "experiments")], [1, 1, 3])

    def test_running_it_again_changes_nothing(self):
        db = fake_db()
        first = ss.setup(db, apply=True, now=NOW)
        second = ss.setup(db, apply=True, now=NOW)
        self.assertEqual(second["created"], [])
        self.assertEqual(second["experiments"], first["experiments"])
        self.assertEqual(len(db["experiments"].docs), 3)

    def test_the_three_experiments_differ_only_in_their_condition(self):
        db = fake_db()
        ss.setup(db, apply=True, now=NOW)
        a, b, c = db["experiments"].docs
        allowed = {"_id", "title", "description", "experimentFeatures.proactiveSettings.heuristicWeights.affective",
                   "experimentFeatures.proactiveSettings.heuristicWeights.generic",
                   "experimentFeatures.proactiveSettings.heuristicWeights.reactive"}
        for x, y in ((a, b), (a, c), (b, c)):
            self.assertLessEqual(set(ss.differences(x, y)), allowed)

    def test_one_condition_per_experiment_with_weight_100(self):
        db = fake_db()
        ss.setup(db, apply=True, now=NOW)
        active = []
        for e in db["experiments"].docs:
            w = e["experimentFeatures"]["proactiveSettings"]["heuristicWeights"]
            on = [k for k, v in w.items() if v > 0]
            self.assertEqual(len(on), 1)
            self.assertEqual(w[on[0]], 100)
            active.append(on[0])
        self.assertEqual(sorted(active), ["affective", "generic", "reactive"])

    def test_titles_that_participants_see_do_not_reveal_the_condition(self):
        for title, _, _ in ss.CONDITIONS:
            for word in ("reactive", "standard", "affective", "proactive", "neutral", "warm", "control", "baseline"):
                self.assertNotIn(word, title.lower())

    def test_timing_is_the_study_rule_in_all_three(self):
        db = fake_db()
        ss.setup(db, apply=True, now=NOW)
        for e in db["experiments"].docs:
            schedule = e["experimentFeatures"]["proactiveSettings"]["schedule"]
            self.assertEqual(schedule["mode"], "random")
            self.assertEqual(schedule["randomWindows"], [{"start": "09:00", "end": "19:00", "count": 2}])
            self.assertEqual(e["studySettings"]["durationDays"], 14)

    def test_one_shared_agent_with_the_agreed_settings(self):
        db = fake_db()
        result = ss.setup(db, apply=True, now=NOW)
        agent = db["agents"].docs[0]
        self.assertEqual((agent["model"], agent["temperature"]), ("gpt-4o", 0.7))
        self.assertIn("7. Safety:", agent["systemStarterPrompt"])
        self.assertEqual({e["activeAgent"] for e in db["experiments"].docs}, {result["agent"]})

    def test_the_same_four_questions_after_every_conversation(self):
        db = fake_db()
        result = ss.setup(db, apply=True, now=NOW)
        form = db["forms"].docs[0]
        self.assertEqual([q["props"]["fieldKey"] for q in form["questions"]], ["open", "enjoyed", "in_control", "start_liked"])
        self.assertEqual({e["experimentForms"]["postConversation"] for e in db["experiments"].docs}, {result["form"]})

    def test_existing_documents_are_never_changed(self):
        db = fake_db()
        db["agents"].docs.append({"_id": "old", "title": ss.AGENT_TITLE, "systemStarterPrompt": "someone edited this"})
        ss.setup(db, apply=True, now=NOW)
        self.assertEqual(db["agents"].docs[0]["systemStarterPrompt"], "someone edited this")
        self.assertEqual(len(db["agents"].docs), 1)


if __name__ == "__main__":
    unittest.main()
