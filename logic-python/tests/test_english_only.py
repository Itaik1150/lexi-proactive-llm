"""I4 (docs/REVIEW.md, D8): the study runs in English only."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from unittest.mock import MagicMock

from heuristics.base_heuristic import BaseHeuristic
from heuristics.generic import GenericHeuristic

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
HEBREW = re.compile("[֐-׿]")
SKIP = {"node_modules", "venv", ".venv", "Archive", "archive", "build", ".git", ".gradle", "__pycache__", "dist", "docs"}


class EnglishOnly(unittest.TestCase):
    def test_no_hebrew_text_anywhere_in_the_code(self):
        found = []
        for base in ("logic-python", os.path.join("Lexi", "server", "src"), os.path.join("Lexi", "client", "src"),
                     os.path.join("android-app", "app", "src")):
            for root, dirs, files in os.walk(os.path.join(ROOT, base)):
                dirs[:] = [d for d in dirs if d not in SKIP]
                for f in files:
                    if os.path.splitext(f)[1] in {".py", ".ts", ".tsx", ".kt", ".xml", ".json"}:
                        path = os.path.join(root, f)
                        if os.path.abspath(path) == os.path.abspath(__file__):
                            continue
                        try:
                            with open(path, encoding="utf-8") as fh:
                                if HEBREW.search(fh.read()):
                                    found.append(os.path.relpath(path, ROOT))
                        except (UnicodeDecodeError, OSError):
                            pass
        self.assertEqual(found, [])

    def test_a_participant_stored_as_hebrew_still_gets_english(self):
        user = {"_id": "64b7f0f0f0f0f0f0f0f0f0f0", "username": "dana", "language": "he",
                "proactiveMemory": {"preferred_language": "he"}}
        h = GenericHeuristic(user=user, llm_service=MagicMock(), mongodb_client=MagicMock(), default_language="he")
        self.assertEqual(h.language, "en")
        self.assertEqual(h._target_lang, "English")

    def test_hebrew_messages_do_not_switch_the_language(self):
        self.assertIsNone(BaseHeuristic._detect_language(["שלום מה נשמע"]))


if __name__ == "__main__":
    unittest.main()
