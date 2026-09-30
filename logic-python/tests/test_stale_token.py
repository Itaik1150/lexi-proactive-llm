"""S8: only tokens Firebase declares dead may be cleared (docs/REVIEW.md)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from firebase_admin import exceptions as fb_exceptions
from firebase_admin import messaging

from services.research_service import ResearchService

is_stale = ResearchService._is_stale_token_error


class StaleTokenDetection(unittest.TestCase):
    def test_unregistered_token_is_stale(self):
        self.assertTrue(is_stale(messaging.UnregisteredError("Requested entity was not found.")))

    def test_malformed_token_is_stale(self):
        err = fb_exceptions.InvalidArgumentError(
            "The registration token is not a valid FCM registration token")
        self.assertTrue(is_stale(err))

    def test_wrong_project_is_not_stale(self):
        # A misconfigured service account must never opt participants out.
        self.assertFalse(is_stale(messaging.SenderIdMismatchError("SenderId mismatch")))
        self.assertFalse(is_stale(fb_exceptions.NotFoundError("Requested entity was not found.")))

    def test_other_argument_errors_are_not_stale(self):
        self.assertFalse(is_stale(fb_exceptions.InvalidArgumentError("Invalid JSON payload")))

    def test_generic_errors_are_not_stale(self):
        self.assertFalse(is_stale(RuntimeError("not found")))
        self.assertFalse(is_stale(fb_exceptions.UnavailableError("backend unavailable")))


if __name__ == "__main__":
    unittest.main()
