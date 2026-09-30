# Data & Analysis Guide

What gets written to MongoDB, what each field really means, and the traps to avoid when analysing it.
Field names are exactly as written by the code (`logic-python/services/research_service.py::log_proactive_event`).

## `proactive_logs` — one document per **successful** send

| Field | Type | Meaning | Watch out |
|---|---|---|---|
| `cycle_id` | string (uuid) | one scheduler run (or one AI-planned single-user run) | AI-planned runs create a new id per user |
| `timestamp` | datetime (UTC) | time the FCM send succeeded | convert to `Asia/Jerusalem` for "time of day" |
| `user_id` | string | `users._id` as text | |
| `experiment_id` | string | the user's experiment | |
| `experiment_type` | string | the heuristic with the **largest weight** in the experiment | **not** the heuristic drawn for this send — use `heuristic_selected` |
| `heuristic_selected` / `trigger_source` | string | the heuristic drawn: `affective`, `temporal`, `behaviouralGap`, `generic` | identical fields; `reactive` never appears (nothing is sent) |
| `generated_message` | string | the exact notification body | |
| `was_fallback` | bool | the heuristic had no usable memory and sent a cold-start message | **stays `false` if the LLM call failed** and a static template was used (REVIEW V11) |
| `memory_content` | string | first 120 chars of the memory that drove the message; `""` for fallback/generic | |
| `language` | `"he"` \| `"en"` | language resolved for this send | |
| `topic_label` | string | same as the heuristic name; not informative | |
| `status` | string | always `"sent"` | failures are not logged at all (REVIEW V2) |
| `notification_id` | string | Firebase message id | |
| `heuristic_weights_snapshot` | object | weights **greater than zero** at send time | zero weights are omitted |
| `llm_model` | string | the experiment's `llmModel` setting | may differ from the model actually used (REVIEW V4) |

Not stored, but you will want: `conversation_id`, whether the participant opened the notification, whether and when they replied,
the daily-cap value in force, whether a static template replaced an LLM message.

## Other collections you will use

| Collection | Useful fields |
|---|---|
| `metadata_conversations` | `_id` (= `conversationId` in messages), `userId`, `experimentId`, `conversationNumber`, `createdAt`, `lastMessageTimestamp` (ms epoch), `isFinished` |
| `conversations` | `conversationId`, `role` (`user`/`assistant`), `content`, `messageNumber`, `isProactiveOpener` (on message 1), `userAnnotation` |
| `users` | `experimentId`, `isProactive`, `language`, `proactiveMemory.*`, `conversationSummaries[]` |
| `experiments` | `experimentFeatures.proactiveSettings.*` — the configuration each participant was under |

## Queries

The examples use `mongosh`. Replace `EXP` with an experiment id string.

### Fallback rate per heuristic
Run this before believing any between-condition comparison (REVIEW V5).
```js
db.proactive_logs.aggregate([
  { $match: { experiment_id: "EXP" } },
  { $group: { _id: "$heuristic_selected",
              sends: { $sum: 1 },
              fallbacks: { $sum: { $cond: ["$was_fallback", 1, 0] } } } },
  { $project: { sends: 1, fallbacks: 1, fallback_rate: { $divide: ["$fallbacks", "$sends"] } } }
])
```

### Sends per participant per day (Jerusalem time)
```js
db.proactive_logs.aggregate([
  { $match: { experiment_id: "EXP" } },
  { $group: { _id: { user: "$user_id",
                     day: { $dateToString: { date: "$timestamp", format: "%Y-%m-%d", timezone: "Asia/Jerusalem" } } },
              n: { $sum: 1 } } },
  { $sort: { n: -1 } }
])
```
If any `n` exceeds the cap you intended, the cap was not applied (REVIEW V1).

### Language and model mix
```js
db.proactive_logs.aggregate([
  { $match: { experiment_id: "EXP" } },
  { $group: { _id: { language: "$language", model: "$llm_model", heuristic: "$heuristic_selected" }, n: { $sum: 1 } } }
])
```

### Linking a send to its conversation (today)
The engine creates the conversation a moment *before* it sends, so the nearest `metadata_conversations` document for that user
that was created within about a minute before `timestamp` is the one. Until `conversation_id` is logged this is a heuristic —
validate it on a sample by checking that message 1 of that conversation has `isProactiveOpener: true` and equals `generated_message`.
```python
from datetime import timedelta
from bson import ObjectId

def conversation_for(db, log):
    lo, hi = log["timestamp"] - timedelta(minutes=2), log["timestamp"] + timedelta(seconds=5)
    meta = db.metadata_conversations.find_one(
        {"userId": log["user_id"], "createdAt": {"$gte": lo, "$lte": hi}},
        sort=[("createdAt", -1)])
    if not meta:
        return None
    first = db.conversations.find_one({"conversationId": str(meta["_id"]), "messageNumber": 1})
    ok = first and first.get("isProactiveOpener") and first["content"] == log["generated_message"]
    return meta if ok else None

def replied(db, meta):
    return db.conversations.count_documents(
        {"conversationId": str(meta["_id"]), "role": "user"}) > 0
```

## Pitfalls checklist

1. **Report the fallback rate** per heuristic next to every result; treat `was_fallback` as part of the condition or exclude it — but decide up front.
2. **Denominators are missing.** Only successful sends exist. You cannot compute delivery rate or "how many participants never received anything" from this collection; count participants from `users` and join.
3. **Time zones.** Stored in UTC; the participants and all scheduling are `Asia/Jerusalem` (DST applies).
4. **`experiment_type` is not the condition.** Use `heuristic_selected`.
5. **Participants can be switched off.** `clear_stale_fcm_token` sets `isProactive=false` on errors (REVIEW S8); check `users.isProactive` before assuming a participant was reachable throughout.
6. **Deferred deep-link assignment** may have put a participant in the wrong experiment (REVIEW V9) — verify `users.experimentId` against your recruitment list.
7. **Messages that are not from a notification** may still be flagged `isProactiveOpener` (REVIEW V8).
8. **Preserve the configuration.** The dashboard reportedly stores a prompt that equals the code default as an empty string (`ProactiveSettingsModal.tsx`); if the default text in code changes later, past experiments would silently change meaning. Export `experiments.experimentFeatures.proactiveSettings` and the Git commit hash with every data export.

## Suggested log schema for the next version

`attempt_id`, `cycle_id`, `timestamp`, `user_id`, `experiment_id`, `heuristic_drawn`, `status` (`sent | fcm_failed | dropped | conversation_failed | skipped_day | skipped_cap | reactive`),
`reason`, `conversation_id`, `generated_message`, `was_fallback`, `used_static_template`, `memory_id`, `memory_age_hours`, `language`,
`llm_model_requested`, `llm_model_used`, `temperature`, `weights_snapshot` (all five, including zeros), `cap_in_force`,
`notification_id`, `opened_at`, `first_reply_at`, `code_version`.
