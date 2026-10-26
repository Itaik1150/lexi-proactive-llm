/**
 * M2 / M3 (docs/REVIEW.md, D15): the chat prompt carries today's date and ALL dated notes of earlier
 * conversations, identically for every condition.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    buildMemorySection,
    buildProactiveSection,
    composeSystemPrompt,
    formatDay,
    todayLine,
} from '../services/chatMemoryPrompt';

const NOW = new Date('2026-10-26T12:00:00Z');
const PERSONA = 'You are Lexi, an empathetic AI companion.';

const NOTES = {
    c2: { summary: 'The user has a big exam tomorrow and is very nervous.', conversation_date: '2026-10-26', updated_at: '2026-10-26T11:35:00' },
    c1: { summary: 'The user said their dog Rex is sick.', conversation_date: '2026-10-24', updated_at: '2026-10-24T18:00:00' },
    c3: { summary: 'The user is excited that their sister Maya is visiting.', conversation_date: '2026-10-26', updated_at: '2026-10-26T12:10:00' },
};

test('dates are written out in full and in UTC', () => {
    assert.equal(formatDay('2026-10-26'), 'Monday 26 October 2026');
    assert.equal(formatDay(new Date('2026-12-31T23:59:00Z')), 'Thursday 31 December 2026');
    assert.equal(formatDay('not a date'), '');
    assert.equal(formatDay(undefined), '');
    assert.equal(todayLine(NOW), 'Today is Monday 26 October 2026.');
});

test('every earlier note appears with its date, oldest first', () => {
    const text = buildMemorySection(NOTES);
    const lines = text.split('\n').filter((l) => l.startsWith('- '));
    assert.deepEqual(lines, [
        '- Saturday 24 October 2026: The user said their dog Rex is sick.',
        '- Monday 26 October 2026: The user has a big exam tomorrow and is very nervous.',
        '- Monday 26 October 2026: The user is excited that their sister Maya is visiting.',
    ]);
});

test('the note of the conversation that is going on is left out', () => {
    const text = buildMemorySection(NOTES, 'c3');
    assert.ok(!text.includes('Maya'));
    assert.ok(text.includes('exam'));
});

test('nothing to remember gives no memory section at all', () => {
    assert.equal(buildMemorySection(undefined), '');
    assert.equal(buildMemorySection({}), '');
    assert.equal(buildMemorySection({ a: { summary: '   ' }, b: {} }), '');
});

test('a note without a usable date is still shown, not lost', () => {
    const text = buildMemorySection({ a: { summary: 'The user likes tea.' } });
    assert.ok(text.includes('- Earlier: The user likes tea.'));
});

test('the memory section tells the model not to invent past events', () => {
    const text = buildMemorySection(NOTES);
    assert.ok(text.includes('never invent or guess past events'));
    assert.ok(text.includes('Do not say that you read notes'));
});

test('M3: Reactive, Standard and Affective participants get exactly the same chat prompt', () => {
    // The builder has no condition parameter; the same stored notes must give the same prompt.
    const participants = ['reactive', 'generic', 'affective'].map((group) => ({ group, notes: { ...NOTES } }));
    const prompts = participants.map((p) =>
        composeSystemPrompt({ persona: PERSONA, now: NOW, notes: p.notes, currentConversationId: 'c-now' }),
    );
    assert.equal(prompts[0], prompts[1]);
    assert.equal(prompts[1], prompts[2]);
    for (const n of Object.values(NOTES)) assert.ok(prompts[0].includes(n.summary));
    assert.ok(prompts[0].startsWith(PERSONA));
    assert.ok(prompts[0].includes('Today is Monday 26 October 2026.'));
});

test('the memory behind a notification is an addition to the same prompt, not a replacement', () => {
    const plain = composeSystemPrompt({ persona: PERSONA, now: NOW, notes: NOTES, currentConversationId: 'c-now' });
    const fromNotification = composeSystemPrompt({
        persona: PERSONA,
        now: NOW,
        notes: NOTES,
        currentConversationId: 'c-now',
        proactive: {
            memory: 'The user has a big exam tomorrow.',
            transcript: 'User: Have a big exam tomorrow, very nervous',
            sharedOn: '2026-10-26',
            when: 'tomorrow',
            whenDate: '2026-10-27',
        },
    });
    assert.ok(fromNotification.startsWith(plain));
    assert.ok(fromNotification.includes('"The user has a big exam tomorrow."'));
    assert.ok(fromNotification.includes('told you this on Monday 26 October 2026'));
    assert.ok(fromNotification.includes('they said: "tomorrow" (Tuesday 27 October 2026)'));
    assert.ok(fromNotification.includes('Have a big exam tomorrow, very nervous'));
});

test('no proactive context gives no extra section', () => {
    assert.equal(buildProactiveSection(null), '');
    assert.equal(buildProactiveSection({ memory: '', transcript: 'x' }), '');
});

test('today is stated even when there is no memory yet', () => {
    const text = composeSystemPrompt({ persona: PERSONA, now: NOW });
    assert.equal(text, `${PERSONA}\n\nToday is Monday 26 October 2026.`);
});
