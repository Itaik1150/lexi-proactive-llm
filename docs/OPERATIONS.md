# Operations Guide

Setting the system up locally, deploying it, and keeping it running during a study.

## 1. Requirements

| Tool | Version | Why |
|---|---|---|
| Node.js | **18.x** (`>=18.14.2 <19`, see `Lexi/server/.nvmrc`) | API and React build |
| Python | 3.12 | proactive engine (`zoneinfo` needs 3.9+) |
| MongoDB Atlas | any tier | shared database |
| Firebase project | — | push notifications; needs a service-account key |
| Android Studio | current | building the app |
| OpenAI and/or Anthropic API key | — | message generation |

## 2. Configuration

Three components, three `.env` files. Copy each `.env.example` and fill it in — the real files are git-ignored.

| File | Variables |
|---|---|
| `Lexi/server/.env` | `PORT`, `NODE_ENV`, `MONGODB_URL`, `MONGODB_DB_NAME`, `JWT_SECRET_KEY`, `FRONTEND_URL`, `APK_DOWNLOAD_URL`, optional `CORS_EXTRA_ORIGINS`, `CORS_PREVIEW_SUFFIX` |
| `Lexi/client/.env` | `REACT_APP_API_URL`, `REACT_APP_FRONTEND_URL` |
| `logic-python/.env` | `MONGODB_URL`, `MONGODB_DB_NAME`, `MONGODB_USERS_COLLECTION`, `LLM_PROVIDER`, `LLM_MODEL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `SERVICE_ACCOUNT_JSON` or `SERVICE_ACCOUNT_JSON_CONTENT`, `FCM_DEFAULT_TITLE`, `LEXI_SERVER_URL`, `FRONTEND_BASE_URL` |
| `android-app/app/build.gradle.kts` | `SERVER_URL`, `FRONTEND_BASE_URL` (`buildConfigField`) |
| `android-app/app/src/google-services.json` | downloaded from the Firebase console; git-ignored, so a fresh clone **cannot build** until you add it |

CORS: with `NODE_ENV=production` the API only accepts browser requests from the deployed web app and `FRONTEND_URL`. If the web app is ever served from another address (custom domain, Vercel preview), add it to `CORS_EXTRA_ORIGINS` (or set `CORS_PREVIEW_SUFFIX` for previews); otherwise the browser will block API calls.

Rules: never commit secrets; use a database user limited to the one database; give the Python engine and the Node API the **same** database.
When testing locally, point `LEXI_SERVER_URL` at your local API — its default is production.

## 3. Run locally

```bash
# API
cd Lexi/server && npm install && npm run dev            # http://localhost:5000

# Web app
cd Lexi/client && npm install && npm start              # http://localhost:3000

# Python engine (one cycle, no timers)
cd logic-python
python -m venv venv && source venv/bin/activate         # Windows: venv\Scripts\activate
pip install -r requirements.txt
python run_cycle.py

# Python engine (the real scheduler)
python scheduler.py
```

Unit tests (no database or network needed):

```bash
cd logic-python && python -m unittest discover -s tests -v   # engine
cd Lexi/server && npm test                                   # API hardening
```

To try a send end to end you need a user document with `experimentId`, `fcmToken` (a real device token), `isProactive: true`,
and an experiment with `proactiveSettings.enabled: true` and non-zero weights.

## 4. Deploy

These are the settings the scripts are written for; check them against your actual Render and Vercel dashboards.

| Piece | Where | How |
|---|---|---|
| Web app | Vercel | project root `Lexi/client`; set the two `REACT_APP_*` variables |
| API + scheduler | Render web service | build `bash scripts/render-build.sh`, start `bash scripts/render-start.sh` (Node in the foreground, Python scheduler in the background) |
| Database | MongoDB Atlas | network access limited to Render's outbound IPs |
| Android APK | GitHub release or similar | build a **signed release** APK; set `APK_DOWNLOAD_URL` |

Render environment: everything from the server table above **plus** everything from the Python table. Put the Firebase JSON in
`SERVICE_ACCOUNT_JSON_CONTENT` (one line) or as a Secret File at `/etc/secrets/firebase.json`.

`scripts/render-start.sh` swallows scheduler failures so the API keeps running — which also means a dead scheduler is silent.
See the runbook.

## 5. Runbook during a study

**Daily**
- Render logs contain `💓 Scheduler heartbeat` every 30 minutes. No heartbeat ⇒ the scheduler is down; restart the service.
- After a redeploy, if any experiment uses `ai_agent` scheduling and it is past 00:01, today's planned times are lost.

**Before changing an experiment mid-study** — export `experimentFeatures.proactiveSettings` and record the Git commit; it changes the meaning of later data.

**When a participant reports no notifications**
1. `users.isProactive` and `users.fcmToken` set? (token errors clear both — REVIEW S8)
2. Notifications allowed in Android settings? Battery optimisation off for the app?
3. Any `proactive_logs` row for them today? If not: weekday allowed? `enabled`? weights not all `reactive`? daily quota already reached (the log line says `daily quota reached (n/m)`)?
4. Render logs around the scheduled time: search for their username.

**Rotating credentials** — Atlas user password (then Render env `MONGODB_URL` in *both* services' config), `JWT_SECRET_KEY` (logs everyone out),
OpenAI/Anthropic keys, Firebase service account (create new key in Firebase console, replace, delete the old one).

## 6. What to set up next

- Run the Python engine as its own Render **Background Worker**, and write a heartbeat document to Mongo that something alerts on.
- Sign and minify the Android release; disable cloud backup.
- Add a small `pytest` suite for the pure functions in `logic-python`.

Details and reasons: [`REVIEW.md`](REVIEW.md).
