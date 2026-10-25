import mongoose from 'mongoose';

/**
 * Restores a participant's normal greeting after a proactive opener has been used.
 *
 * The engine (logic-python) injects a proactive message by overwriting `agent.firstChatSentence`
 * and saving the previous greeting in `proactiveMemory.injected_prompt_original`. This is the ONE
 * place that undoes that, whatever triggered it (the participant replied, or finished a conversation).
 *
 * It is a single atomic update: the greeting is copied back and the saved original removed in one
 * operation on the database, so a concurrent injection can never be half-overwritten (the old
 * read-then-write version could replace a freshly injected opener with a stale greeting).
 * It only ever writes `firstChatSentence` from a saved, non-empty original, so it can never blank it.
 */
type Collection = {
    updateOne: (filter: object, update: object | object[]) => Promise<{ modifiedCount?: number }>;
    findOne: (filter: object, options?: object) => Promise<any>;
};
type Db = { collection: (name: string) => Collection };

const ORIGINAL = 'proactiveMemory.injected_prompt_original';
// Written by earlier versions of the engine (a 2-hour expiry that no longer exists). Cleaned up here.
const LEGACY_RESET_AFTER = 'proactiveMemory.injected_prompt_reset_after';

const OBJECT_ID_PATTERN = /^[a-f0-9]{24}$/i;

/** Update pipeline: copy the saved original back as the greeting, then drop the saved fields. */
export const RESTORE_PIPELINE = [
    { $set: { 'agent.firstChatSentence': `$${ORIGINAL}` } },
    { $unset: [ORIGINAL, LEGACY_RESET_AFTER] },
];

export const createGreetingReset = (getDb: () => Db = () => mongoose.connection.db as unknown as Db) => {
    /** Returns true if a greeting was restored. Never throws. */
    const restoreGreeting = async (userId: unknown): Promise<boolean> => {
        const id = String(userId ?? '');
        if (!OBJECT_ID_PATTERN.test(id)) return false;
        try {
            const users = getDb().collection('users');
            const _id = new mongoose.Types.ObjectId(id);

            const result = await users.updateOne({ _id, [ORIGINAL]: { $type: 'string', $ne: '' } }, RESTORE_PIPELINE);

            // Leftover from the old expiry scheme with nothing to restore: just remove it, never touch the greeting.
            await users.updateOne(
                { _id, [LEGACY_RESET_AFTER]: { $exists: true }, [ORIGINAL]: { $exists: false } },
                { $unset: { [LEGACY_RESET_AFTER]: '' } },
            );

            const restored = (result.modifiedCount ?? 0) > 0;
            if (restored) console.log(`[proactive] greeting restored for user ${id}`);
            return restored;
        } catch (error) {
            console.warn(`[proactive] could not restore greeting for user ${id}:`, error);
            return false;
        }
    };

    /** Same, for the participant who owns a conversation. */
    const restoreGreetingForConversation = async (conversationId: unknown): Promise<boolean> => {
        const id = String(conversationId ?? '');
        if (!OBJECT_ID_PATTERN.test(id)) return false;
        try {
            const meta = await getDb()
                .collection('metadata_conversations')
                .findOne({ _id: new mongoose.Types.ObjectId(id) }, { projection: { userId: 1 } });
            return meta?.userId ? await restoreGreeting(String(meta.userId)) : false;
        } catch (error) {
            console.warn(`[proactive] could not look up the owner of conversation ${id}:`, error);
            return false;
        }
    };

    return { restoreGreeting, restoreGreetingForConversation };
};

export const greetingReset = createGreetingReset();
