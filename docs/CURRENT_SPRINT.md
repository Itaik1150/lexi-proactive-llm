# Lexi — Current Sprint & Launch Plan

## Phase 1: Core Engine Bugs & Features (Current Focus)
- [x] **1.1 Fix Memory Management Logic:** Refine prompts and the memory extraction logic. 
  * *Bugs to fix:* Prevent duplicate memory creation, fix the issue where it misses memories after several runs, and fix the bug where multiple memories from a single conversation are all marked as `used` even if the heuristic only consumes one.

- [x] **1.3 Add AI-Driven Scheduling:** Add a "Let the agent decide" toggle inside the Admin Dashboard schedule settings so the agent can autonomously choose notification times.
- [ ] **1.4 Security & Limits Verification:** Ensure `maxDailyNotifications` works correctly and verify Firebase Service Account JSON is securely loaded via Render Secrets (absent from git history).

## Phase 2: Thesis Data Logging & Questionnaires
- [ ] **2.1 Implement Relevant Metrics Collection:** Ensure all specific metrics relevant to the thesis research are actively tracked, collected, and sent to the database.
- [ ] **2.2 Funnel Analytics & Export:** Ensure `proactive_logs` accurately track the funnel (Sent → Opened → Replied) and export correctly from the Admin Data Panel.
- [ ] **2.3 Pre/Post Questionnaires:** Verify the app serves the assigned forms (FormsModel/FormsRouter) to users at correct intervals.

## Phase 3: UI/UX & Polish
- [x] **3.1 Adjust Mobile Chat UI:** Reduce the chat text/UI size on mobile devices, or implement a settings toggle allowing the user to adjust the size themselves.
- [ ] **1.2 Update Opening Prompt:** Change and refine the initial opening prompt for the agent.
