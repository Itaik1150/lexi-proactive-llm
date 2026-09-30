# Lexi: Proactive Agent System Architecture & Rules
**Context for AI Agent:** Read this document to understand the system state before suggesting code changes. Do NOT refer to legacy candidate-pool logic.

## 1. System Overview
*   **API & Scheduler (Node + Python):** Hosted on Render (single instance).
*   **Web Client (React):** Hosted on Vercel. Participant chat UI + Admin dashboard.
*   **Mobile (Android):** WebView shell + Firebase Cloud Messaging (FCM).
*   **Database:** MongoDB Atlas.

## 1.5 Global Topology & Onboarding Flow
*   **Hosting:** React client runs on Vercel. Node.js API and Python APScheduler run concurrently on a single Render Starter instance (`render-start.sh`).
*   **Participant Onboarding:** Users click a join link (`/join/:experimentId`). The Node API logs their IP in `apk_sessions` (deferred deep linking). They download a generic APK. On first open, `MainActivity.kt` matches the IP to the session, assigns them to the correct experiment, and registers their FCM token.
*   **Push Delivery:** Python Engine (`fcm_service.py`) sends payloads to Firebase. `LexiMessagingService.kt` intercepts them to wake the device and fire a high-intensity notification that deep-links directly into the specific conversation.

## 2. The Proactive Engine (Python)
The system uses a **Probability-Based Heuristic Selector**. Every cycle, `coordinated_send_and_inject()` reads experiment weights from MongoDB and randomly selects ONE heuristic. 
*   **Reactive (Control):** The fallback if no heuristics are active. No notification sent.
*   **LLM Integration:** All heuristics pass prompts to `llm_service.py`. No LLM calls happen directly inside heuristic classes.

## 2.5 Core Database Collections (MongoDB Atlas)
*   `users`: Participant data, FCM tokens, `isProactive` flags, and `proactiveMemory` (where heuristics store extracted context).
*   `experiments`: Configuration. Contains `proactiveSettings` (weights, schedules, models, daily caps).
*   `conversations` & `metadata_conversations`: Chat logs and metadata (`isFinished`). Note: `conversationsController` resets the proactive opener whenever a user sends a message.
*   `proactive_logs`: The source of truth for thesis analytics. Tracks every cycle attempt, heuristic chosen, fallback status, language, and delivery status.
*   `apk_sessions`: Temporary IP-matching store for Android onboarding.
*   `forms`: Pre/post experiment questionnaires.

### The 4 Heuristic Classes (Inherit from `BaseHeuristic`)
1.  **`AffectiveHeuristic`:** Extracts emotional content (`emotional_memories`). Generates empathetic check-ins.
2.  **`TemporalHeuristic`:** Extracts future plans (`future_mentions`). Reminds users of upcoming events.
3.  **`BehaviouralGapHeuristic`:** Extracts unfulfilled intentions (`open_intents`). Follows up gently. Tracks scanned conversations via `gap_scanned_conversation_ids` (set).
4.  **`GenericHeuristic`:** No memory extraction. Sends neutral chat invitations.

## 3. Strict Architectural Rules
*   **Prompt Safety:** The researcher only writes the persona/task prompt in the UI. The backend (`BaseHeuristic._safe_memory_prompt` and `_safe_message_prompt`) automatically appends JSON schemas and structural constraints.
*   **Uniform Fallback:** If a heuristic is selected but fails to find relevant memory, it MUST use `_cold_start_message()` to generate a fallback notification. It cannot return `None`.
*   **Language Cascade:** Target language is resolved dynamically: `proactiveMemory.preferred_language` → `user.language` → `experiment.defaultLanguage` → `"he"`.
*   **Data Logging:** `research_service.log_proactive_event()` must record `experiment_id`, `experiment_type`, `heuristic_selected`, `was_fallback`, `memory_content`, `language`, `heuristic_weights_snapshot`, and `llm_model` for thesis analytics.
*   **No User-Level Override:** The `proactiveGroup` field on the User document is deprecated for routing. Routing is strictly controlled by `ExperimentsModel.proactiveSettings.heuristicWeights`.
## 4. Comprehensive File, Class, & Method Dictionary

### 4.1 Python Proactive Engine (`logic-python/`)

**Core Services & Orchestration:**
*   `services/research_service.py`: 
    *   `coordinated_send_and_inject()`: Core loop. Reads weights, schedules, and language from DB, selects heuristic, and dispatches to FCM.
    *   `_load_experiment_settings()`: Fetches weights, prompts, schedule, `defaultLanguage`, and `maxDailyNotifications`.
    *   `_run_selected_heuristic()`: Executes the selected class, captures `used_fallback`, `memory_content`, and `language`.
    *   `get_proactive_users_with_rate_limit()`: Enforces `maxDailyNotifications` per experiment.
    *   `log_proactive_event()`: Writes analytics (funnel, heuristic chosen, fallback status, model used) to `proactive_logs`.
*   `services/llm_service.py`: 
    *   `_call_llm()`: The single dispatch point for all LLM calls.
    *   `override_model()`: Sets OpenAI or Anthropic model dynamically per experiment.
    *   `check_intent_completion()`: (Used by Behavioural Gap).
*   `services/fcm_service.py`: Dispatches payloads to Firebase.
*   `utils/mongodb_client.py`: Shared database connections.
*   `scheduler.py`: Runs on startup. Reads `allowedDays`, exact `fireTimes`, and `randomWindows` (with `count` and `jitter`) from MongoDB via APScheduler.
*   `run_cycle.py`: Manual, one-shot trigger for testing (bypasses cron).

**Heuristic Classes (`logic-python/heuristics/`):**
*   `base_heuristic.py` (`BaseHeuristic`):
    *   `__init__()`: Initializes `used_fallback`, `memory_content`, sets language cascade (`proactiveMemory` → `user.language` → `default_language` → `"he"`).
    *   `_safe_memory_prompt()`, `_safe_message_prompt()`: Injects `MEMORY_SCHEMA`, `STRUCTURAL_JSON_SUFFIX`, and `STRUCTURAL_MESSAGE_SUFFIX` to protect LLM formatting.
    *   `_cold_start_message()`: Handles uniform fallbacks if no memory is found.
    *   `_detect_language()`, `_ensure_language_detected()`: Auto-detects user language from character ratios.
    *   `_reload_user()`: Refreshes user doc mid-cycle.
*   `affective.py` (`AffectiveHeuristic`): Extracts `emotional_memories` (content, affective_score 1-10, timestamp_iso). Tracks scan state privately via `affective_last_analyzed_msg_count`.
*   `temporal.py` (`TemporalHeuristic`): Extracts `future_mentions` (text, when_iso). Implements `_COLD_START_PROMPT`.
*   `behavioural_gap.py` (`BehaviouralGapHeuristic`): Extracts `open_intents` (intent, stated_at, checked). Tracks scan state privately via `gap_scanned_conversation_ids` ($addToSet). Implements `_COLD_START_PROMPT`.
*   `generic.py` (`GenericHeuristic`): No memory extraction (just language detection). Outputs neutral invitations.

### 4.2 Node.js Backend (`Lexi/server/src/`)

**Users & Experiments:**
*   `models/ExperimentsModel.ts`: Defines `proactiveSettings` (`heuristicWeights`, `heuristicPrompts`, `schedule`, `defaultLanguage`, `maxDailyNotifications`).
*   `models/UsersModel.ts`: `proactiveGroup` (deprecated for routing, kept optional for backwards compatibility).
*   `types/experiments.type.ts`, `types/users.type.ts`
*   `services/experiments.service.ts`: `getActiveAgent()` logic.
*   `services/users.service.ts`: Handles user registration.


**Conversations & Sessions:**
*   `services/conversations.service.ts`: Assembles in-chat system prompts (stripped of "research/experiment" wording).
*   `controllers/conversationsController.controller.ts`: Handles `firstChatSentence` reset (clears opener on message / finish / 2h).
*   `models/ConversationsModel.ts`, `models/MetadataConversationsModel.ts`

**Data Aggregation & Questionnaires (Thesis Analytics):**
*   `models/FormsModel.ts`, `types/forms.type.ts`
*   `services/forms.service.ts`, `controllers/formsController.ts`, `routers/formsRouter.ts`
*   `services/dataAggregation.service.ts`, `controllers/dataAggregationController.controller.ts`, `routers/dataAggregationRouter.router.ts`
*   `controllers/joinController.ts`: Handles deferred deep linking and `/join/:experimentId` IP session matching.
*   `controllers/experimentsController.controller.ts`
`models/FormsModel.ts`, `services/forms.service.ts`, `routers/formsRouter.ts`: Backend logic for serving pre/post experiment questionnaires.
*   `models/MetadataConversationsModel.ts`: Links conversations to user IDs and tracks completion status.
*   `services/dataAggregation.service.ts`: Aggregates metrics for the researcher dashboard.

### 4.3 React Client (`Lexi/client/src/`)

**Admin Dashboard:**
*   `screens/Admin/components/experiments-panel/ProactiveSettingsModal.tsx`: UI for toggles, probabilities (must sum to 100), prompt editors, day/time scheduler, random windows, and `maxDailyNotifications`.
*   `screens/Admin/components/data-panel/DataPanel.tsx`: UI for data exports and metric analysis.
*   `screens/Admin/components/forms-panel/FormsPanel.tsx`, `create-form/CreateForm.tsx`
*   `models/AppModels.ts`: Includes `RandomWindow` interface (`{ start, end, count }`) and `proactiveSettings`.
*   `DAL/server-requests/experiments.ts`, `DAL/server-requests/dataAggregation.ts`, `DAL/server-requests/forms.ts`

**Participant Chat UI:**
*   `screens/Chat/ChatPage.tsx`, `components/side-bar-chat/SideBarChat.tsx`
*   `screens/Chat/components/UserAnnotation.tsx`
*   `components/forms/conversation-form/ConversationForm.tsx`, `components/questions/Question.tsx`
*   `screens/Admin/components/data-panel/DataPanel.tsx`: Admin UI for exporting metrics and proactive logs.
*   `screens/Admin/components/forms-panel/FormsPanel.tsx`: Admin UI for building questionnaires.
*   `screens/Chat/components/UserAnnotation.tsx` & `components/forms/conversation-form/ConversationForm.tsx`: UI for participants filling out forms.

### 4.4 Android Shell & Infra

**Android App (`android-app/`):**
*   `MainActivity.kt`: Handles deferred deep linking to exact conversations.
*   `LexiMessagingService.kt`: Intercepts FCM payloads, wakes device, triggers high-intensity push intents.

**Deployment Scripts (`scripts/`):**
*   `render-build.sh`: Compiles Node and Python environments.
*   `render-start.sh`: Launches Node API in foreground and APScheduler in background on the same instance.