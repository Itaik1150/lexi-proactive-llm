import mongoose from 'mongoose';

/**
 * Funnel stamps on `proactive_logs` rows (written by the Python engine, one per notification attempt).
 * For a row with status "sent" and a conversation_id:
 *   opened_at       first time the participant's app fetched that conversation
 *   first_reply_at  first message the participant wrote in it
 * Each stamp is set once (the first time wins). These calls are best-effort: they never throw,
 * so a logging problem can never break the chat.
 */
type LogsCollection = { updateOne: (filter: object, update: object) => Promise<unknown> };

const OBJECT_ID_PATTERN = /^[a-f0-9]{24}$/i;

export const createProactiveLogsService = (
    getCollection: () => LogsCollection = () => mongoose.connection.db.collection('proactive_logs'),
) => {
    const stamp = async (conversationId: unknown, field: 'opened_at' | 'first_reply_at'): Promise<void> => {
        if (typeof conversationId !== 'string' || !OBJECT_ID_PATTERN.test(conversationId)) return;
        try {
            await getCollection().updateOne(
                { conversation_id: conversationId, status: 'sent', [field]: { $exists: false } },
                { $set: { [field]: new Date() } },
            );
        } catch (error) {
            console.warn(`[proactive_logs] could not set ${field}:`, error);
        }
    };

    return {
        markOpened: (conversationId: unknown) => stamp(conversationId, 'opened_at'),
        // Replying implies the conversation was opened, even if that fetch was missed.
        markReplied: async (conversationId: unknown) => {
            await stamp(conversationId, 'opened_at');
            await stamp(conversationId, 'first_reply_at');
        },
    };
};

export const proactiveLogsService = createProactiveLogsService();
