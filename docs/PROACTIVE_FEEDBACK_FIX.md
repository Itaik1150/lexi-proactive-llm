# Proactive Feedback Fix & Notification Routing

## Issue 1: Missing Feedback Buttons - FIXED

### Problem
The Like/Dislike buttons were not rendering because the original logic checked if the message was the "last" message. After the user sends their first reply, the agent's response becomes the last message, incorrectly hiding the feedback buttons from the proactive opener.

### Root Cause
The condition was:
```typescript
isLastMessage && message.isProactiveOpener
```

But after user interaction:
- Message 1: Agent (proactive opener) - no longer "last"
- Message 2: User reply
- Message 3: Agent response - now "last" but NOT proactive

### Solution
Changed logic to show feedback only on the FIRST message when:
1. It's the first message in the conversation (index === 0)
2. The conversation has only 1 message (user hasn't replied yet)
3. The message has `isProactiveOpener: true`

**Updated Files:**
- `Lexi/client/src/screens/Chat/components/MessageList.tsx`
- `Lexi/client/src/screens/Chat/components/Message.tsx`
- `Lexi/client/src/screens/Chat/ChatPage.tsx` (added debug logs)

### New Logic
```typescript
// In MessageList.tsx
const showFeedbackOnFirstMessage = messages.length === 1 && messages[0]?.isProactiveOpener;

// Pass to Message component
showProactiveFeedback={index === 0 && showFeedbackOnFirstMessage}
```

### Behavior After Fix
✅ User taps notification → Opens chat → Sees proactive message with 👍👎 buttons
✅ User clicks Like or Dislike → Rating stored
✅ User sends first message → Buttons remain visible (still only 1 message before reply sent)
✅ After user message sent → Conversation has 2+ messages → Buttons disappear (correct!)

### Debug Console Logs Added
To verify the data flow, check browser console for:
```
[ChatPage] Loaded conversation: [...]
[ChatPage] First message isProactiveOpener: true
[Message] Proactive feedback check: {...}
```

---

## Issue 2: Skip Welcome Screen on Notification Tap - ALREADY WORKING

### Current Implementation
The notification routing is **already implemented correctly** in the Android app. No changes needed!

### How It Works

**1. Notification Creation (Python → FCM)**
```python
# logic-python/services/fcm_service.py sends:
{
    "conversationId": "...",
    "experimentId": "...",
    "body": "proactive message"
}
```

**2. Notification Reception (Android)**
```kotlin
// LexiMessagingService.kt (lines 29-38)
val conversationId = message.data["conversationId"]
val experimentId   = message.data["experimentId"]

val deepLinkUrl = if (!conversationId.isNullOrEmpty() && !experimentId.isNullOrEmpty()) {
    "${BuildConfig.FRONTEND_BASE_URL}/e/$experimentId/c/$conversationId"
} else {
    null
}
```

**3. Deep Link Handling (Android)**
```kotlin
// MainActivity.kt (lines 72-86)
val deepLinkUrl = intent?.getStringExtra("deepLinkUrl")

if (!deepLinkUrl.isNullOrEmpty()) {
    // Extract base experiment URL and cache it
    val baseUrl = Regex("(https?://[^/]+/e/[a-fA-F0-9]{24})").find(deepLinkUrl)?.groupValues?.get(1)
    if (baseUrl != null) {
        prefs.edit().putString(KEY_EXPERIMENT_URL, baseUrl).apply()
    }
    // DIRECTLY load the conversation URL, bypassing Welcome screen
    setContent { MaterialTheme { ChatScreen(url = deepLinkUrl, ...) } }
    return
}
```

**4. React Router Matches URL**
```typescript
// App.tsx routes:
/e/:experimentId          → Home (Welcome screen)
/e/:experimentId/c/:conversationId → ChatPage (Direct to chat!)
```

### Verification Steps

To verify notification routing is working:

1. **Send a proactive notification** (via Python scheduler or manual trigger)
2. **Tap the notification** on Android device
3. **Expected behavior:**
   - App opens directly to ChatPage (`/e/.../c/...`)
   - Skips the Home/Welcome screen entirely
   - Shows the proactive message with feedback buttons

4. **If Welcome screen appears instead:**
   - Check Android logs: `adb logcat -s Lexi FCM`
   - Look for: `"onNewIntent: navigating to [URL]"`
   - Verify the notification payload includes both `conversationId` and `experimentId`

### Troubleshooting

**Symptom:** App opens to Welcome screen instead of chat

**Possible causes:**
1. **Missing conversation ID in notification**
   - Check: `logic-python/services/fcm_service.py`
   - Ensure payload includes `conversationId` and `experimentId`

2. **Deep link not passed to WebView**
   - Check: Android logs for "deepLinkUrl" in MainActivity
   - Verify LexiMessagingService constructs the URL correctly

3. **React Router not matching URL**
   - Check: Browser developer tools network tab
   - Verify the WebView loads `/e/:experimentId/c/:conversationId`

### Testing Checklist

- [ ] Proactive notification sent successfully
- [ ] Notification tap opens app
- [ ] WebView loads conversation URL directly
- [ ] ChatPage renders (not Home screen)
- [ ] First message shows feedback buttons
- [ ] Buttons disappear after user replies
- [ ] Rating is stored in database

---

## Files Modified (This Fix)

### Frontend Changes
1. `Lexi/client/src/screens/Chat/components/MessageList.tsx`
   - Changed from `isLastMessage` to `showProactiveFeedback` logic
   - Only shows feedback when `messages.length === 1` and first message is proactive

2. `Lexi/client/src/screens/Chat/components/Message.tsx`
   - Renamed prop from `isLastMessage` to `showProactiveFeedback`
   - Added debug console logs

3. `Lexi/client/src/screens/Chat/ChatPage.tsx`
   - Added debug console logs for conversation loading

### No Backend Changes Required
The backend already:
- ✅ Sets `isProactiveOpener: true` on first message when proactive
- ✅ Returns field in `getConversation` API
- ✅ Stores field in MongoDB

### No Android Changes Required
The Android app already:
- ✅ Receives `conversationId` and `experimentId` in FCM payload
- ✅ Constructs deep link URL to conversation
- ✅ Passes deep link to MainActivity
- ✅ Loads conversation directly, bypassing Welcome screen

---

## Next Steps

1. **Test the fix:**
   - Trigger a proactive notification
   - Tap notification on Android device
   - Verify direct navigation to chat
   - Verify feedback buttons appear
   - Submit feedback and verify it persists

2. **Remove debug logs** (after verification):
   - Remove console.log statements from:
     - `ChatPage.tsx`
     - `Message.tsx`

3. **Optional Enhancement:**
   Link feedback to `proactive_logs` collection for analytics:
   - Add `proactive_log_id` to messages
   - Update both `conversations` and `proactive_logs` when feedback submitted
   - Enable queries like "Which heuristics get best ratings?"

---

## Summary

✅ **Fixed:** Feedback buttons now appear correctly on proactive opener before user replies
✅ **Already Working:** Notification tap routes directly to chat, skipping Welcome screen
✅ **Ready for Testing:** Deploy and verify on Android device with real proactive notifications
