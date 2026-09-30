# Code Review — September 2026

A full read-through of the repository: how the pieces connect, what is wrong, and what to change.
Written against commit `6e2143d` (30 Sep 2026).

**How this was done.** The Python engine (`logic-python/`, ~2,000 lines) was read line by line.
The Node/React delta and the Android app were compared file-by-file against upstream Lexi
([`UPSTREAM_DELTA.md`](UPSTREAM_DELTA.md)) and reviewed by two independent passes.
Every finding is marked:

- **[V]** verified directly in the code by the reviewer of this document
- **[R]** reported by a review pass and traced to a file, but not re-checked line by line

Nothing was changed in code. Only documentation and file layout changed (see [§6](#6-cleanup)).

---

## Progress tracker

Fixes are done one at a time, each in its own commit. **✅ done · 🟡 needs you · ⬜ open**

| ID | Item | Status | Note |
|---|---|---|---|
| S1 | Rotate the leaked Atlas password | 🟡 | only you can do this (Atlas → Database Access) |
| V1 | Daily cap could not be set | ✅ | schema + types + dashboard field added |
| V1b | Dashboard save wiped `defaultLanguage` | ✅ | found while fixing V1; save now keeps unknown keys |
| S8 | Stale-token cleanup could opt everyone out | ✅ | typed Firebase errors only; unit-tested (`logic-python/tests/`) |
| S2 S3 S4 S5 S6 | Auth on token routes, WebView allow-list, `/join` validation, CORS, Android hardening | ⬜ | |
| V2 V3 V4 V6 R5 V9 | Log every attempt, roll back failed sends, reset model, re-scan conversations, one reset path, confirm join | ⬜ | |
| V5 V7 V10–V13 | Fidelity, context asymmetry, LLM confounds, timezone | ⬜ | |
| R1–R4 R9 S11 | Scheduler per experiment, worker + heartbeat, single Mongo client, tests, deps | ⬜ | |

---

## Verdict

The project is a **coherent, ambitious research prototype with a sound core idea**: a probability-weighted
set of heuristics, each with its own memory pipeline and a guaranteed fallback, configurable live from a dashboard,
with structured per-send logging. The Python engine is readable and the separation of *researcher prompt* from
*system-enforced formatting* is a genuinely good design decision.

But it is **not yet safe to collect data you plan to publish**. There are three kinds of problem:

1. **One credential leak** that needs action today (§0).
2. **Several places where the experiment does not do what the dashboard says** — most importantly, the daily
   notification cap can never be set, and most sends will probably be cold-start fallbacks rather than the
   memory-based condition you think you are testing (§1).
3. **Unauthenticated endpoints and an over-trusting Android WebView** (§2).

None of it is hard to fix. Section 7 gives an order of work.

---

## 0. Act now — database password in public git history

| | |
|---|---|
| **What** | `logic-python/.env.new` was committed in `e368bf2` (1 Mar 2026) and deleted in `57d267b`. It contains a full `mongodb+srv://<user>:<password>@…` Atlas connection string. **[V]** |
| **Why it matters** | The repository is public. Deleting a file does not remove it from history; anyone can read it with `git show e368bf2:logic-python/.env.new`. |
| **Fix** | **1.** In Atlas → Database Access, change that database user's password (or create a new user and delete the old one). **2.** Put the new URI in Render's environment variables. **3.** In Atlas → Network Access, replace `0.0.0.0/0` (if present) with Render's outbound IPs. **4.** Optionally purge the file from history with `git filter-repo` — this rewrites every commit hash and needs a force-push, so it is cosmetic once the password is rotated. |

Checked and **not** leaking: no Firebase service-account JSON, no OpenAI/Anthropic key, and no JWT secret
was ever committed (the `${openai_key}`-style hits are template placeholders inherited from upstream).
The Firebase key file at `logic-python/services/lexi-72330-firebase-adminsdk-*.json` exists **locally only**
and is correctly ignored — keep it out of cloud-synced folders.

Also in history: a whole `venv/` folder (3,600 files) from the initial commit. Harmless but bloats every clone.

---

## 1. Research validity — the experiment may not be doing what you think

These matter most for the thesis. Ordered by how much they can change your conclusions.

### V1. The daily notification cap can never be set **[V]** — ✅ fixed
Python enforces `proactiveSettings.maxDailyNotifications` (`research_service.py:197`, `:1034`; `scheduler.py:259`).
That key does not exist in the Mongoose schema (`ExperimentsModel.ts`), the TypeScript types, or the React dashboard —
`grep maxDailyNotifications Lexi/` returns nothing. Mongoose strict mode drops unknown keys on save, so even a
hand-edited value is lost the next time anyone saves the experiment.
**Result: no cap is ever applied.** `CURRENT_SPRINT` item 1.4 (still unchecked) was right to worry.
*Fix (done):* the field is now in the schema, both type files and `ProactiveSettingsModal` (0 = no limit). Still open: log the cap in force with each send (part of V2).
*Also found (V1b):* the modal rebuilt `proactiveSettings` from scratch on every save, so `defaultLanguage` (and any other key it does not edit) was deleted; Python then fell back to English. The save now spreads the existing settings first.
*After deploying:* open each experiment in the dashboard, set the limit and save — existing experiments have no value stored, which means "no limit".

### V2. Only successful sends are logged **[V]**
`log_proactive_event` is called only inside `if notification_result:`. Failures, dropped sends, skipped users,
"reactive" draws and exceptions leave **no row**. The docstring promises "delivery success rate = sent / total",
which cannot be computed. The Sent → Opened → Replied funnel (sprint item 2.2) is not implemented anywhere:
the Node server never writes to or reads `proactive_logs`.
*Fix:* write one row per attempt with `status` ∈ `sent | fcm_failed | dropped_gatekeeper | conversation_failed | skipped_day | skipped_cap | reactive` and a `reason`.
Add `opened_at` / `first_reply_at` by having Node update the row when the pre-created conversation is opened and replied to.
Also store `conversation_id` — the log row currently has **no link to the conversation it created** (only `proactiveMemory.linked_conversation_id`, which is overwritten on every send), so joining a send to the participant's reply needs a timestamp-proximity guess ([how](DATA_AND_ANALYSIS.md#linking-a-send-to-its-conversation-today)).

### V3. Nothing is rolled back when a send fails after injection **[V]**
`coordinated_send_and_inject` (1) overwrites the participant's `agent.firstChatSentence`, (2) pre-creates a conversation,
(3) *then* checks the gatekeeper and sends FCM. If step 3 fails or the gatekeeper drops it, the opener stays injected, the
phantom conversation stays, and — for Affective — the memory was already marked `used`. The participant later opens the app
and sees a proactive message they were never notified about, in a condition they were not meant to be in.
*Fix:* compensate on failure (restore `injected_prompt_original`, delete the conversation, un-use the memory), or reorder so the
irreversible steps come last.

### V4. The logged `llm_model` is not necessarily the model used **[V]**
`override_model()` mutates a process-wide singleton and is only called when the experiment has `llmModel` set.
It is never reset, so after one experiment uses `claude-…`, every later user and cycle keeps using it until restart —
while `log_proactive_event` records the *experiment's* setting (`llm_model=experiment_llm_model`).
*Fix:* set the model explicitly for every user (`experiment_model or default`) and log `llm_service.model`.

### V5. Treatment fidelity: most sends are probably fallbacks **[V]**
Memory is extracted **only when that heuristic is drawn** for that user, at send time:

| Heuristic | Needs at send time | Chance a given cycle qualifies |
|---|---|---|
| Temporal | an event whose `when_iso` is **6–24 h** away | low — the event must be extracted earlier *and* Temporal must be drawn in that window |
| Behavioural gap | an intent whose age is **24–48 h**, measured from **extraction time**, not from when the user said it | low — same reason; intents past 48 h are silently discarded |
| Affective | an unused emotional memory younger than **72 h** (again from extraction) | moderate |

With 1–3 sends a day and weights like 25 % each, a large share of Temporal and Gap sends will take the
cold-start path (`was_fallback = true`) and read like a slightly-warmer Generic message. Then the "conditions" you
compare are not the conditions you defined.
*Fix:* (a) **measure it first** — the query in [`DATA_AND_ANALYSIS.md`](DATA_AND_ANALYSIS.md#fallback-rate-per-heuristic) takes seconds;
(b) decouple memory extraction from selection (run it on a timer for all users); (c) use the timestamp of the user's
message, not extraction time; (d) choose among heuristics that currently have material, or declare fallback part of the
treatment and analyse intention-to-treat.

### V6. Conversations are scanned once and never again **[V]**
Affective and Gap mark a conversation as scanned after the first pass — even if it was empty. Consequences:
an ongoing chat analysed at message 3 never has messages 4+ read; and the **pre-created proactive conversation is
empty of user messages when the next cycle runs**, so it is marked scanned and the participant's later reply in exactly
that conversation is never analysed. (The comment "conversations with future messages will appear as a NEW conv doc" is wrong.)
Temporal has the opposite problem: it re-scans the newest 5 conversations every time (extra LLM cost, unbounded `future_mentions`).
*Fix:* store `{conversationId → last scanned messageNumber}` and rescan when it grows.

### V7. Only the Affective condition gives the chat model its source context **[V]**
`research_service` passes `heuristic.linked_memory_id`; only Affective sets it. Node's `getProactiveContext`
looks the memory up in `emotional_memories` only. In Temporal/Gap/Generic chats the assistant sees the opener sentence
but not what it refers to. That is an unintended difference between conditions in the *conversation* that follows.
*Fix:* give every heuristic a memory id and make `getProactiveContext` generic, or drop the injection for all conditions.

### V8. "Proactive conversation" labelling is unreliable **[R]**
Node flags a new conversation `isProactiveOpener` if `injected_prompt_original` exists on the user — so a conversation the
participant opens for their own reasons before replying can be counted as proactive. On the client, `ChatPage.tsx:158–162`
sets `sessionStorage.fromNotification` on the first view of *any* one-message conversation and `MessageList` never clears it,
so the proactive-feedback control appears for non-notification opens. Both contaminate the annotation data.
*Fix:* have Python pass the exact conversation id it created and mark only that one; record a real "opened from notification" event.

### V9. Deferred deep link can assign the wrong experiment **[V]**
`matchSession` matches on client IP only (newest unmatched row within 60 min). On campus Wi-Fi/NAT, CGNAT, VPNs or IPv4/IPv6 mismatch,
two participants can swap experiments, or match nobody. The result is stored permanently on the phone. `X-Forwarded-For[0]`
is client-controlled. There is no check that a session was matched exactly once.
*Fix:* Play Install Referrer, or a one-time code shown on the join page that the participant types/confirms; at minimum, match on IP + user-agent, require exactly one candidate, and show "You are joining *&lt;experiment name&gt;*" for confirmation.

### V10. Provider and prompt confounds **[V]**
- The Anthropic branch of `_call_llm` **ignores `temperature`** (default 1.0 applies) while OpenAI honours 0.3–0.7. Comparing models compares different sampling.
- Temperatures differ by heuristic (Generic 0.3, Gap 0.5, Temporal 0.6, Affective/cold-start 0.7).
- The researcher prompts say "max 15 words"; the system suffix says "Maximum 20 words" — contradictory in one prompt.
- `max_tokens` is 60–80. Hebrew costs several tokens per word, so messages can be cut mid-sentence; `finish_reason`/`stop_reason` is never checked. Memory extraction (300–600 tokens) can truncate JSON → parse error → conversation already marked scanned → memory lost.
- Newer OpenAI models reject `max_tokens` / non-default `temperature`; not yet handled.
- Anthropic JSON mode is only a prompt suffix; fenced ```` ```json ```` output fails `json.loads`.
*Fix:* pass temperature to Anthropic; use one temperature for all message generation; one word limit; check stop reason; strip code fences.

### V11. LLM failure is invisible in the data **[V]**
When the LLM call fails the heuristics return a hard-coded template but leave `used_fallback = False`. Hebrew templates are
grammatically masculine ("איך אתה מרגיש") for every participant. The Gap template inserts an English intent into a Hebrew
sentence, and the English one reads "did you end up *go to the gym*?".
*Fix:* add `used_static_template` to the log; use gender-neutral Hebrew or ask the participant's preferred form at registration.

### V12. Gap completion check sees the original statement **[V]**
`check_intent_completion` receives the user's last 3 conversations — which include the one where the intent was stated —
so the model may treat the original sentence as evidence of follow-through. *Fix:* pass only messages after `stated_at`.

### V13. Time-zone skew in Temporal **[V]**
The extraction prompt gets today's date in UTC; the participant lives in `Asia/Jerusalem` (+2/+3 h). "Tomorrow at 5 pm" becomes 17:00 UTC, and
naive datetimes are read as UTC. Skew is 2–3 h against a 6–24 h window. *Fix:* give the LLM local time and offset.

---

## 2. Security & privacy

| # | Sev. | Finding | Where | Fix |
|---|---|---|---|---|
| S1 | **Critical** | DB password in public history | §0 | rotate |
| S2 | **High** | `POST /users/fcm-token` and `/register-device` take a `userId` from the body with no authentication. Anyone who knows an id can replace a participant's push token (hijacking their notifications). The service returns the full user document, including the bcrypt hash. **[R]** — route has no middleware **[V]** | `usersRouter.router.ts:12-13`, `users.service.ts:189` | derive id from the JWT; return `{ok:true}` |
| S3 | **High** | `MainActivity` is `exported=true`, loads any `deepLinkUrl` extra into a WebView that has the `Android` JS bridge attached (`getFCMToken`, `getCurrentUserId`, `sendTokenToServer`). Any installed app can open an attacker page with access to the bridge. **[R]** (manifest **[V]**) | `AndroidManifest.xml:25`, `MainActivity.kt:74-91,225-240,310` | allow-list your own origin; attach the bridge only there |
| S4 | **High** | `/join/:experimentId` writes the raw parameter into HTML (reflected XSS on your API origin) and inserts it into `apk_sessions` without validation or rate limit. **[V]** insert, **[R]** XSS | `joinController.ts` | `/^[a-f0-9]{24}$/`, verify the experiment exists, escape |
| S5 | **Med** | CORS with `credentials: true` accepts any origin that *contains* your project name and ends in `.vercel.app` — anyone can register such a project. A rejected origin returns a 500 stack trace. A LAN IP is left in the allow-list. **[R]** | `server.ts` | exact-match regex on your Vercel slug |
| S6 | **Med** | Android: `allowBackup="true"` with empty rules (auth cookie + prefs go to cloud backup); `usesCleartextTraffic="true"`; **debug** APK distributed; minify off; notification text visible on lock screen (emotional content!); wake-lock acquired and released immediately; FCM token and user id written to logcat. **[V]** manifest, **[R]** rest | `AndroidManifest.xml`, `build.gradle.kts`, `LexiMessagingService.kt`, `AndroidBridge.kt` | `allowBackup=false`, debug-only cleartext config, signed release build, `VISIBILITY_PRIVATE` |
| S7 | **Med** | Raw IPs kept in `apk_sessions` with no TTL; `matchSession` logs whole session documents and other users' IPs; the landing page says "fully anonymous". Server logs user message text ("MESSAGES SENT TO LLM"). **[R]** | `joinController.ts`, `experimentsController`, `conversations.service.ts` | 24 h TTL index; delete those logs; **check wording against your ethics approval** |
| S8 ✅ | **Med** | Stale-token cleanup treats any error containing "not found" as "delete this token and set `isProactive=false`". `fcm_service.py` itself says "not found" also means *wrong Firebase project*. A misconfigured deploy would silently opt **every** participant out. **[V]** | `research_service.py` (`_is_stale_token_error`) | **fixed:** only `UnregisteredError` and a malformed-token `InvalidArgumentError` count; `SenderIdMismatchError` deliberately excluded (a wrong service account looks the same) |
| S9 | **Low–Med** | `PUT /experiments` and other admin routes appear to have no `isAdmin` check (upstream pattern); JWT has no `expiresIn` and is re-issued on every `/user`. **[R]**, suspected | `experimentsRouter`, `users.service.ts` | auth middleware + expiry |
| S10 | **Low–Med** | `get_all_proactive_users` sets `isProactive=true` for every user with a token and no flag. Fine operationally; check it matches how consent is recorded. **[V]** | `research_service.py:118` | confirm with ethics text |
| S11 | Low | `requests==2.31.0` has a known CVE (fixed in 2.32); all Python deps are pinned to 2023 versions. **[V]** | `requirements.txt` | bump |

---

## 3. Reliability & operations

- **R1. The scheduler ignores which experiment fired. [V]** Every job — whichever experiment's fire time triggered it — calls `run_full_proactive_cycle()` for *all* enabled experiments' users. With two experiments on different schedules, participants are notified at the other experiment's times; only the per-user weekday check and the (unset, see V1) cap limit it.
- **R2. The scheduler is a background subprocess of the web service. [V]** `render-start.sh` runs `python scheduler.py || echo …` in the background; if it dies it is not restarted and nothing alerts you. The job store is in memory, so a redeploy loses today's AI-planned times (the planner only runs at 00:01), and APScheduler's default `misfire_grace_time` is 1 s, so a busy moment silently skips a job.
  *Fix:* deploy it as a separate Render **Background Worker**, write a heartbeat document to Mongo and alert when it goes stale, run the AI planner at startup as well as at 00:01, set `misfire_grace_time`.
- **R3. One shared MongoDB client, reconnected on every call. [V]** `connect()` builds a new `MongoClient` each time and overwrites `self.client`; `disconnect()` closes whichever is current. APScheduler runs jobs on a thread pool, so two overlapping jobs can close each other's client mid-query. It is also slow (a new TLS handshake per operation) and leaks the client if `connect()` is called twice. *Fix:* create one `MongoClient` at import and never close it — it is thread-safe.
- **R4. Fallback schedule sticks. [V]** If Mongo is briefly unreachable at startup the hard-coded `13:45/17:30/21:15` jobs are registered and the hourly reload deliberately leaves them alone forever. Separately, an experiment whose `fireTimes` is empty silently inherits those same three times.
- **R5. Four code paths reset the injected opener [R]** (`conversationsController`, `users.service.resetInjectedPromptIfNeeded`, `usersController.expireProactivePromptIfNeeded`, and Python's inject), not idempotent with one another. In the traced sequence one path leaves `injected_prompt_reset_after` set while another writes `''` as the greeting, and a later expiry pass then deletes `agent.firstChatSentence`. Result: empty first message in later conversations. *Fix:* one atomic pipeline update, called from every path.
- **R6. Deactivating an experiment is not atomic and reactivation doesn't restore `isProactive`. [R]**
- **R7. FCM token refresh depends on the WebView being open. [R]** `onNewToken` only writes to SharedPreferences; the server hears about it via timers inside the page (2 and 5 min) which exist only while the app runs, and `fcmBridge.ts:97` stacks a new interval on every hook run. Logout never clears the token, so a shared phone keeps receiving the previous participant's nudges.
- **R8. Production URLs are defaults. [V]** `LEXI_SERVER_URL`, `FRONTEND_BASE_URL` and Firebase `projectId='lexi-72330'` default to production. A local `python run_cycle.py` with a production `MONGODB_URL` creates real conversations on the live server. The client `AxiosInstance` falls back to `localhost:5000` in a production build and treats every Android browser as the emulator. *Fix:* require the variables; fail loudly.
- **R9. No automated tests for the engine. [V]** The only test-like scripts are the 14 ignored files in `logic-python/Archive/`. The pure logic (`_select_heuristic`, `_detect_language`, schedule parsing, the 24–48 h window, weight normalisation) is easy to cover with `pytest` + `mongomock`.
- **R10. Mongoose schema and `tsconfig` are looser/stricter in the wrong places. [R]** Strict subschema silently strips fields Python needs (V1); `strictNullChecks` and `noImplicitAny` are off, which hides `undefined` bugs.

---

## 4. Opinion on the design

**Keep:** heuristic classes with a shared base; researcher-visible persona prompt vs. system-owned JSON/format suffix; guaranteed
fallback; per-send logging with a weights snapshot; the dual-tier memory idea (verbatim emotional memory + rolling 30 summaries);
deep-linking straight into the pre-created conversation; live-editable configuration.

**Rethink:**

1. **Separate "memory building" from "sending".** Today they are fused inside `get_proactive_message()`. A small background job that keeps every
   participant's `proactiveMemory` up to date would fix V5, V6 and V12 together, remove LLM cost from the send path, and let you *choose*
   a heuristic that has material.
2. **Make the log the source of truth.** One row per attempt, updated as the funnel progresses. Then the analysis chapter is one query, not archaeology.
3. **Decide what the manipulation is.** If a Temporal send with no event is "a warm generic message", say so and report it as such —
   or don't send it. Either is defensible; silently mixing them is not.
4. **One code path for the reset of the opener**, owned by Node, called by Python via an authenticated internal endpoint rather than by writing the same Mongo fields from two languages.
5. **Prefer data-only FCM messages.** Python sends a `notification` block; when the app is backgrounded Android shows it itself and `onMessageReceived` (your custom intent, full-screen behaviour) does not run. **[R]**, suspected.
6. **Two languages, one database** is the largest source of contract drift (V1 is one). A shared JSON-schema file for `proactiveSettings` and `proactiveMemory`, checked in both codebases, would stop this class of bug.

---

## 5. Docs vs. code (why the docs were rewritten)

| Old claim | Reality |
|---|---|
| `SYSTEM_ARCHITECTURE`: "forms / dataAggregation are thesis analytics" | Both are **unchanged upstream Lexi code**; not yours to claim |
| "Researchers set `maxDailyNotifications` in the dashboard" | Not possible (V1) |
| Affective "tracks scan state via `affective_last_analyzed_msg_count`" | Code uses `affective_scanned_conversation_ids` |
| Language cascade ends at `"he"` | Code ends at `"en"` unless the experiment sets `defaultLanguage` (Mongoose default `'he'`) |
| README: Temporal asks "how it went" | Only *future* events 6–24 h ahead; the "just passed" branch of the prompt is dead code |
| README: "sufficient for full thesis analysis without post-hoc joins" | Failures and the funnel are not logged (V2) |
| README: `cp .env.example .env` | No `.env.example` existed — now added |
| Links to `PROACTIVE_NOTIFICATIONS.md` (in the private working docs) | That file does not exist |
| Code comments "Task 6.x" | Refer to prompts to an AI assistant; opaque to a reader or examiner — replace with descriptive comments over time |

---

## 6. Cleanup

**Done in this pass** (all reversible via git):

- `docs/archive/` now holds the 11 historical implementation logs (`PROACTIVE_FEEDBACK_*`, `PROACTIVE_SETTINGS_*`, old `CURRENT_SPRINT`, old architecture doc) that had accumulated at the repo root and inside `Lexi/`. They are kept, not deleted.
- Removed the empty, unused `logic-python/logic/` package.
- Added `.env.example` files for the three components.
- Rewrote `README.md` and wrote `docs/ARCHITECTURE.md`, `DATA_AND_ANALYSIS.md`, `OPERATIONS.md`, `UPSTREAM_DELTA.md`.

**Recommended, not done** (needs your machine/IDE or your decision):

- Delete local clutter: `logic-python/Archive/` (14 old scripts), `logic-python/venv/`, `Lexi/server/clean_db.ts` if unused (it is untracked).
- Android: remove duplicate launcher icon sets (`favicon.webp`, `ic_launcher*.webp`, `faviconh*.png` — only `faviconh` is referenced), `ExampleUnitTest`/`ExampleInstrumentedTest`, unused Compose `ui/theme/*`. Do this in Android Studio and build.
- Remove leftover debug logging: on the client `MessageList.tsx` (logs on every render), `ChatPage.tsx` (dumps whole messages), `AxiosInstance.ts`, `useActiveUser.ts`, `fcmBridge.ts` (token prefix); on the server `conversations.service.ts` ("MESSAGES SENT TO LLM", `[getProactiveContext]`) and `experimentsController.updateExperiment` (logs the full request body).
- Remove the demo hard-coding (`Login.tsx` `DEMO_EXPERIMENT_ID`, `ChatPage.tsx` "Demo Completed") from the study build behind a flag.
- Remove duplicated `getFCMTokenWithRetry` in `LoginForm`/`RegisterForm` and dead bridge methods (`AndroidBridge.kt` `sendTokenToServer` posts to `http://10.0.2.2:5000`).
- `Lexi/server/src/index.js` and `Lexi/server/setup.js` are unmodified upstream leftovers; nothing runs them in production.
- `mongodb_client.py` has debug methods that load the whole users collection (`get_users_with_fcm_tokens`, `get_user_context`, `update_user_first_message` — the latter two query `_id` as a string and would never match).

---

## 7. Suggested order of work

| When | Do | Items |
|---|---|---|
| **Today** | Rotate the Atlas password | S1 |
| **This week** (small, high value) | Auth on FCM routes · validate `/join` param · `allowBackup=false` · allow-list WebView origin · narrow stale-token detection · CORS exact match · add `maxDailyNotifications` to schema/UI | S2 S3 S4 S5 S6 S8 V1 |
| **Before more participants** | Log every attempt · roll back failed sends · reset model per user · fix scan tracking · one opener-reset path · confirm join with the participant | V2 V3 V4 V6 R5 V9 |
| **Before the analysis** | Measure fallback rate · decouple memory building · align temperature/limits · timezone · contexts across conditions | V5 V7 V10 V11 V12 V13 |
| **Hardening** | Separate worker + heartbeat · single Mongo client · per-experiment scheduling · tests · pin/update deps | R1–R4 R9 S11 |
