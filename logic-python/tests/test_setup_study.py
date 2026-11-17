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

    def update_one(self, flt, update):
        doc = self.find_one(flt)
        for path, value in update["$set"].items():
            target = doc
            *parents, last = path.split(".")
            for key in parents:
                target = target.setdefault(key, {})
            target[last] = value


def fake_db():
    return {"agents": FakeCollection(), "forms": FakeCollection(), "experiments": FakeCollection()}


class StudySetup(unittest.TestCase):
    def test_a_dry_run_creates_nothing(self):
        db = fake_db()
        result = ss.setup(db, apply=False, now=NOW)
        self.assertEqual(len(result["created"]), 7)
        self.assertEqual([len(c.docs) for c in db.values()], [0, 0, 0])

    def test_apply_creates_one_agent_one_form_three_experiments(self):
        db = fake_db()
        ss.setup(db, apply=True, now=NOW)
        self.assertEqual([len(db[k].docs) for k in ("agents", "forms", "experiments")], [1, 3, 3])

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
        form = db["forms"].find_one({"name": ss.FORM_NAME})
        self.assertEqual([q["props"]["fieldKey"] for q in form["questions"]], ["open", "enjoyed", "in_control", "start_liked"])
        self.assertEqual({e["experimentForms"]["postConversation"] for e in db["experiments"].docs}, {result["form"]})

    def test_existing_documents_are_never_changed(self):
        db = fake_db()
        db["agents"].docs.append({"_id": "old", "title": ss.AGENT_TITLE, "systemStarterPrompt": "someone edited this"})
        ss.setup(db, apply=True, now=NOW)
        self.assertEqual(db["agents"].docs[0]["systemStarterPrompt"], "someone edited this")
        self.assertEqual(len(db["agents"].docs), 1)


class Questionnaires(unittest.TestCase):
    def setUp(self):
        from tools import study_questionnaires as sq
        self.sq = sq
        self.baseline, self.end = sq.baseline_form(), sq.end_form()

    def keys(self, form):
        return [q["props"]["fieldKey"] for q in form["questions"]]

    def test_the_baseline_shows_the_consent_page_first(self):
        self.assertTrue(self.baseline["termsOfConditions"])
        self.assertNotIn("termsOfConditions", self.end)

    def test_sizes(self):
        self.assertEqual(len(self.baseline["questions"]), 12 + 11 + 8 + 3)
        self.assertEqual(len(self.end["questions"]), 10 + 2 + 7 + 3 + 4 + 4 + 12 + 8 + 3)

    def test_every_question_has_a_unique_key_the_server_will_store(self):
        for form in (self.baseline, self.end):
            keys = self.keys(form)
            self.assertEqual(len(keys), len(set(keys)))
            for key in keys:
                self.assertRegex(key, r"^[A-Za-z0-9_-]{1,64}$")
                self.assertNotIn(key, ("username", "age", "gender"))

    def test_the_shared_core_is_identical_at_baseline_and_at_the_end(self):
        def core(form):
            return [q for q in form["questions"] if q["props"]["fieldKey"].startswith(("uls_", "privacy_"))]
        self.assertEqual(core(self.baseline), core(self.end))
        self.assertEqual(len(core(self.end)), 11)

    def test_every_question_is_required_and_of_a_type_the_app_can_show(self):
        for form in (self.baseline, self.end):
            for q in form["questions"]:
                self.assertIn(q["type"], ("scale-radio", "number-input"))
                self.assertTrue(q["props"]["required"])
                self.assertTrue(q["props"]["label"].strip())

    def test_the_agent_is_called_lexi_everywhere(self):
        text = " ".join(q["props"]["label"] for q in self.end["questions"])
        self.assertNotIn("Pepper", text)
        self.assertIn("Lexi", text)


class FillingTheSlots(unittest.TestCase):
    def test_new_experiments_get_both_questionnaires(self):
        db = fake_db()
        result = ss.setup(db, apply=True, now=NOW)
        for e in db["experiments"].docs:
            self.assertEqual(e["experimentForms"]["registration"], result["baseline"])
            self.assertEqual(e["studySettings"]["endSurveyForm"], result["end"])

    def test_an_empty_slot_of_an_existing_experiment_is_filled_and_a_set_one_is_kept(self):
        db = fake_db()
        ss.setup(db, apply=True, now=NOW)
        first, second = db["experiments"].docs[0], db["experiments"].docs[1]
        first["experimentForms"]["registration"] = None          # as created before the questionnaires existed
        second["studySettings"]["endSurveyForm"] = "chosen-by-hand"
        result = ss.setup(db, apply=True, now=NOW)
        self.assertEqual(first["experimentForms"]["registration"], result["baseline"])
        self.assertEqual(second["studySettings"]["endSurveyForm"], "chosen-by-hand")
        self.assertEqual(len(result["filled"]), 1)

    def test_a_dry_run_fills_nothing(self):
        db = fake_db()
        ss.setup(db, apply=True, now=NOW)
        db["experiments"].docs[0]["experimentForms"]["registration"] = None
        result = ss.setup(db, apply=False, now=NOW)
        self.assertEqual(len(result["filled"]), 1)
        self.assertIsNone(db["experiments"].docs[0]["experimentForms"]["registration"])


if __name__ == "__main__":
    unittest.main()
