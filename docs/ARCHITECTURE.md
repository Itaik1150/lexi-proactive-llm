# Architecture

How the system fits together and what each part is responsible for.
For known problems see [`REVIEW.md`](REVIEW.md); for the database contract and analysis see [`DATA_AND_ANALYSIS.md`](DATA_AND_ANALYSIS.md).

## 1. Purpose

Lexi is an open-source chat platform for running experiments on human–chatbot interaction.
This thesis adds a **proactive layer**: the system decides *when* and *what* to send a participant, pushes a
notification to their phone, and opens a conversation that already begins with that message.
A researcher configures everything from an admin dashboard; every send is logged for analysis.

The research question the layer supports: *does the type of memory a proactive message draws on
(emotional, upcoming event, unfulfilled intention, or none) change how participants respond?*

## 2. Components

```
                        ┌───────────────────────────────┐
   Participant phone    │  Android app (Kotlin)         │
                        │  WebView shell + FCM service  │
                        └──────┬──────────────▲─────────┘
                       HTTPS   │              │ FCM push (Firebase)
        ┌──────────────────────▼───┐   ┌──────┴───────────────────────┐
        │ React web app  (Vercel)  │   │ Python engine  (Render)      │
        │ chat UI + admin dashboard│   │ APScheduler · heuristics·LLM │
        └──────────┬───────────────┘   └──────┬───────────────────────┘
                   │ REST                      │ reads/writes + 1 REST call
        ┌──────────▼───────────────────────────▼──────┐
        │ Node/Express API (Render)  ──►  MongoDB Atlas│
        └──────────────────────────────────────────────┘
```

| Component | Path | Role | Origin |
|---|---|---|---|
| Web client | `Lexi/client` | Participant chat UI, admin dashboard (`ProactiveSettingsModal` is the proactive control panel) | upstream Lexi + thesis additions |
| API | `Lexi/server` | Users, experiments, conversations, forms, data export; `/join` landing + IP session matching; opener reset logic | upstream Lexi + thesis additions |
| Proactive engine | `logic-python` | Scheduling, heuristic selection, memory extraction, message generation, FCM dispatch, logging | thesis |
| Android app | `android-app` | Installs on the phone, receives push, deep-links into the conversation | thesis |
| Deploy scripts | `scripts/` | Render build/start (Node in foreground, Python scheduler in background) | thesis |

Exactly which files are yours and which are upstream: [`UPSTREAM_DELTA.md`](UPSTREAM_DELTA.md).

**Hosting.** Web client on Vercel; Node API **and** the Python scheduler share one Render instance
(`scripts/render-start.sh`); one MongoDB Atlas database is shared by both; one Firebase project sends pushes.

## 3. One proactive cycle, step by step

`scheduler.py` fires (cron, random window, or AI-planned time) → `ResearchService.run_full_proactive_cycle()`:

1. **Find eligible users** — experiments with `proactiveSettings.enabled`; users with an `fcmToken` and `isProactive = true`;
   skip anyone who already got a message this cycle. Jobs are scoped to the experiment whose schedule fired them.
2. For each user, **load the experiment's live settings** from Mongo — weights, prompts, schedule, model, default language.
3. **Weekday check** against `schedule.allowedDays` (Asia/Jerusalem; 0 = Sunday), then the **daily quota check**: the participant may receive at most the number of notifications per day that the schedule defines (see §5) — sends already logged since local midnight are counted, and the send is skipped once the quota is reached.
4. **Draw one heuristic** with `random.uniform` over the weights. `reactive` = "send nothing" (the control).
5. **Run the heuristic** → it (a) extracts/refreshes memory from recent conversations, (b) reloads the user,
   (c) generates a message with the LLM, or (d) falls back to a cold-start message. It never returns `None`.
6. **Inject** the message into `users.agent.firstChatSentence`, remembering the previous greeting in
   `proactiveMemory.injected_prompt_original`.
7. **Pre-create a conversation** via `POST /conversations/create` on the Node API. Node builds the first message from the injected
   sentence and flags it `isProactiveOpener`.
8. **Gatekeeper**: re-read `isProactive`; drop the send if the participant was switched off meanwhile.
9. **Send FCM** with `conversationId` and `experimentId` in the data payload.
10. **Log** and clean up. Every attempt — sends, skips, control draws and failures — writes one `proactive_logs` document with its outcome and reason; a successful send also calls `heuristic.clear_after_send()`. Later the API stamps `opened_at` and `first_reply_at` on the row when the participant opens and answers the conversation.

The order 6 → 7 matters: the Node server reads the injected sentence while creating the conversation.
Steps 6–8 are not rolled back if 9 fails (REVIEW V3).

### After the participant taps the notification
The app opens the WebView on `/…/conversations/<id>`. When the participant replies (or finishes, or a timer expires),
Node restores the original greeting (`resetInjectedPromptIfNeeded` and related paths). For the Affective condition,
`getProactiveContext` also feeds the memory and the last 7 messages of the source conversation into the chat model's system prompt.

## 4. The four heuristics

All inherit `BaseHeuristic` (`heuristics/base_heuristic.py`). Researchers edit only the *persona/task* prompt in the dashboard;
the base class appends the JSON schema and output rules (`_safe_memory_prompt`, `_safe_message_prompt`).

| Heuristic | Memory it builds (`proactiveMemory.*`) | Fires when | Otherwise |
|---|---|---|---|
| **Affective** | `emotional_memories[]` `{memory_id, content, affective_score 1–10, conversationId, timestamp_iso, used}`; `conversationSummaries[]` (rolling 30, at user root) | an unused memory younger than 72 h exists; highest score wins and is marked `used` immediately | warm "listening ear" invitation (`was_fallback`) |
| **Temporal** | `future_mentions[]` `{text, when_iso, conversationId}`; `fired_temporal_mentions[]` | a mention's `when_iso` is 6–24 h ahead and not yet fired | "anything exciting coming up?" (`was_fallback`) |
| **Behavioural gap** | `open_intents[]` `{intent, stated_at, checked, conversationId}`; `pending_gap_followup`; `gap_scanned_conversation_ids[]` | an intent is 24–48 h old and the LLM judges the user's recent messages give no sign of follow-through | "how are your plans going?" (`was_fallback`) |
| **Generic** | none (only language detection) | always | — (control; never a "fallback") |
| *Reactive* | — | weight draw | nothing is sent |

**Language cascade:** `proactiveMemory.preferred_language` → `user.language` → experiment `defaultLanguage` → `"en"`.
Detection is character-based: > 15 % Hebrew letters ⇒ Hebrew, otherwise English.

**LLM access:** every call goes through `services/llm_service.py::_call_llm` (OpenAI or Anthropic, chosen per experiment by the `llmModel` string).

## 5. Scheduling modes (`proactiveSettings.schedule`)

| `mode` | Behaviour |
|---|---|
| `exact` | one cron job per `fireTimes` entry on the allowed weekdays |
| `random` | per window `{start,end,count}`: `count` cron jobs at `start` with jitter up to the window length |
| `ai_agent` | at 00:01 a planner asks the LLM, per user, for `count` times inside `randomWindows[0]`, based on the user's activity hours, past sends and upcoming events; registers one-off jobs |

**Notifications per participant per day** is whatever the schedule says, and it is enforced as a hard maximum
(`services/schedule_utils.py::daily_quota`, checked in `coordinated_send_and_inject`):

| Mode | Daily quota |
|---|---|
| `exact` | number of distinct fire times |
| `random` | sum of `count` over the random windows |
| `ai_agent` | `count` ("Notifications per user") of the window |

A draw of the *reactive* control sends nothing, so a participant can receive fewer than the quota, never more.

The job list is rebuilt from the database every hour on the hour, so dashboard edits apply within an hour.
All times are `Asia/Jerusalem`.

## 6. Participant onboarding (Android)

1. Researcher shares `…/join/<experimentId>`. The Node server shows a landing page.
2. **Download** hits `/join/<id>/download`: the server stores `{ip, experimentId, timestamp, matched:false}` in `apk_sessions` and redirects to the APK release.
3. On first launch `MainActivity` calls the API's match-session endpoint; the server matches the caller's IP to the newest unmatched session
   from the last 60 minutes and returns the `experimentId`, which the app stores. (Weakness: REVIEW V9. Fallback: manual URL entry.)
4. The participant registers/logs in inside the WebView; the page passes the FCM token to the API (`/users/fcm-token` or `/users/register-device`). These calls require the login cookie and always act on the logged-in user.
5. From then on `LexiMessagingService` receives pushes, builds a high-priority notification and, on tap, opens the deep-link URL.

## 7. Collections (MongoDB Atlas)

| Collection | Written by | Contains |
|---|---|---|
| `users` | Node, Python | account, `agent`, `experimentId`, `fcmToken`, `isProactive`, `proactiveMemory`, `conversationSummaries` |
| `experiments` | Node (dashboard) | `experimentFeatures.proactiveSettings` — see below |
| `metadata_conversations` | Node | one per conversation; `userId`, `createdAt`, `lastMessageTimestamp`, `isFinished` |
| `conversations` | Node | one document per message; `isProactiveOpener` on message 1 |
| `proactive_logs` | Python (attempt), Node (`opened_at`, `first_reply_at`) | one document per **attempt**, any outcome |
| `apk_sessions` | Node | join-link → IP matches |
| `forms` | Node | pre/post questionnaires (unchanged upstream) |

`experiments.experimentFeatures.proactiveSettings`:
`enabled`, `frequency`, `heuristics` (legacy booleans), `heuristicWeights {affective, temporal, behaviouralGap, generic, reactive}`
(the dashboard forces the sum to 100 and writes `reactive` as the remainder), `heuristicPrompts.<name>.{memoryPrompt,messagePrompt}`,
`schedule {allowedDays, mode, fireTimes, randomWindows[]}`, `llmModel`, `defaultLanguage`.
There is no separate daily-limit setting: the schedule itself defines it (§5).

## 8. Design rules the code follows

- **Prompt safety** — structure lives in code, persona lives in the dashboard.
- **Uniform fallback** — a drawn heuristic always produces a message; `was_fallback` records the path.
- **Namespaced memory** — each heuristic writes only its own tracking fields (`affective_*`, `gap_*`, `fired_temporal_*`).
- **No user-level routing** — `proactiveGroup` on the user is deprecated; only the experiment's weights decide.
- **Live configuration** — settings are re-read from Mongo per user per cycle; nothing is cached in Python.
