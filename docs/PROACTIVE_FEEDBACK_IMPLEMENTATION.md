# Proactive Notification Feedback Implementation

## Overview
This document describes the minimal code changes made to implement Like/Dislike feedback for proactive notifications in the chat UI.

## Feature Behavior
- When a user opens a conversation after receiving a proactive notification, the first message (the proactive opener) displays thumbs up/down buttons
- Feedback buttons ONLY appear for the **last message** in the chat IF it's from the agent AND was triggered proactively
- Once the user clicks a rating, it highlights and is stored in the database
- The existing UserAnnotation component is reused with new conditional logic

## Changes Made

### 1. Database Schema
**File:** `Lexi/server/src/models/ConversationsModel.ts`

Added `isProactiveOpener` field to track messages that were created from proactive notifications:
```typescript
isProactiveOpener: { type: Boolean, default: false }
```

### 2. TypeScript Type Definitions

**File:** `Lexi/server/src/types/conversations.type.ts`

Added `isProactiveOpener?` field to both `IConversation` and `Message` interfaces.

**File:** `Lexi/server/src/types/users.type.ts`

Added `proactiveMemory` field to `IUser` interface to enable type-safe access:
```typescript
proactiveMemory?: {
    injected_prompt_original?: string;
    injected_prompt_reset_after?: Date;
    [key: string]: any;
};
```

**File:** `Lexi/client/src/models/AppModels.ts`

Added `isProactiveOpener?` field to `MessageType` interface.

### 3. Backend Service Logic

**File:** `Lexi/server/src/services/conversations.service.ts`

**Changes:**
1. **createConversation method** - Detects when a proactive opener is active:
   ```typescript
   const hasProactiveOpener = !user.isAdmin && user.proactiveMemory?.injected_prompt_original;
   ```
   
2. **createMessageDoc method** - Now accepts `isProactiveOpener` parameter and stores it:
   ```typescript
   private createMessageDoc = async (
       message: Message,
       conversationId: string,
       messageNumber: number,
       isProactiveOpener: boolean = false,
   )
   ```

3. **getConversation method** - Returns `isProactiveOpener` field to frontend:
   ```typescript
   const returnValues = isLean
       ? { _id: 0, role: 1, content: 1 }
       : { _id: 1, role: 1, content: 1, userAnnotation: 1, isProactiveOpener: 1 };
   ```

### 4. Frontend UI Changes

**File:** `Lexi/client/src/screens/Chat/components/MessageList.tsx`

Tracks which message is the last one and passes this information to child Message components:
```typescript
const lastMessageIndex = messages.length - 1;
// ...
<Message
    // ... other props
    isLastMessage={index === lastMessageIndex}
/>
```

**File:** `Lexi/client/src/screens/Chat/components/Message.tsx`

Updated the condition for showing UserAnnotation:
```typescript
{!isUser && experimentHasUserAnnotation && message._id && isLastMessage && message.isProactiveOpener && (
    <UserAnnotation
        key={message._id}
        message={message}
        handleUpdateUserAnnotation={handleUpdateUserAnnotation}
    />
)}
```

**Logic:** Show feedback buttons ONLY when:
- Message is from agent (!isUser)
- Experiment has userAnnotation feature enabled
- Message has an ID (saved to DB)
- It's the last message in the conversation
- It was created from a proactive notification

## How It Works

### Flow:
1. **Proactive System** (Python) modifies `user.agent.firstChatSentence` and stores the original in `user.proactiveMemory.injected_prompt_original`

2. **User Opens App** and creates a new conversation

3. **Backend** (`createConversation`):
   - Checks if `user.proactiveMemory.injected_prompt_original` exists
   - If yes, marks the first message with `isProactiveOpener: true`

4. **Frontend** (Chat UI):
   - Renders all messages
   - Shows thumbs up/down buttons ONLY for the last message IF it's proactive

5. **User Clicks Feedback**:
   - Existing `updateUserAnnotation` endpoint is called
   - Stores 1 (like) or -1 (dislike) in `message.userAnnotation`
   - UI updates to show selected state

## Database Fields

### conversations collection
```javascript
{
  _id: ObjectId,
  conversationId: String,
  content: String,
  role: String,
  messageNumber: Number,
  userAnnotation: Number,        // -1 (dislike), 0 (neutral), 1 (like)
  isProactiveOpener: Boolean,    // NEW FIELD - true if created from proactive notification
  createdAt: Date,
  timestamp: Number
}
```

## Testing Checklist

### 1. Backend Testing
- [ ] Verify new conversations created after proactive notifications have `isProactiveOpener: true` on first message
- [ ] Verify regular conversations have `isProactiveOpener: false` on first message
- [ ] Verify `getConversation` returns the `isProactiveOpener` field

### 2. Frontend Testing
- [ ] Open chat after receiving a proactive notification
- [ ] Verify thumbs up/down buttons appear below the agent's first message
- [ ] Click thumbs up - verify icon highlights and API call succeeds
- [ ] Refresh page - verify selection persists
- [ ] Click thumbs down - verify it changes from thumbs up
- [ ] Send a new message - verify buttons remain (still last agent message)
- [ ] Agent replies - verify buttons disappear (no longer last message)

### 3. Edge Cases
- [ ] Regular (non-proactive) conversations should NOT show feedback buttons
- [ ] Admin users testing conversations should NOT show feedback buttons
- [ ] Experiments with `userAnnotation` feature disabled should NOT show feedback buttons
- [ ] Only the LAST agent message in a proactive conversation shows buttons

## API Endpoints Used

### Existing (No Changes Required)
- `PUT /conversations/annotation` - Updates `userAnnotation` field
  - Body: `{ messageId: string, userAnnotation: number }`
  - Returns: 200 OK

## Migration Notes

**No database migration required.**

The `isProactiveOpener` field has a default value of `false`, so:
- Existing messages will not break
- New messages will be properly flagged
- Old conversations will simply not show feedback (correct behavior)

## Rollback Plan

If issues arise, you can easily rollback by:

1. **Frontend only** - Comment out the `&& message.isProactiveOpener` condition in Message.tsx to show feedback on all agent messages (reverts to old behavior if that was desired)

2. **Full rollback** - Remove the field from schema and types, remove the conditional logic

## Future Enhancements (Optional)

If you want to link feedback to `proactive_logs` collection:

1. Add `proactive_log_id` field to conversations when creating proactive messages
2. Update `updateUserAnnotation` to also update the corresponding `proactive_logs` document
3. This enables analytics like "Which heuristics get the best ratings?"

## Notes

- **Zero refactoring** - Only added new fields and minimal conditional logic
- **Preserves existing behavior** - UserAnnotation component unchanged, just conditional rendering
- **Type-safe** - All TypeScript types updated appropriately
- **Low risk** - New field has safe defaults, existing data unaffected
