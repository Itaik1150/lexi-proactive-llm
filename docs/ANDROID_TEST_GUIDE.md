# Android test guide — step by step

How to test the changes to the participant app: the "Open Lexi" join flow (review item V9) and the hardening (S3, S6).
Nothing here was compiled or run by the person who wrote the code, so **you are the first to build it**. Take notes as you go (a table at the end shows what to send back).

Allow about 1½ hours the first time. You do not need to know Android; every step says where to click or what to type.

## Before you start

You need:

| What | Notes |
|---|---|
| Android Studio | already installed |
| A way to run the app | **either** your phone + USB cable **or** the emulator `Medium_Phone` that already exists on this computer |
| A test participant | an account (username and password) you can log in with inside an experiment. Use your own test account, **not a real participant** |
| The experiment's join link | in the admin dashboard open the experiment → **Proactive settings** (bell icon) → the link next to the copy icon, like `https://lexi-server-1rx9.onrender.com/join/64b7…`. The last part (24 letters and digits) is the **experiment id**; write it down as `EXP_ID` |

**The new server code must be deployed before Part C and D1.** The confirmation screen asks the server for `/experiments/<EXP_ID>/public`, which only exists after the latest server commit is pushed and Render has redeployed. Check it in a browser:
`https://lexi-server-1rx9.onrender.com/experiments/EXP_ID/public` should show `{"title":"…","isActive":true}`. If it says "Cannot GET", the server is not updated yet — tell Claude to push (Parts A and B work without it).

Tools used in the terminal commands (PowerShell). Replace `EXP_ID` with your experiment id:

```powershell
$adb = "C:\Users\itaik\AppData\Local\Android\Sdk\platform-tools\adb.exe"
& $adb devices          # lists connected phones/emulators; yours must say "device"
```

---

## Part A — Unit tests (10 minutes, no phone needed)

1. Start Android Studio. **File → Open** → choose the folder `C:\Users\itaik\code\master-thesis\android-app` (the `android-app` folder itself, not the repository root). If it asks "Trust project", click **Trust Project**.
2. Wait until the bar at the bottom stops showing "Gradle sync…" / "Indexing…" (first time: several minutes, needs internet). If a pop-up suggests updating Gradle or the Android plugin, click **Don't remind me again** / close it — do **not** update.
   - If sync fails with "Unsupported Java version": **File → Settings → Build, Execution, Deployment → Build Tools → Gradle → Gradle JDK** → pick any entry that says 17, 21 (for example `jbr-21`) → **OK** → click the elephant icon "Sync Project with Gradle Files".
3. In the left panel, change the dropdown at the top (it says **Android**) to **Project**. Expand `app → src → test → java → com.example.lexiparticipant`.
4. Right-click the folder `lexiparticipant` → **Run 'Tests in 'lexiparticipant''**.
5. The **Run** panel at the bottom shows the result. **Expected: 17 tests, all green** (JoinLinkTest 9, UrlPolicyTest 7, ExampleUnitTest 1).
6. If something is red or the project does not compile: click the red item, copy the text from the panel (or take a screenshot) and send it to Claude. Do not try to fix it yourself.

## Part B — Build and install the app (15 minutes)

**Option 1 — your phone**
1. On the phone: **Settings → About phone** → tap **Build number** 7 times ("You are now a developer"). Go back → **System → Developer options** → turn on **USB debugging**.
2. Connect the USB cable. On the phone choose **File transfer** (if asked) and tap **Allow** on "Allow USB debugging?" (tick "Always allow").
3. In Android Studio's top toolbar the device box should show your phone's name.

**Option 2 — emulator**
1. **Tools → Device Manager** → click the ▶ next to `Medium_Phone` and wait until the phone screen appears and settles.
2. The emulator can receive notifications only if it has Google Play services (look for a Play Store icon). If not, use your real phone for Part D.

**Then, for either option**
3. **Build → Select Build Variant…** → make sure `app` says **debug**.
4. Click the green ▶ **Run** button (top toolbar). The first build takes a few minutes. The app installs and opens.
5. If Android asks to allow notifications, tap **Allow**.
6. If you get "INSTALL_FAILED_UPDATE_INCOMPATIBLE": the phone has an older Lexi signed with a different key. Uninstall it (long-press the Lexi icon → App info → Uninstall) and run again. (This loses that phone's saved study.)

## Part C — Joining a study (V9)

Make sure the app is installed, then use PowerShell.

**C1 — The "Open Lexi" link**
```powershell
& $adb shell am start -a android.intent.action.VIEW -d "lexi://join/EXP_ID"
```
Expected: Lexi opens and shows **"You are joining: *your study's title*"** with **Continue** and **This is not my study**. Tap **Continue** → the study's login/chat page loads.

**C2 — A link that does not exist**
```powershell
& $adb shell am start -a android.intent.action.VIEW -d "lexi://join/000000000000000000000000"
```
Expected: "This invitation is not valid, or the study is closed." and a button **Enter my link manually**.

**C3 — The same study again**
Run the command from C1 once more. Expected: the chat opens **directly**, with no question.

**C4 — The button on the join page** (this is what participants really use)
1. On the phone open **Chrome** and go to your join link (`https://lexi-server-1rx9.onrender.com/join/EXP_ID`). You should see the invitation page with **Download & Join**, three numbered steps, and a white **Open Lexi** button.
2. Do **not** download anything (the app is already installed). Tap **Open Lexi**.
3. Chrome may ask "Open in Lexi?" → tap **Open**. Expected: same as C1.
4. If the button does nothing, tap the small **Tap here** link under it instead, and note that the button failed.

**C5 — The manual fallback**
1. Uninstall Lexi from the phone, then **Run** again from Android Studio (fresh install, no saved study).
2. Open Lexi from the launcher. You will see "looking for your study" (this can take up to a minute while the server wakes up), then either the confirmation screen (it guessed from your network) or a screen asking you to paste a link.
3. If you see the paste screen: paste `https://lexi-server-1rx9.onrender.com/join/EXP_ID` and tap **Continue**. Expected: the study opens.
4. Try pasting nonsense (`hello`) → expected: an error message, not a crash.

## Part D — Hardening (S3, S6)

### D1 — Tapping a notification (the most important test)
You need the test participant **logged in on this phone** (log in inside the app once; that registers the phone for notifications), and at least one conversation for that participant.

Send yourself a notification from the computer (use the participant's username):
```powershell
cd C:\Users\itaik\code\master-thesis\logic-python
.venv\Scripts\python.exe tools\send_test_push.py --username YOUR_TEST_USERNAME            # shows what it would send
.venv\Scripts\python.exe tools\send_test_push.py --username YOUR_TEST_USERNAME --send     # really sends it
```
(It only reads the database and sends one push. If it says it cannot connect, update `MONGODB_URL` in `logic-python\.env` with the **new** Atlas password.)

Do the test three times, once for each state of the app:

| State | How to get it | What to do | Expected |
|---|---|---|---|
| **Open** | the app is on screen | send the push | a heads-up notification appears; tap it → the conversation opens |
| **Background** | press the Home button (app still in recent apps) | send the push, pull down the notification bar | tap it → **the conversation opens** (not the study home) |
| **Closed** | open recent apps and swipe Lexi away | send the push | tap it → **the conversation opens** |

After each tap, note whether the **feedback/annotation control** appears in the conversation (it should appear after a notification tap).

**Lock screen text.** Send a push while the app is **open**, then lock the phone straight away and look at the lock screen. With `HIDE_TEXT_ON_LOCK_SCREEN = true` it should say only "You have a new message". Be aware: when the app is in the background or closed, **Android itself draws the notification and shows the full text on the lock screen**; the hiding only applies to notifications the app draws itself. Making it apply every time needs a change in how the engine sends pushes (see "What is not covered" below).

### D2 — A link in a message opens outside the app
In the chat send yourself a message containing `https://example.com`. If the link is tappable, tap it. Expected: **Chrome** opens example.com; Lexi itself never shows it. If the chat does not make links tappable, write "not tappable" and skip.

### D3 — Bad notification data is ignored
```powershell
& $adb shell am start -n com.example.lexiparticipant/.MainActivity --es deepLinkUrl "https://example.com"
& $adb shell am start -n com.example.lexiparticipant/.MainActivity --es experimentId "../x" --es conversationId "abc"
```
Expected for both: Lexi opens normally (your study), and **never** shows example.com or an error page.

### D4 — Updating an app that already has a saved study
Only if the phone already had Lexi with a study before you started Part B: that is covered by Part B step 4 (the new build installs over the old one). Expected: Lexi opens your **same** study without asking. (If you had to uninstall in B6, write "not testable".)

### D5 — Backups are off (optional)
```powershell
& $adb shell dumpsys package com.example.lexiparticipant | Select-String "flags="
```
Expected: the line does **not** contain `ALLOW_BACKUP`.

---

## What to send back

Copy this list and fill it in with ✔ or ✘ (and a screenshot or the red text for any ✘):

```
A  unit tests (17 green):
B  app installs and opens:
C1 Open Lexi link -> confirmation -> Continue:
C2 invalid link message:
C3 same study opens directly:
C4 Open Lexi button on the join page:
C5 manual paste fallback (+ nonsense gives an error):
D1 notification tap opens the conversation:  open / background / closed
D1 feedback control appears after the tap:
D1 lock-screen text (app open):
D2 outside link opens Chrome (or "not tappable"):
D3 bad data ignored:
D4 update keeps the study (or "not testable"):
Anything odd:
```

## If something goes wrong

| Problem | What to try |
|---|---|
| `adb` is "not recognized" | use the `$adb` full path shown above (set it again in each new PowerShell window) |
| `adb devices` shows nothing or "unauthorized" | reconnect the cable; on the phone tap **Allow USB debugging**; try another cable/port |
| Android Studio does not list your phone | switch the USB mode to **File transfer**; make sure USB debugging is on |
| "Looking for your study…" never ends | the server may be waking up (up to ~90 s). Wait, then use the manual paste screen |
| Confirmation says "Could not reach the server" | check the phone's internet, tap **Try again** |
| **Open Lexi** does nothing | the new app must be installed; try the **Tap here** link; try Chrome rather than another browser |
| No notification appears | allow notifications for Lexi (Settings → Apps → Lexi → Notifications), turn off Do Not Disturb, check the participant is logged in on this phone |
| Anything that crashes | in Android Studio open the **Logcat** tab at the bottom, type `Lexi` in the filter box, reproduce the problem and copy the lines |

## What is not covered by these tests

- **Pushes shown by Android itself.** The engine sends each push as a "notification message". When the app is not open, Android draws it and the app's own notification code (lock-screen hiding, the full-screen wake-up) does **not** run. The conversation link now works in that state (the app reads the ids Android passes along), but the lock-screen hiding does not. The fix is to send the push as a data-only message from the engine; it changes delivery behaviour, so decide with Claude after D1.
- A **signed release** APK and minification (see `OPERATIONS.md`, section 6).
- Token refresh while the app is closed, and logging out clearing the token (review item R7).
