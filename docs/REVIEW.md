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
| S1 | Rotate the leaked Atlas password | ✅ | done by the owner 30 Sep 2026 (history still contains the old, now-dead URI) |
| V1 | Daily limit could not be applied | ✅ | no extra setting: the schedule's own count (exact times / window counts / AI count) is now a hard per-day maximum |
| V1b | Dashboard save wiped `defaultLanguage` | ✅ | found while fixing V1; save now keeps unknown keys |
| R1 | Every job notified all experiments' users | ✅ | jobs are scoped to the experiment whose schedule fired them |
| V2 | Only successful sends were logged; no funnel | ✅ | every attempt logged with status and reason; `conversation_id`, quota and model used stored; API stamps `opened_at` / `first_reply_at` |
| V3 | Failed sends left an opener, a phantom conversation and a consumed memory behind | ✅ | snapshot before injecting; full rollback on failure; gatekeeper moved ahead of conversation creation |
| V4 | Model leaked between experiments; log named the wrong model | ✅ | model selected per participant; `llm_model_used` logged |
| V6 | Conversations scanned once; later replies (incl. the notification conversation) missed | ✅ | per-conversation message progress; only new messages analysed; failures retried |
| S8 | Stale-token cleanup could opt everyone out | ✅ | typed Firebase errors only; unit-tested (`logic-python/tests/`) |
| S2 | Push-token routes had no login | ✅ | `requireUser` middleware; id comes from the login cookie; response no longer returns the user record |
| S4 | `/join` XSS and unvalidated writes | ✅ | id must be a real experiment (24 hex + exists), escaped, downloads rate-limited |
| S5 | CORS accepted look-alike Vercel projects | ✅ | exact origins only; previews opt-in via `CORS_PREVIEW_SUFFIX`; refused origins no longer 500 |
| S3 | Exported activity + JS bridge could be pointed at any URL | 🟡 | **device-tested 25 Oct:** hostile `deepLinkUrl` and malformed ids are ignored. An outside link inside a message could not be tested (the chat shows links as plain text); that rule is covered by unit tests only |
| S6 | Android: backup, cleartext, lock screen, token logs | 🟡 | **device-tested 25 Oct:** backup off, lock-screen text hidden when the app draws the notification. Notifications Android draws itself (app closed or in the background) still show the full text (see V10 note, item 5). Still open: a signed release build and minification (need your keystore) |
| R5 | Four overlapping opener-reset paths; a race could replace a fresh opener or blank the greeting | ✅ | one atomic reset; the two dormant paths removed; engine verifies the conversation really starts with the opener |
| V9 | Join link can assign the wrong experiment | 🟡 | server fix deployed; **device-tested 25 Oct** (Samsung, Android 16): Open Lexi link and button, confirmation screen, invalid link, manual paste fallback. Remaining: the weaknesses listed under V9 (sideloaded installs give no referrer; the address match is a convenience) |
| S12 | `GET /experiments/:id` returns the whole experiment (prompts, settings) to anyone, no login | ⬜ | new finding; see §2 |
| V5 V7 V10–V13 | Fidelity, context asymmetry, LLM confounds, timezone | ⬜ | |
| R1–R4 R9 S11 | Scheduler per experiment, worker + heartbeat, single Mongo client, tests, deps | ⬜ | |

---

## Sprint plan — from here to a deployable study app

*Written 26 Oct 2026 from the protocol draft "Lexi Takes the Lead" (25 Oct) and the owner's decisions of 26 Oct. **Goal of the sprint: the app is ready for deployment and the 14-day field study can start.** The protocol is kept privately (git-ignored, the repository is public): `docs/private/Proactive_Lexi_Experiment_Protocol_draft-2026-10-25.pdf` and the editable LaTeX source `docs/private/protocol/protocol.tex`, which is edited as the work below is decided, so that it can be pasted into Overleaf for submission. Owner = Itai; Claude = code and analysis. ⬜ open · 🟡 in progress/needs the owner · ✅ done.*

### Decisions made (26 Oct)

| # | Decision |
|---|---|
| D1 | The 87 % / 93 % fallback rate in the existing data is **accepted for now**: it comes from demo accounts that wrote little. It is **re-measured with real interaction** (rehearsal and pilot). |
| D2 | **Memory is built and used exactly the same way for every condition/heuristic** (the protocol: memory retrieval and behaviour inside a conversation are strictly identical across conditions). |
| D3 | When a participant has **no usable memory the fallback is sent — for every heuristic, the same way**. The fallback keeps the **meaning of the heuristic** that sent it (Affective: warm and supportive; Standard: neutral invitation). It is logged (`was_fallback`) and reported. |
| D4 | The **Finish button moves**: a participant could not press it where it is. |
| D5 | **Questionnaires are the owner's task**; participants come from **Prolific** and the study must verify they really take part (answer notifications, finish sessions, fill questionnaires). |
| D6 | The **protocol is unfinished**; finishing it is a task (X2, X3). |
| D7 | **One experiment per group** (Reactive / Standard / Affective); no assignment code. Condition = which experiment a participant belongs to. *Risk to handle: see P1.* |
| D8 | **English only**, everywhere in the code (the whole study is in English). |
| D9 | **Memory has two kinds** (see "Memory design" below). |
| D10 | **Data donation** (screen time) is **decided at the end**, with pros and cons recorded (Phase 6). |
| D11 | **Like/dislike micro-feedback** is not working at the moment; whether to keep it (participant burden) is decided later (Phase 6). |
| D13 | **Heuristic-memory lifecycle (M4):** **no expiry**; each event is used **once**; the event chosen is the highest meaningfulness score, ties broken by the most recent. A "second use" rule (score 8 or more, at least 3 days later, written as a follow-up) is **not built now**; it stays available as a switch if the rehearsal shows too many fallbacks. |
| D14 | **The LLM that writes the Affective notification also sees the recent dated summaries**, with the chosen event (if any) as the main subject. So even a day without a fresh event gives a notification that shows continuity. The **Standard** condition stays neutral and sees none of it. The notification stays **short** (one sentence, about 15 words). |
| D15 | **The chat LLM gets all the dated summaries in its system prompt in every conversation, for every participant of every condition** (identical across conditions), plus the memory that created the notification when the conversation was opened from one. |
| D12 *(proposed)* | The model gets **no web access**: it is not needed for the research question and would add uncontrolled variation between participants. |

### Memory design (agreed 26 Oct, to be built in Phase 2)

Both kinds are built **after every conversation, for every participant of every condition** (the condition only decides what the *notification* does with them).

1. **General memory — one dated summary per conversation.** Written when the conversation ends (Finish or inactivity timeout). If the participant continues the same conversation later, that conversation's summary is **replaced** by a new summary of the whole conversation (never appended as a second note, which is what happens today: summaries are made per analysed batch). Each summary carries the conversation's **date**. The chat model receives the dated summaries in its system prompt (kept within a token budget; the oldest are dropped first).
2. **Heuristic memory — specific events that answer a heuristic** (emotional events for Affective; upcoming events for Temporal; stated plans for Behavioural gap). Each is stored **separately**, with its **date**, its **source conversation** and a **score for how meaningful it is** (assigned by the LLM at extraction), so that when the heuristic is drawn the **most meaningful unused** one is chosen and the notification is written from it.
3. **What the chat model sees:** in **every** conversation all the dated summaries; in a conversation that was opened by a notification **also the heuristic memory that created that notification** (for every heuristic, not only Affective).
4. **Same pipeline for all conditions:** this also makes the protocol's measure "emotional memories generated" comparable across conditions, because it is computed the same way for everyone.

*Open (M4, to discuss):* how long a heuristic memory stays valid, and whether it may be used more than once.

### What the protocol requires that the code does not do yet (found 26 Oct)

| # | Protocol says | Code today | Task |
|---|---|---|---|
| F1 | Participants are randomly assigned to one of three conditions for 14 days | per-send random draw inside one experiment; **owner will use one experiment per group** | P1 |
| F2 | Memory retrieval in chat is **identical across conditions** | summaries are written only when the Affective heuristic is drawn, yet injected into every chat; the nudge's source context exists only for Affective | M1, M3 |
| F3 | "Emotional memories generated" is counted **for everyone** | memory is extracted only for the drawn heuristic, at send time | M1 |
| F4 | A **session disclosure score 1–10** from a post-interaction LLM analysis (a *different* score from the per-memory score; see M7) | does not exist | M7 |
| F5 | A conversation ends with the **Finish** button | not pressable for at least one participant | P6 |
| F6 | **Notification conversion** (reply within 60 min) and **latency to tap** | `opened_at` and `first_reply_at` are logged; no explicit "tapped" event | P7 |
| F7 | **Like/dislike micro-feedback** on opening a proactive intervention | **not working at the moment**; "opened from a notification" is also labelled unreliably (V8) | P4 |
| F8 | **Qualtrics bi-weekly** + in-app **IMS WEALTH** event surveys | not present (owner brings the questionnaires) | P2 |
| F9 | **Data donation**: external social-app screen time | nothing | decide at the end (Phase 6) |
| F10 | **Prolific** recruitment, ≥ 6 sessions/week, payment | no Prolific linkage | P5 |
| F11 | Consent page, demographic registration (name, age, gender) | forms exist; flow not verified for this protocol | P8 |
| F12 | English-speaking participants only | Hebrew in the code: static fallback templates (4 heuristic files), Hebrew-letter language detection, `he` defaults (experiment model, heuristic base class, scheduler helpers) | I4 |
| F13 | Time zones "compatible with the notification schedule" | scheduler windows are fixed to Asia/Jerusalem | I5 |
| F14 | Appendix A shows the **exact prompts** | assembled from several places (researcher prompt says "max 15 words", system suffix "20") | M6, X3 |
| F15 | The chat model can convey *when* past events happened | the chat prompt has **no date at all**; summaries and memories are undated | M2 |

### Phase 1 — Infrastructure (blocking)

| ID | Task | Who | Status |
|---|---|---|---|
| I1 | Upgrade Render to the always-on plan; confirm heartbeat every 30 min (R2a) | owner, then Claude checks logs | ⬜ |
| I2 | Restart-safe scheduler: re-plan the rest of today at startup, `misfire_grace_time`, heartbeat in the database (R2) | Claude | ⬜ |
| I3 | Signed **release** APK (keystore, `versionCode` bump, join page serves it) | owner (keystore) + Claude | ⬜ |
| I4 | **English only (D8)**: remove Hebrew templates and Hebrew-letter language detection; `defaultLanguage = en` as the model default; one language path in the prompts | Claude | ⬜ |
| I5 | Time zones: screen Prolific by time zone, or store the participant's time zone and schedule in it | decision + Claude | ⬜ |
| I6 | Close S12 (experiment endpoints that expose prompts and settings) | Claude | ⬜ |

### Phase 2 — Memory and notification logic (core)

| ID | Task | Who | Status |
|---|---|---|---|
| M1 | **The two-kind memory pipeline (D9)**, built after every conversation for every participant of every condition, outside the send path | Claude | ⬜ |
| M2 | **Dates**: each summary and memory carries its date; the chat prompt states today's date (participant's time zone); a notification's source memory says how long ago it happened | Claude | ⬜ |
| M3 | **Chat prompt content** (D9.3, D15): all dated summaries in every conversation + the memory behind the notification in a notification-opened conversation, for every heuristic (V7). **Automated test**: the chat prompt carries the same summaries for a Reactive, a Standard and an Affective participant | Claude | ⬜ |
| M4 | Heuristic-memory lifecycle **decided (D13)**: no expiry, once, ranked by score then recency; remove the 72-hour expiry; log which memory was used (`memory_id`) and how old it was | Claude | ⬜ |
| M5 | Fallback rule (D3) implemented the same for all heuristics; fallback messages keep the heuristic's meaning; for Affective the fallback uses the recent summaries (D14); reported in the logs | Claude | ⬜ |
| M6 | **Prompt design, one scenario at a time**: (1) chat persona, (2) per-conversation summary, (3) heuristic memory extraction with score, (4) Affective notification, (5) Standard (neutral) notification, (6) fallback messages, (7) the scheduling agent. Notifications are concise (one sentence, about 15 words). For each: agree the exact wording, implement it, then give it to the protocol (X3). Also: a single source of truth, and fix the 15 vs 20 word conflict | owner + Claude | ⬜ |
| M7 | **Session disclosure score (DV)**: one 1–10 score per conversation, measured on the whole transcript, the same way for every condition. It is an **outcome measure for the analysis, not a mechanism of the app**, so it is best computed **offline after the study** from the stored transcripts with a validated prompt (and a human-rated sample to check it). This is a different score from the per-memory score of D9.2. | Claude (analysis script) + owner (prompt wording) | ⬜ |

### Phase 3 — Study instrumentation

| ID | Task | Who | Status |
|---|---|---|---|
| P1 | **Randomisation across the three experiments (D7)**: no code needed, but participants must not choose or drift into a group. Either one Prolific screener, then **you randomise the Prolific ids into three lists** and run three studies with custom allowlists, or a **single randomising join link** (small code: balanced counter, n = 20 each). Also check that the three experiments are **identical except the proactive settings** (persona, model, prompts) | owner decision + Claude (config check, optional link) | ⬜ |
| P2 | **Questionnaires**: owner supplies Qualtrics bi-weekly items and IMS WEALTH; Claude integrates (links carrying the participant's id, when shown, a record of completion) | owner → Claude | ⬜ |
| P4 | Make the **like/dislike micro-feedback** work again and label "opened from a notification" reliably (V8) — **only if it is kept** (Phase 6) | Claude | ⬜ |
| P5 | **Prolific integration**: capture Prolific id, study id and session id at join; completion code/redirect; per-participant **compliance view** (notifications answered, sessions per week, questionnaires done) | owner (Prolific study) + Claude | ⬜ |
| P6 | **Finish button**: move it and fix the screen insets so nothing sits under the status bar | Claude | ⬜ |
| P7 | Explicit "notification tapped" event with timestamp (latency, 60-min conversion) | Claude | ⬜ |
| P8 | Consent page and demographic registration verified end to end | owner + Claude | ⬜ |

### Phase 4 — Verification and hardening

| ID | Task | Who | Status |
|---|---|---|---|
| H1 | Data-only pushes so the lock-screen text is hidden also when the app is closed | Claude | ⬜ |
| H2 | One shared database client, schedule fallback quirks, tests for the engine, dependency updates (R3, R4, R9, S11) | Claude | ⬜ |
| H3 | LLM/prompt confounds, silent LLM failures, gap-check and time-zone issues (V10–V13) | Claude | ⬜ |
| H4 | **Dress rehearsal**: 3–5 internal participants, one per condition, 3–4 days, checking every logged measure end to end | owner + Claude | ⬜ |
| H5 | Re-measure the fallback rate on the rehearsal data (D1) | Claude | ⬜ |

### Phase 5 — Documents and approvals

| ID | Task | Who | Status |
|---|---|---|---|
| X1 | **Ethics approval** — start now (long lead time); it needs the notification design and the data-donation decision | owner | ⬜ |
| X2 | **Protocol, pass 1 (now)**: close the open points — required interaction frequency and minimum conversation length for a valid session (≥ 6 sessions/week), statistical models and power, Results/Discussion text. Edit `docs/private/protocol/protocol.tex` | owner (+ Claude on request) | ⬜ |
| X3 | **Protocol, pass 2 (after the prompts of M6 are decided and implemented)**: Appendix A with the exact prompts exported from the code (persona, per-conversation summary, memory extraction with score, Affective notification, Standard notification, fallback, disclosure scoring), and the fallback rule (D3). Edit the same `.tex` | Claude exports, owner writes | ⬜ |
| X4 | Prolific pilot (a few participants), then launch | owner | ⬜ |

### Phase 6 — Decide at the end

**P3 — Data donation of external social-app screen time (H5).**

| Pros | Cons |
|---|---|
| An **objective** measure of social engagement, no self-report bias | Needs the Android **usage-access** permission, which the participant must enable by hand in system settings: a scary step that raises **drop-out and refusals** |
| Android keeps several days of history, so a **baseline** can be read when the participant joins | **Ethics and consent** weight: app-usage data is sensitive; Prolific and the ethics board will look closely |
| Only a few apps and minutes per day are needed (small, aggregated data) | **Weak construct**: minutes in WhatsApp or Instagram are not social connectedness, and can go up for reasons unrelated to the agent |
| A novel contribution for a field-study paper | n = 20 per group with noisy daily minutes gives **low power** for H5, which is the most exploratory hypothesis |
| | Engineering and testing time: permission flow, daily upload, per-phone differences, the study app's own usage must be excluded |

*Claude's opinion:* **do not build it for the first study.** H5 is the weakest hypothesis, the cost (retention, ethics, engineering) falls on H1–H4, which carry the paper, and the power is low. Measure social engagement with a **short self-report scale in the Qualtrics surveys** instead (cheap, no permission), report H5 as exploratory, and revisit data donation after the pilot or for a follow-up study. If it is kept, make it an **optional opt-in** sub-study, reported separately.

**P4 — Keep the like/dislike micro-feedback?** It is the protocol's real-time measure of intrusiveness (DV 4), but it adds a step every time a participant opens a notification and can itself change the experience. Decide after the rehearsal (H4), with the participants' own feedback on the burden.

### Open design questions (for the discussion)

1. **The size and shape of the dated summaries** in the chat prompt (token budget instead of a fixed 30; optionally one running profile paragraph).
2. **Web access (D12):** confirm that the model has none.
3. **P1:** which randomisation route (Prolific lists or a randomising link).
4. **M6:** the exact wording of each prompt, starting with the Affective notification.

*Protocol open points copied from the draft (so they are not lost): "Verify required interaction frequency? Minimum conversation length to count as a valid interaction?", "Verify: confirm specific statistical models and assure adequate statistical power", A.2 "add the prompt added in code — what about the score it should give?", A.3 "change? … should add the rows added to the prompt inside code", A.4 "[Paste the sentiment analysis prompt here]".*

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

### V1. The daily notification limit was never applied **[V]** — ✅ fixed
Python looked for `proactiveSettings.maxDailyNotifications`, which the Node schema and dashboard never had — so nothing ever limited
how many notifications a participant got. The dashboard already expresses the number per day through the schedule
("notifications per user" for random windows and the AI mode, or the number of fire times for exact mode), so no separate setting was added.
*Fix (done):* `services/schedule_utils.daily_quota()` derives the per-day maximum from the schedule, and `coordinated_send_and_inject`
— the single place every send passes through, for all three modes — skips a participant whose sends since local midnight have reached it.
The scheduler uses the same module, and tests check that the jobs it registers match the quota. If the database cannot be read the send is skipped rather than risked.
*Also fixed (V1b):* the dashboard rebuilt `proactiveSettings` from scratch on every save, so `defaultLanguage` (and any key it does not edit) was deleted and Python fell back to English. The save now spreads the existing settings first.
*Also done with V2:* the quota in force is stored on every log row (`daily_quota`, `sent_today_before`).

### V2. Only successful sends were logged **[V]** — ✅ fixed
`log_proactive_event` used to run only inside `if notification_result:`, so failures, skips and control draws left no row, the docstring's
"delivery success rate = sent / total" could not be computed, and the Sent → Opened → Replied funnel (sprint item 2.2) was not implemented.
*Fix (done):* every attempt now writes exactly one row (`services/log_schema.py`) with `status` ∈ `sent · reactive · skipped_day · skipped_quota · skipped_quota_unverified · heuristic_failed · injection_failed · conversation_failed · dropped_gatekeeper · fcm_failed · error`,
a `reason`, the **drawn** heuristic, `conversation_id`, `daily_quota` and `sent_today_before`, and `llm_model_used`.
Fields that do not apply are `null` rather than a misleading default. The API stamps `opened_at` (first fetch of the conversation) and `first_reply_at` (first participant message) on `sent` rows.
Tests drive the real send loop through every outcome and assert exactly one row each. See [`DATA_AND_ANALYSIS.md`](DATA_AND_ANALYSIS.md) for the schema and queries.
*Still open:* `used_static_template` (V11), `temperature` (V10), memory id/age (V5), a code-version stamp; rolling back a failed send is V3.

### V3. Nothing was rolled back when a send failed after injection **[V]** — ✅ fixed
The loop overwrote the participant's `agent.firstChatSentence`, pre-created a conversation, and only then checked the gatekeeper and
sent FCM. A failure left the opener injected, a phantom conversation behind, the participant's conversation count and the experiment's
session counts inflated, and — for Affective — the memory already marked `used`. The participant would later see a proactive
message they were never notified about.
*Fix (done):* before injecting, the engine snapshots the fields it will overwrite (`services/injection_state.py`). If anything fails afterwards
it puts them back, deletes the pre-created conversation and reverses the counters the API bumped (refusing if the participant already wrote in it),
and gives the memory back (`undo_selection`, implemented for Affective; the other heuristics only change state after a successful send).
The gatekeeper check now runs *before* the conversation is created, so the most common drop leaves nothing to clean up. If the user state cannot be read,
nothing is sent. Each rollback step is independent and never raises; the log row's `reason` says what was undone (`| rolled back: greeting restored, conversation discarded, memory un-used`).
*Not covered:* if the API created the conversation but its response was lost (timeout), the engine cannot know and nothing is discarded.

### V4. The logged `llm_model` was not necessarily the model used **[V]** — ✅ fixed
`override_model()` mutated a process-wide singleton and was only called when the experiment had `llmModel` set, so after one experiment used `claude-…`
every later participant and cycle kept using it until restart, while the log recorded the experiment's setting.
*Fix (done):* `ProactiveLogic.use_model()` is called for **every** participant — the experiment's model, or the environment default when none is set —
and `llm_model_used` (the model actually called) is logged next to `llm_model` (what was asked for). Unit-tested, including that the loop selects the model per participant.

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

*Measured on 25 Oct 2026* (read-only query on `proactive_logs`; 263 sent rows, 7 Aug – 14 Oct, one experiment, 6 participants, all written before the V2 logger so only successful sends exist):

| Heuristic | Sends | Fallback (no usable memory) | Memory-based |
|---|---:|---:|---:|
| Affective | 203 | **176 (87 %)** | 27 |
| Temporal | 28 | **26 (93 %)** | 2 |
| Generic | 32 | 0 | 32 (by definition) |
| Behavioural gap | 0 | — | — |

The cause is supply versus demand, not a bug in one heuristic: the participants wrote 109, 18, 10, 18, 11 and 31 messages in total against 130, 43, 31, 26, 20 and 13 sends, and each nudge creates a new conversation, so most conversations never contain a participant message. The 36 emotional memories that were extracted were **all used once** (none expired unused), and only 5 future events were ever mentioned. A memory can fire a nudge only once, so with a nudge per day the fallback rate is set by how much participants write. Caveats: this is a small demo/friends experiment, one account sent 130 nudges (probably development testing), and V6 (replies in already-scanned conversations were missed) was fixed after these rows were written, so the rate may be lower with the current code. The weights of that experiment are currently 100 % Affective, so it has no between-condition comparison at all.

### V6. Conversations were scanned once and never again **[V]** — ✅ fixed
Affective and Gap marked a conversation as scanned after the first pass, even if it was empty. So an ongoing chat analysed at message 3 never had
messages 4+ read, and the **pre-created notification conversation has no participant messages when the next cycle runs**, so it was marked scanned
and the participant's later reply in exactly that conversation was never analysed. Failed LLM calls were also marked scanned, losing that data for good.
Temporal had the opposite problem: it re-read its newest 5 conversations on every cycle (cost, and `future_mentions` growth).
*Fix (done):* every memory-building heuristic now tracks progress **per conversation** as the highest participant `messageNumber` analysed
(`proactiveMemory.affective_scan_progress`, `gap_scan_progress`, `temporal_scan_progress`; `services/scan_progress.py`).
A conversation that grew is analysed again for its **new** messages only; one with no participant messages yet stays pending until the participant replies;
progress advances only after a successful extraction, so a failed LLM call is retried next cycle. Conversations the old scheme had already scanned
(`*_scanned_conversation_ids`) are migrated on first sight without re-extracting, to avoid duplicate memories. Affective also skips a memory it already extracted
for that conversation and no longer loses a whole conversation to a malformed score such as "7/10". At most 3 conversations (5 for Temporal) are analysed per cycle,
newest first; the rest wait for the next cycle.
*Side effect to know:* conversation summaries (Affective) are now produced per analysed batch of new messages, so a long conversation can yield several summaries in the rolling window of 30.
*Limit:* a conversation that was in the old scheme and grew *before* this deployment keeps the messages it had at migration as "already analysed".

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
*Partly addressed:* the Android app wrote its "opened from notification" flag into one preferences file while the JavaScript bridge read another, so the web app never received it (found during the S3/S6 work; the file name is now shared in `AndroidBridge`). The web-side heuristic above (first view of any one-message conversation) is still open, and with the Android signal now working you should re-check what the annotation control does after a notification tap.

### V9. Deferred deep link can assign the wrong experiment **[V]** — 🟡 server side fixed, app side open
`matchSession` matched on client IP only (newest unmatched row within 60 min). On campus Wi-Fi/NAT, CGNAT, VPNs or an IPv4/IPv6 mismatch, two participants could swap experiments,
or match nobody, and the result is stored permanently on the phone.
*Fixed on the server:* the match is made only if every unused download from that address belongs to the **same** experiment (several downloads for one experiment — a room of participants — still work, each device takes the newest).
If one address has downloads for **different** experiments the server answers "ambiguous" (HTTP 200, no experiment) and the app falls back to its manual screen instead of guessing.
IPv6 addresses are compared on their /64 prefix, so a phone's browser (download) and app (first launch) still match when only the interface identifier differs; sessions are claimed atomically so a download is never assigned twice.
Outcomes are counted in a new `apk_match_events` collection (`matched`, `ambiguous`, `none`, `lost_race`, with candidate counts and no addresses), so the match rate can be measured — see [`DATA_AND_ANALYSIS.md`](DATA_AND_ANALYSIS.md). Raw IPs are no longer written to the server logs, and the endpoint no longer dumps other participants' IPs.
The match response also carries `experimentTitle` for a confirmation screen.
*Written for the app (option 1, chosen); built, installed and tested on a phone on 25 Oct — results in [`ANDROID_TEST_GUIDE.md`](ANDROID_TEST_GUIDE.md#results-of-the-first-test-run):*
1. **"Open Lexi" hand-off.** The join page now has an *Open Lexi* button (an Android intent link, with a plain `lexi://join/<id>` fallback) that opens the installed app with the experiment id, independent of the network address. The app registers `lexi://join/<id>` in its manifest and validates the id (exactly 24 hex characters) before using it.
2. **Confirmation screen.** Whether the experiment comes from the button or from the network-address match, the participant sees "You are joining *Study name* — Continue / This is not my study" before it is stored permanently. The title comes from a new minimal public endpoint, `GET /experiments/:id/public` (title and active flag only).
3. **Manual fallback accepts the link participants actually have.** It now takes `/join/<id>` and `/e/<id>` links, and the app always loads `<FRONTEND_BASE_URL>/e/<id>` built from the validated id — never a host taken from pasted text.
*Limits:* sideloaded apps give no install-referrer, so if a participant opens Lexi straight from the installer (not from the page) the app falls back to the address match plus the confirmation screen. `X-Forwarded-For[0]` is client-controlled unless a trusted proxy overwrites it; the match is a convenience, never a security control.

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
| S2 ✅ | **High** | `POST /users/fcm-token` and `/register-device` take a `userId` from the body with no authentication. Anyone who knows an id can replace a participant's push token (hijacking their notifications). The service returns the full user document, including the bcrypt hash. **[R]** — route has no middleware **[V]** | `usersRouter.router.ts:12-13`, `users.service.ts:189` | derive id from the JWT; return `{ok:true}` — **fixed:** login required; the user id is taken from the cookie and a different `userId` in the body is refused (403); the response no longer contains the user record; unit-tested |
| S3 🟡 | **High** | `MainActivity` is `exported=true`, loads any `deepLinkUrl` extra into a WebView that has the `Android` JS bridge attached (`getFCMToken`, `getCurrentUserId`, `sendTokenToServer`). Any installed app can open an attacker page with access to the bridge. **[R]** (manifest **[V]**) | `AndroidManifest.xml:25`, `MainActivity.kt:74-91,225-240,310` | allow-list your own origin; attach the bridge only there — **device-tested 25 Oct (most checks):** only addresses with the build's own scheme, host and port (`UrlPolicy`) load in the WebView (notification links, saved links, in-page navigation; other sites open in the browser); the saved experiment URL is rebuilt from a validated id; the bridge lost `getCurrentUserId`, `setOpenedFromNotification`, `sendTokenToServer`, `initializeTokenTransmission`; `allowFileAccess`/`allowContentAccess` off, mixed content blocked outside debug builds |
| S4 ✅ | **High** | `/join/:experimentId` writes the raw parameter into HTML (reflected XSS on your API origin) and inserts it into `apk_sessions` without validation or rate limit. **[V]** insert, **[R]** XSS | `joinController.ts` | `/^[a-f0-9]{24}$/`, verify the experiment exists, escape — **fixed:** id must be 24 hex characters and an existing experiment, HTML-escaped, downloads limited to 60 per 10 min per IP; unit-tested. (TTL for stored IPs is still open, see S7) |
| S5 ✅ | **Med** | CORS with `credentials: true` accepts any origin that *contains* your project name and ends in `.vercel.app` — anyone can register such a project. A rejected origin returns a 500 stack trace. A LAN IP is left in the allow-list. **[R]** | `server.ts` | exact-match regex on your Vercel slug — **fixed:** exact origins; dev addresses only outside production; previews only via `CORS_PREVIEW_SUFFIX`; refused origins get no CORS headers instead of a 500; unit-tested |
| S6 🟡 | **Med** | Android: `allowBackup="true"` with empty rules (auth cookie + prefs go to cloud backup); `usesCleartextTraffic="true"`; **debug** APK distributed; minify off; notification text visible on lock screen (emotional content!); wake-lock acquired and released immediately; FCM token and user id written to logcat. **[V]** manifest, **[R]** rest | `AndroidManifest.xml`, `build.gradle.kts`, `LexiMessagingService.kt`, `AndroidBridge.kt` | `allowBackup=false`, debug-only cleartext config, signed release build, `VISIBILITY_PRIVATE` — **device-tested 25 Oct (most checks):** `allowBackup=false` with empty backup and device-transfer rules; release builds are https-only (plain-http local addresses moved to a debug-only network config); lock-screen text hidden via `HIDE_TEXT_ON_LOCK_SCREEN`; token and user id no longer logged. **Not done:** a signed release APK (the join page still serves `app-debug.apk`) and minification — see OPERATIONS §6 |
| S7 | **Med** | Raw IPs kept in `apk_sessions` with no TTL; `matchSession` logs whole session documents and other users' IPs; the landing page says "fully anonymous". Server logs user message text ("MESSAGES SENT TO LLM"). **[R]** | `joinController.ts`, `experimentsController`, `conversations.service.ts` | 24 h TTL index; delete those logs; **check wording against your ethics approval** |
| S8 ✅ | **Med** | Stale-token cleanup treats any error containing "not found" as "delete this token and set `isProactive=false`". `fcm_service.py` itself says "not found" also means *wrong Firebase project*. A misconfigured deploy would silently opt **every** participant out. **[V]** | `research_service.py` (`_is_stale_token_error`) | **fixed:** only `UnregisteredError` and a malformed-token `InvalidArgumentError` count; `SenderIdMismatchError` deliberately excluded (a wrong service account looks the same) |
| S9 | **Low–Med** | `PUT /experiments` and other admin routes appear to have no `isAdmin` check (upstream pattern); JWT has no `expiresIn` and is re-issued on every `/user`. **[R]**, suspected | `experimentsRouter`, `users.service.ts` | auth middleware + expiry |
| S10 | **Low–Med** | `get_all_proactive_users` sets `isProactive=true` for every user with a token and no flag. Fine operationally; check it matches how consent is recorded. **[V]** | `research_service.py:118` | confirm with ethics text |
| S11 | Low | `requests==2.31.0` has a known CVE (fixed in 2.32); all Python deps are pinned to 2023 versions. **[V]** | `requirements.txt` | bump |
| S12 | **Med** | `GET /experiments/:id` (and `/features`, `/content`, `/registrationForm`, `/conversationForms`) return experiment data to anyone who knows the id, with no login. The first returns the whole document, including `proactiveSettings` (the researcher's prompts, weights, schedule). **[V]** (`getExperiment` returns the document unfiltered) | `experimentsController.getExperiment` | return only what a participant's browser needs, or require login; the app now uses `GET /experiments/:id/public` instead |

---

## 3. Reliability & operations

- **R1. The scheduler ignored which experiment fired — ✅ fixed. [V]** Every job — whichever experiment's fire time triggered it — calls `run_full_proactive_cycle()` for *all* enabled experiments' users. With two experiments on different schedules, participants are notified at the other experiment's times; only the per-user weekday check and the daily quota (added in V1) limit it. *Fix (done): every job now carries its experiment id and only that experiment's participants are processed; the hard-coded fallback jobs still cover all.*
- **R2a. The Render service was on the free plan, so the scheduler slept. [V, measured 25 Oct 2026]** `lexi-server` was listed as `plan: free`. Free web services sleep after about 15 minutes without web traffic, and the scheduler runs inside that service, so it only existed while someone happened to visit. The Render logs show a fresh instance starting every few hours (20, 21, 23, 24, 25 Oct) and **no instance ever reaching its first 30-minute heartbeat**; the last logged notification was 14 Oct. The scheduled sends of a real study cannot work on this plan. *Fix (owner, 25 Oct): upgrade to the paid always-on plan (Starter).* After the upgrade, confirm that a heartbeat line appears every 30 minutes in the Render logs.
- **R2. The scheduler is a background subprocess of the web service. [V]** `render-start.sh` runs `python scheduler.py || echo …` in the background; if it dies it is not restarted and nothing alerts you. The job store is in memory, so a redeploy loses today's AI-planned times (the planner only runs at 00:01), and APScheduler's default `misfire_grace_time` is 1 s, so a busy moment silently skips a job.
  *Fix:* deploy it as a separate Render **Background Worker**, write a heartbeat document to Mongo and alert when it goes stale, run the AI planner at startup as well as at 00:01, set `misfire_grace_time`.
- **R3. One shared MongoDB client, reconnected on every call. [V]** `connect()` builds a new `MongoClient` each time and overwrites `self.client`; `disconnect()` closes whichever is current. APScheduler runs jobs on a thread pool, so two overlapping jobs can close each other's client mid-query. It is also slow (a new TLS handshake per operation) and leaks the client if `connect()` is called twice. *Fix:* create one `MongoClient` at import and never close it — it is thread-safe.
- **R4. Fallback schedule sticks. [V]** If Mongo is briefly unreachable at startup the hard-coded `13:45/17:30/21:15` jobs are registered and the hourly reload deliberately leaves them alone forever. Separately, an experiment whose `fireTimes` is empty silently inherits those same three times.
- **R5. Four code paths reset the injected opener — ✅ fixed. [V]** Tracing the code showed the real picture: only the reset inside `conversations.service.message()` (via `users.service.resetInjectedPromptIfNeeded`) was live. The controller's reset and the "expire after 2 h on app open" reset only fire when `injected_prompt_reset_after` exists, which the engine no longer writes — except on user documents left by earlier versions, where the expiry path could delete `agent.firstChatSentence` outright (it copied from a field the other path had already removed). The live path also did read-then-write, so a participant's reply landing between the engine's injection and its conversation creation could replace the fresh opener with the old greeting, and the notification would open onto the normal greeting.
  *Fix (done):* a single reset (`services/greetingReset.ts`) used by everything: one atomic update that copies the saved original back and removes the saved fields, running only when a non-empty original exists (so it can never blank the greeting) and cleaning the legacy `injected_prompt_reset_after` field. The two dormant paths are deleted. Finishing a conversation uses the same function. On the engine side `_verify_opener` checks, right after the conversation is created, that its first message is the proactive message flagged `isProactiveOpener`; if not, the send is rolled back (V3) and logged as `conversation_failed` / "opener mismatch" instead of notifying onto the wrong greeting.
  *Behavior change:* there is no 2-hour expiry any more (the engine already documented "no time-based expiry"); a proactive greeting stays until the participant replies or finishes a conversation. The atomic pipeline update follows the same pattern as the code it replaces but was verified with unit tests against a fake database, not against a live MongoDB — reply to a test notification after deploying to confirm.
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
5. **Send pushes as data-only messages. [V]** The engine sends a `notification` block plus data. When the app is in the background or closed (the normal case for a nudge) Android draws the notification itself and never calls the app's own handler, so the lock-screen hiding (S6), the full-screen wake-up and the deep link built by `LexiMessagingService` do not run. Android passes the data (`conversationId`, `experimentId`) as intent extras instead, and the app only looked for a `deepLinkUrl` extra, so a tap opened the study home rather than the conversation. *App side fixed (untested):* `MainActivity` now builds the conversation URL from those two validated ids as well. *Still open (changes delivery behaviour, test with a phone):* send data-only messages with high priority so the app always handles them; `LexiMessagingService` already falls back to `data["title"]` and `data["body"]`.
6. **Two languages, one database** is the largest source of contract drift (V1 is one). A shared JSON-schema file for `proactiveSettings` and `proactiveMemory`, checked in both codebases, would stop this class of bug.

---

## 5. Docs vs. code (why the docs were rewritten)

| Old claim | Reality |
|---|---|
| `SYSTEM_ARCHITECTURE`: "forms / dataAggregation are thesis analytics" | Both are **unchanged upstream Lexi code**; not yours to claim |
| "Researchers set `maxDailyNotifications` in the dashboard" | No such setting; the schedule defines it (V1) |
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
| **This week** (small, high value) | `allowBackup=false` · allow-list WebView origin · debug-only cleartext · signed release build | S3 S6 |
| **Before more participants** | confirm join with the participant | V9 |
| **Before the analysis** | Measure fallback rate · decouple memory building · align temperature/limits · timezone · contexts across conditions | V5 V7 V10 V11 V12 V13 |
| **Hardening** | Separate worker + heartbeat · single Mongo client · per-experiment scheduling · tests · pin/update deps | R1–R4 R9 S11 |
