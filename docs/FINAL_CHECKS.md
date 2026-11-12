# Final checks before submission

Everything here is a live check on the real system that we go over **together, once all changes are
made** (owner decision, 12 Nov 2026). Unit tests run on every change and are not listed here; this
file is only for what has to be seen working on the phone, on Render or in the database.

Status: ⬜ not checked yet · ✅ passed · ❌ failed (with a note).

## A. Infrastructure

| # | Check | How | Who | Status |
|---|---|---|---|---|
| A1 | Render runs on the Starter plan and never sleeps | Render dashboard shows "Starter"; the scheduler heartbeat appears every 30 min in the logs for a full day | owner upgrades, Claude reads the logs | ⬜ |
| A2 | The latest code is live | the deploy of the last commit is "live" on Render; the scheduler start-up log lists the memory job and the random planner | Claude | ⬜ |

## B. Timing (D20: random times, same rule for both proactive groups)

| # | Check | How | Who | Status |
|---|---|---|---|---|
| B1 | Every proactive experiment is set to **Random window, 09:00–19:00, 2 per user** (UK time) | dashboard; Claude reads `experimentFeatures.proactiveSettings.schedule` of each experiment. *12 Nov: set on the demo experiment by Claude; the three study experiments do not exist yet* | owner sets, Claude verifies | ⬜ |
| B2 | Each participant gets their own 2 times per day, inside the window, at least 2 h apart | `notification_plans`: one document per participant per day, times differ between participants, never before the window start | Claude | ⬜ |
| B3 | The notifications are actually sent at the planned times | `proactive_logs` rows with status `sent` within a minute of each planned time, at most 2 per participant per day | Claude | ⬜ |
| B4 | A restart in the middle of the day does not lose or double the day's notifications | after a deploy during the window: a plan with `replanned_after_restart: true`, and no participant above 2 that day | Claude | ⬜ |
| B5 | All clock times are UK time | the scheduler's start-up log prints `Study time zone : Europe/London`; planned times in `notification_plans` are between 09:00 and 19:00; the dashboard shows Europe/London; the Prolific study screens for UK residents *12 Nov: after the deploy the engine reported `Europe/London`, and the first plan was drawn inside the window (14:47 and 16:48 UK time, 2 h 1 min apart, marked as re-planned after a restart).* Still to do: the Prolific filter | Claude + owner (Prolific) | 🟡 |

## C. Memory (M1–M3)

| # | Check | How | Who | Status |
|---|---|---|---|---|
| C1 | A finished conversation gets a dated summary and its events within about 2 minutes | press Finish on the phone; Claude reads the participant's `conversation_notes` and `emotional_memories` | owner + Claude | ⬜ |
| C2 | A conversation left open is analysed after 30 minutes of silence | leave one open; check after 35 min | owner + Claude | ⬜ |
| C3 | The chat remembers earlier conversations, with correct timing | new conversation, ask "what did I tell you about my week?"; Lexi mentions the right events and says when they happened | owner | ⬜ |
| C4 | Nothing is invented from Lexi's own words | read 5 summaries of real conversations; no detail only Lexi said | owner + Claude | ⬜ |

## D. Notifications (M4, M5)

| # | Check | How | Who | Status |
|---|---|---|---|---|
| D1 | Affective notification about an event: one sentence, about 15 words, names the event, first name at most once | receive one on the phone; `proactive_logs` shows `message_source: event`, `memory_id`, `memory_age_days` | owner + Claude | ⬜ |
| D2 | Opening it gives a chat that knows why Lexi reached out | reply to it; Lexi continues about that event naturally | owner | ⬜ |
| D3 | Affective without a new event uses the recent days (`summary`), and a brand-new participant gets the warm pool (`pool`) | test account with no unused events; a fresh account | Claude | ⬜ |
| D4 | Standard notification comes from the neutral pool, with no name | Standard test account; text is in `docs/MESSAGE_POOLS.md` | owner + Claude | ⬜ |
| D5 | No pool message repeats before all were used, never twice in a row | after several days, `pool_state` and the sent texts in `proactive_logs` | Claude | ⬜ |
| D6 | After a pool or summary notification the chat does not talk about an old event | open such a notification; Lexi does not bring up an unrelated earlier event | owner | ⬜ |
| D7 | Reactive participants never receive a notification | `proactive_logs` for the Reactive experiment: only `reactive` rows, no `sent` | Claude | ⬜ |

## E. Study setup

| # | Check | How | Who | Status |
|---|---|---|---|---|
| E1 | The three experiments are identical except their proactive settings (persona, model settings, first sentence) | Claude compares the three experiment and agent documents | Claude | ⬜ |
| E2 | Old demo and test data is reset before the rehearsal and before the study | counts of conversations, notes and events for test accounts are zero | owner approves, Claude runs | ⬜ |
| E3 | The consent text is the BGU one approved by ethics (not the old Cambridge text) | open the consent page in the app | owner | ⬜ |
| E4 | The questionnaires open at the right moments and are recorded as completed | (after P2 is built) | owner + Claude | ⬜ |

## G. Dashboard and access (I6, P7, P9)

| # | Check | How | Who | Status |
|---|---|---|---|---|
| G1 | The admin dashboard still works after logging in: experiments list, editing an experiment, agents, forms, data export (JSON and Excel) | owner clicks through each | owner | ⬜ |
| G2 | Without a login the admin routes are closed | **12 Nov, live server, no cookie:** experiments list, full experiment, agents, forms, engine config and both data exports answer 401; health, public info, features (two flags only) and content stay open. Still to do: a participant's login gets 403 | Claude | ✅ (403 case open) |
| G3 | A participant can still register, log in, chat and finish (nothing a participant needs was closed) | owner on the phone with a fresh account | owner | ⬜ |
| G4 | The proactive-settings window shows the real prompts, pools and memory rules, with a recent "published" time | owner opens it; texts equal `docs/MESSAGE_POOLS.md` and protocol Appendix A | owner + Claude | ⬜ |
| G5 | Tapping a notification is recorded | tap one on the phone; its `proactive_logs` row has `tapped_at` within seconds of the tap | owner + Claude | ⬜ |
| G6 | English only | a test account stored as Hebrew still gets English notifications | Claude | ⬜ |

## F. Protocol

| # | Check | How | Who | Status |
|---|---|---|---|---|
| F1 | No highlighted placeholder is left (daily window, time zones, Prolific details) | search `\hl{` and `\todo` in `docs/private/overleaf/main.tex` | owner + Claude | ⬜ |
| F2 | Every prompt in Appendix A is exactly the one in the code | compare A.1–A.5 with `memory_pipeline.py`, `affective.py`, `message_pools.py` and the agent's persona | Claude | ⬜ |
| F3 | The protocol in Overleaf is the latest version | `git status` in `docs/private/overleaf` is clean and pushed | Claude | ⬜ |
