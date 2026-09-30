# Data & Analysis Guide

What gets written to MongoDB, what each field really means, and the traps to avoid when analysing it.
Field names are exactly as written by the code (`logic-python/services/log_schema.py`, `Lexi/server/src/services/proactiveLogs.service.ts`).

> **Rows written before 1 Oct 2026** come from the older logger: only `status: "sent"` rows exist, and they lack
> `attempt_id`, `reason`, `conversation_id`, `daily_quota`, `sent_today_before`, `llm_model_used`, `opened_at` and `first_reply_at`.
> Keep that in mind when mixing periods.

## `proactive_logs` — one document per **attempt**

Every time the engine considers notifying a participant it writes exactly one row, whatever happens.
That gives you real denominators: how often participants were reached, skipped, put in the control, or failed.

### Outcomes (`status`)

| `status` | Meaning | Counts toward the daily quota |
|---|---|:-:|
| `sent` | FCM accepted the push | yes |
| `reactive` | control draw — nothing is sent, by design | no |
| `skipped_day` | today is not an allowed weekday for the experiment | no |
| `skipped_quota` | participant already received the schedule's notifications for today | no |
| `skipped_quota_unverified` | could not count today's sends, so the engine did not risk sending | no |
| `heuristic_failed` | the drawn heuristic raised an error or returned nothing | no |
| `injection_failed` | the opener could not be written to the user document | no |
| `conversation_failed` | the opener conversation could not be pre-created | no |
| `dropped_gatekeeper` | participant was switched off between the draw and the send | no |
| `fcm_failed` | the push could not be sent to Firebase (see `reason`) | no |
| `error` | any other unexpected exception (see `reason`) | no |

### Fields

| Field | Type | Meaning | Watch out |
|---|---|---|---|
| `attempt_id` | string (uuid) | unique id of this attempt | |
| `cycle_id` | string (uuid) | one scheduler run | AI-planned runs create a new id per participant |
| `timestamp` | datetime (UTC) | when the outcome was recorded | convert to `Asia/Jerusalem` for time of day |
| `user_id` | string | `users._id` as text | |
| `experiment_id` | string | the participant's experiment | |
| `status` | string | see above | |
| `reason` | string \| null | why, for skips and failures (max 300 chars) | |
| `heuristic_selected` (= `trigger_source`) | string \| null | the heuristic **drawn** for this attempt: `affective`, `temporal`, `behaviouralGap`, `generic`, or `reactive` | `null` for outcomes before the draw (`skipped_*`) |
| `experiment_type` | string | the heuristic with the largest weight in the experiment | **not** the condition of this attempt — use `heuristic_selected` |
| `generated_message` | string | the exact notification text | `""` when none was generated |
| `was_fallback` | bool \| null | no usable memory, a cold-start message was used | `null` when no message existed; stays `false` if an LLM failure was replaced by a static template (REVIEW V11) |
| `memory_content` | string | first 120 characters of the memory behind the message | `""` for fallback/generic |
| `language` | `"he"` \| `"en"` \| null | language used | |
| `conversation_id` | string \| null | the conversation created for this notification | set once the conversation exists; joins to `metadata_conversations._id` |
| `notification_id` | string \| null | Firebase message id | only for `sent` |
| `heuristic_weights_snapshot` | object | weights **greater than zero** at that moment | zero weights are omitted |
| `llm_model` | string | the model the experiment *asked for* | may differ from what was used |
| `llm_model_used` | string | the model the engine actually called | the trustworthy one |
| `daily_quota` | int \| null | notifications per day the schedule allows for this participant | |
| `sent_today_before` | int \| null | how many had already been sent that day (Jerusalem time) | |
| `opened_at` | datetime | **added later by the API** on `sent` rows: first time the app fetched the conversation | see below |
| `first_reply_at` | datetime | **added later by the API**: first message the participant wrote in it | |

### What the funnel timestamps mean
- `opened_at` is the first time *any client* requested that conversation from the API. For the participant it is the notification tap (or opening the app onto it). It would also be set by a researcher viewing the conversation, or by a page reload.
- `first_reply_at` is the first message with role `user` in it. A reply also sets `opened_at` if the fetch was missed.
- Both are set once (first time wins), only on `sent` rows. Absent means "did not happen (yet)".

## Other collections you will use

| Collection | Useful fields |
|---|---|
| `metadata_conversations` | `_id` (= `conversationId` in messages), `userId`, `experimentId`, `conversationNumber`, `createdAt`, `lastMessageTimestamp` (ms epoch), `isFinished` |
| `conversations` | `conversationId`, `role` (`user`/`assistant`), `content`, `messageNumber`, `isProactiveOpener` (on message 1), `userAnnotation` |
| `users` | `experimentId`, `isProactive`, `language`, `proactiveMemory.*`, `conversationSummaries[]` |
| `experiments` | `experimentFeatures.proactiveSettings.*` — the configuration each participant was under |

Recommended indexes (run once in Atlas / `mongosh`; they speed up the daily-quota count and the funnel stamps):
```js
db.proactive_logs.createIndex({ user_id: 1, timestamp: -1 })
db.proactive_logs.createIndex({ conversation_id: 1 })
```

## Queries

The examples use `mongosh`. Replace `EXP` with an experiment id string.

### What happened to every attempt
```js
db.proactive_logs.aggregate([
  { $match: { experiment_id: "EXP" } },
  { $group: { _id: { heuristic: "$heuristic_selected", status: "$status" }, n: { $sum: 1 } } },
  { $sort: { "_id.heuristic": 1, n: -1 } }
])
```

### The funnel per heuristic: sent → opened → replied
```js
db.proactive_logs.aggregate([
  { $match: { experiment_id: "EXP", status: "sent" } },
  { $group: { _id: "$heuristic_selected",
              sent: { $sum: 1 },
              opened:  { $sum: { $cond: [{ $ifNull: ["$opened_at", false] }, 1, 0] } },
              replied: { $sum: { $cond: [{ $ifNull: ["$first_reply_at", false] }, 1, 0] } } } }
])
```

### Time from notification to opening and to first reply (minutes)
```js
db.proactive_logs.aggregate([
  { $match: { experiment_id: "EXP", status: "sent", first_reply_at: { $exists: true } } },
  { $project: { heuristic_selected: 1,
                to_open:  { $divide: [{ $subtract: ["$opened_at", "$timestamp"] }, 60000] },
                to_reply: { $divide: [{ $subtract: ["$first_reply_at", "$timestamp"] }, 60000] } } },
  { $group: { _id: "$heuristic_selected", avg_open: { $avg: "$to_open" }, avg_reply: { $avg: "$to_reply" }, n: { $sum: 1 } } }
])
```

### Fallback rate per heuristic
Run this before believing any between-condition comparison (REVIEW V5).
```js
db.proactive_logs.aggregate([
  { $match: { experiment_id: "EXP", status: "sent" } },
  { $group: { _id: "$heuristic_selected",
              sends: { $sum: 1 },
              fallbacks: { $sum: { $cond: ["$was_fallback", 1, 0] } } } },
  { $project: { sends: 1, fallbacks: 1, fallback_rate: { $divide: ["$fallbacks", "$sends"] } } }
])
```

### Sends per participant per day (Jerusalem time)
```js
db.proactive_logs.aggregate([
  { $match: { experiment_id: "EXP", status: "sent" } },
  { $group: { _id: { user: "$user_id",
                     day: { $dateToString: { date: "$timestamp", format: "%Y-%m-%d", timezone: "Asia/Jerusalem" } } },
              n: { $sum: 1 } } },
  { $sort: { n: -1 } }
])
```
`n` should never exceed the schedule's notifications per day (exact: number of fire times; random: sum of window counts; AI: the window count). If it does, that is a bug — please report it.

### Language and model actually used
```js
db.proactive_logs.aggregate([
  { $match: { experiment_id: "EXP", status: "sent" } },
  { $group: { _id: { language: "$language", model: "$llm_model_used", heuristic: "$heuristic_selected" }, n: { $sum: 1 } } }
])
```

### From a send to the conversation and its messages
`conversation_id` is now stored, so no guessing is needed:
```python
def messages_for(db, log):
    return list(db.conversations.find({"conversationId": log["conversation_id"]}).sort("messageNumber", 1))
```

## Pitfalls checklist

1. **Report the fallback rate** per heuristic next to every result; treat `was_fallback` as part of the condition or exclude it — but decide up front.
2. **Use the right denominator.** "Reached" = `status: "sent"`. Control participants (`reactive`) never receive anything, so compare their behaviour through conversations, not through `opened_at`.
3. **Time zones.** Stored in UTC; the participants and all scheduling are `Asia/Jerusalem` (DST applies).
4. **`experiment_type` is not the condition.** Use `heuristic_selected`.
5. **Participants can be switched off.** A dead push token sets `isProactive=false`; check `users.isProactive` before assuming a participant was reachable throughout, and look at `dropped_gatekeeper` / `fcm_failed` rows.
6. **Deferred deep-link assignment** may have put a participant in the wrong experiment (REVIEW V9) — verify `users.experimentId` against your recruitment list.
7. **Messages that are not from a notification** may still be flagged `isProactiveOpener` (REVIEW V8); prefer `conversation_id` from `proactive_logs`.
8. **An opened notification is not proof of reading.** `opened_at` means the conversation was fetched.
9. **Preserve the configuration.** The dashboard reportedly stores a prompt that equals the code default as an empty string (`ProactiveSettingsModal.tsx`); if the default text in code changes later, past experiments would silently change meaning. Export `experiments.experimentFeatures.proactiveSettings` and the Git commit hash with every data export.
10. **Old rows** (before 1 Oct 2026) only have `sent` outcomes and no funnel fields.

## Still missing (see REVIEW)

`used_static_template` (V11), `memory_id` / `memory_age_hours` (V5), `temperature` (V10), and a `code_version` stamp.
