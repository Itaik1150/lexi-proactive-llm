"""
Structure of one `proactive_logs` document. One document is written for EVERY attempt to
notify a participant, not only for successful sends, so the analysis has real denominators.
See docs/DATA_AND_ANALYSIS.md for how to query it.

The Node API later adds two timestamps to rows with status "sent" (funnel):
  opened_at       first time the participant's app fetched the notification's conversation
  first_reply_at  first message the participant wrote in that conversation
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

# Outcomes ------------------------------------------------------------------------------
SENT = "sent"                                  # FCM accepted the message
FCM_FAILED = "fcm_failed"                      # push could not be delivered to FCM
DROPPED_GATEKEEPER = "dropped_gatekeeper"      # participant switched off between draw and send
CONVERSATION_FAILED = "conversation_failed"    # the opener conversation could not be pre-created
INJECTION_FAILED = "injection_failed"          # the opener could not be written to the user document
HEURISTIC_FAILED = "heuristic_failed"          # the drawn heuristic raised or returned nothing
REACTIVE = "reactive"                          # control draw: nothing is sent, by design
SKIPPED_DAY = "skipped_day"                    # today is not an allowed weekday
SKIPPED_QUOTA = "skipped_quota"                # participant already received today's quota
SKIPPED_QUOTA_UNVERIFIED = "skipped_quota_unverified"  # could not count today's sends, so did not risk it
ERROR = "error"                                # unexpected exception; see `reason`

ALL_STATUSES = (
    SENT, FCM_FAILED, DROPPED_GATEKEEPER, CONVERSATION_FAILED, INJECTION_FAILED,
    HEURISTIC_FAILED, REACTIVE, SKIPPED_DAY, SKIPPED_QUOTA, SKIPPED_QUOTA_UNVERIFIED, ERROR,
)


def build_log_entry(
    *,
    cycle_id: str,
    user_id: str,
    status: str,
    message: Optional[dict] = None,
    reason: Optional[str] = None,
    notification_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    experiment_id: Optional[str] = None,
    experiment_type: Optional[str] = None,
    heuristic_selected: Optional[str] = None,
    heuristic_weights: Optional[dict] = None,
    llm_model: Optional[str] = None,
    llm_model_used: Optional[str] = None,
    daily_quota: Optional[int] = None,
    sent_today_before: Optional[int] = None,
    now: Optional[datetime] = None,
) -> dict:
    """
    Build the document. `message` is the dict returned by ResearchService._run_selected_heuristic
    (present only when a message was generated). Fields that do not apply to an outcome are None,
    never a misleading default: e.g. `was_fallback` is None (not False) when no message existed.
    """
    message = message or {}
    drawn = heuristic_selected or message.get("trigger_source")
    return {
        "attempt_id":                 str(uuid.uuid4()),
        "cycle_id":                   cycle_id,
        "timestamp":                  now or datetime.now(timezone.utc),
        "user_id":                    user_id,
        "experiment_id":              experiment_id or "",
        "experiment_type":            experiment_type or "",
        "status":                     status,
        "reason":                     (reason or None) and str(reason)[:300],
        # heuristic that was DRAWN for this attempt (None for outcomes before the draw);
        # trigger_source is the same value, kept for older queries.
        "heuristic_selected":         drawn,
        "trigger_source":             drawn,
        "generated_message":          message.get("generated_message", ""),
        "was_fallback":               message.get("was_fallback") if message else None,
        "memory_content":             message.get("memory_content", ""),
        "language":                   message.get("language") if message else None,
        "topic_label":                message.get("topic_label", drawn or ""),
        "conversation_id":            conversation_id,
        "notification_id":            notification_id,
        "heuristic_weights_snapshot": heuristic_weights or {},
        "llm_model":                  llm_model or "",       # what the experiment asked for
        "llm_model_used":             llm_model_used or "",  # what the engine actually called
        "daily_quota":                daily_quota,           # notifications/day the schedule allows
        "sent_today_before":          sent_today_before,     # sends already logged today at decision time
    }
