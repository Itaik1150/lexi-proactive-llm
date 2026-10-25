/**
 * R5 (docs/REVIEW.md): one atomic, safe way to restore the greeting after a proactive opener.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { RESTORE_PIPELINE, createGreetingReset } from '../services/greetingReset';

const USER = '64b7f0f0f0f0f0f0f0f0f0f1';
const CONV = '64b7f0f0f0f0f0f0f0f0f0f2';

const fakeDb = (opts: { modifiedCount?: number; metaUserId?: string | null; throwOn?: string } = {}) => {
    const calls: { collection: string; op: string; filter: any; update?: any }[] = [];
    const db = {
        collection: (name: string) => ({
            updateOne: async (filter: object, update: object | object[]) => {
                if (opts.throwOn === name) throw new Error('db down');
                calls.push({ collection: name, op: 'updateOne', filter, update });
                return { modifiedCount: opts.modifiedCount ?? 1 };
            },
            findOne: async (filter: object) => {
                if (opts.throwOn === name) throw new Error('db down');
                calls.push({ collection: name, op: 'findOne', filter });
                return opts.metaUserId === null ? null : { userId: opts.metaUserId ?? USER };
            },
        }),
    };
    return { db, calls };
};

test('the pipeline copies the saved original back and removes the saved fields, in one update', () => {
    assert.deepEqual(RESTORE_PIPELINE[0], { $set: { 'agent.firstChatSentence': '$proactiveMemory.injected_prompt_original' } });
    const unset = (RESTORE_PIPELINE[1] as any).$unset as string[];
    assert.ok(unset.includes('proactiveMemory.injected_prompt_original'));
    assert.ok(unset.includes('proactiveMemory.injected_prompt_reset_after'), 'legacy field is cleaned in the same step');
    assert.equal(RESTORE_PIPELINE.length, 2);
});

test('it only runs when a non-empty saved original exists, so the greeting can never be blanked', async () => {
    const { db, calls } = fakeDb();
    const restored = await createGreetingReset(() => db as any).restoreGreeting(USER);
    assert.equal(restored, true);
    const main = calls[0];
    assert.equal(main.collection, 'users');
    assert.deepEqual(main.filter['proactiveMemory.injected_prompt_original'], { $type: 'string', $ne: '' });
    assert.equal(main.update, RESTORE_PIPELINE, 'a single pipeline update, no read-then-write');
});

test('nothing to restore reports false, and leftover legacy expiry fields are removed without touching the greeting', async () => {
    const { db, calls } = fakeDb({ modifiedCount: 0 });
    const restored = await createGreetingReset(() => db as any).restoreGreeting(USER);
    assert.equal(restored, false);
    const cleanup = calls[1];
    assert.deepEqual(cleanup.filter['proactiveMemory.injected_prompt_original'], { $exists: false });
    assert.deepEqual(cleanup.filter['proactiveMemory.injected_prompt_reset_after'], { $exists: true });
    assert.deepEqual(cleanup.update, { $unset: { 'proactiveMemory.injected_prompt_reset_after': '' } });
    assert.ok(!JSON.stringify(cleanup.update).includes('firstChatSentence'), 'cleanup never writes the greeting');
});

test('invalid user ids never reach the database', async () => {
    const { db, calls } = fakeDb();
    const svc = createGreetingReset(() => db as any);
    for (const bad of [undefined, null, '', 'abc', { $ne: '' }, 42, '<script>']) {
        assert.equal(await svc.restoreGreeting(bad), false);
        assert.equal(await svc.restoreGreetingForConversation(bad), false);
    }
    assert.equal(calls.length, 0);
});

test('a database failure is swallowed and reported as not restored', async () => {
    const svc = createGreetingReset(() => fakeDb({ throwOn: 'users' }).db as any);
    assert.equal(await svc.restoreGreeting(USER), false);
    const svc2 = createGreetingReset(() => fakeDb({ throwOn: 'metadata_conversations' }).db as any);
    assert.equal(await svc2.restoreGreetingForConversation(CONV), false);
});

test('finishing a conversation restores the greeting of the participant who owns it', async () => {
    const { db, calls } = fakeDb();
    const restored = await createGreetingReset(() => db as any).restoreGreetingForConversation(CONV);
    assert.equal(restored, true);
    assert.equal(calls[0].collection, 'metadata_conversations');
    assert.equal(calls[0].op, 'findOne');
    const userUpdate = calls.find((c) => c.collection === 'users' && c.op === 'updateOne')!;
    assert.equal(String(userUpdate.filter._id), USER);
});

test('a conversation without an owner restores nothing', async () => {
    const { db, calls } = fakeDb({ metaUserId: null });
    assert.equal(await createGreetingReset(() => db as any).restoreGreetingForConversation(CONV), false);
    assert.ok(!calls.some((c) => c.collection === 'users'));
});
