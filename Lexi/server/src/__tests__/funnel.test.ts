/**
 * V2 (docs/REVIEW.md): opened_at / first_reply_at stamps on proactive_logs rows.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createProactiveLogsService } from '../services/proactiveLogs.service';

const CONV = '64b7f0f0f0f0f0f0f0f0f0f0';

const fakeCollection = () => {
    const calls: { filter: any; update: any }[] = [];
    return { calls, updateOne: async (filter: object, update: object) => void calls.push({ filter, update }) };
};

test('markOpened sets opened_at once, only on the sent row of that conversation', async () => {
    const col = fakeCollection();
    await createProactiveLogsService(() => col)!.markOpened(CONV);
    assert.equal(col.calls.length, 1);
    const { filter, update } = col.calls[0];
    assert.equal(filter.conversation_id, CONV);
    assert.equal(filter.status, 'sent');
    assert.deepEqual(filter.opened_at, { $exists: false }, 'first stamp wins');
    assert.ok(update.$set.opened_at instanceof Date);
});

test('markReplied sets opened_at (if it was missed) and first_reply_at', async () => {
    const col = fakeCollection();
    await createProactiveLogsService(() => col).markReplied(CONV);
    const fields = col.calls.map((c) => Object.keys(c.update.$set)[0]);
    assert.deepEqual(fields, ['opened_at', 'first_reply_at']);
    for (const c of col.calls) assert.equal(c.filter.conversation_id, CONV);
});

test('ids that are not ObjectIds never reach the database', async () => {
    const col = fakeCollection();
    const svc = createProactiveLogsService(() => col);
    for (const bad of [undefined, null, '', 'abc', { $ne: '' }, 123, '<script>']) {
        await svc.markOpened(bad);
        await svc.markReplied(bad);
    }
    assert.equal(col.calls.length, 0);
});

test('a database failure is swallowed and never breaks the chat', async () => {
    const svc = createProactiveLogsService(() => ({
        updateOne: async () => {
            throw new Error('db down');
        },
    }));
    await assert.doesNotReject(svc.markOpened(CONV));
    await assert.doesNotReject(svc.markReplied(CONV));
});
