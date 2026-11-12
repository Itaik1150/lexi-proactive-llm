/**
 * Study flow (docs/REVIEW.md P2, P5): baseline answers, completion codes, end survey.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { usersRouter } from '../routers/usersRouter.router';
import { baselineAnswers, studyDay, studyStatus } from '../services/study.service';
import { requireUser } from '../utils/authMiddleware';

const REGISTERED = new Date('2026-12-01T10:00:00Z');
const onDay = (n: number) => new Date(REGISTERED.getTime() + (n - 1) * 24 * 3600 * 1000 + 60 * 1000);
const SETTINGS = { durationDays: 14, endSurveyForm: 'form-1', onboardingCompletionCode: 'ONB123', finalCompletionCode: 'FIN456' };
const linked = { createdAt: REGISTERED, prolific: { pid: 'a'.repeat(24) } };

test('day 1 is the day of registration', () => {
    assert.equal(studyDay(REGISTERED, new Date(REGISTERED.getTime() + 1000)), 1);
    assert.equal(studyDay(REGISTERED, onDay(2)), 2);
    assert.equal(studyDay(REGISTERED, onDay(14)), 14);
    assert.equal(studyDay(undefined, new Date()), 1);
});

test('the onboarding code is shown to a linked participant until they confirm it', () => {
    assert.equal(studyStatus(linked, SETTINGS, onDay(1)).onboardingCode, 'ONB123');
    const confirmed = { ...linked, study: { onboardingCodeAckAt: new Date() } };
    assert.equal(studyStatus(confirmed, SETTINGS, onDay(1)).onboardingCode, null);
});

test('a participant who is not linked to Prolific never sees a completion code', () => {
    const tester = { createdAt: REGISTERED, study: { endSurvey: { submittedAt: new Date() } } };
    const s = studyStatus(tester, SETTINGS, onDay(20));
    assert.equal(s.onboardingCode, null);
    assert.equal(s.finalCode, null);
});

test('the end survey opens on the last day, not before', () => {
    assert.equal(studyStatus(linked, SETTINGS, onDay(13)).endSurveyDue, false);
    assert.equal(studyStatus(linked, SETTINGS, onDay(14)).endSurveyDue, true);
    assert.equal(studyStatus(linked, SETTINGS, onDay(30)).endSurveyDue, true, 'still open for a late participant');
});

test('the final code appears only after the end survey was submitted', () => {
    assert.equal(studyStatus(linked, SETTINGS, onDay(14)).finalCode, null);
    const done = { ...linked, study: { endSurvey: { submittedAt: new Date() } } };
    const s = studyStatus(done, SETTINGS, onDay(14));
    assert.equal(s.finalCode, 'FIN456');
    assert.equal(s.endSurveyDue, false);
    assert.equal(s.endSurveyDone, true);
});

test('without an end survey the final code appears once the study period is over', () => {
    const settings = { ...SETTINGS, endSurveyForm: undefined };
    assert.equal(studyStatus(linked, settings, onDay(14)).finalCode, null);
    assert.equal(studyStatus(linked, settings, onDay(15)).finalCode, 'FIN456');
});

test('an experiment without study settings shows nothing and does not break', () => {
    const s = studyStatus(linked, undefined, onDay(20));
    assert.deepEqual(
        [s.durationDays, s.onboardingCode, s.endSurveyDue, s.finalCode],
        [14, null, false, null],
    );
});

test('baseline answers: everything that is not a fixed column, cleaned', () => {
    const answers = baselineAnswers({
        username: 'dana',
        age: 30,
        gender: 'female',
        ddi_1: 5,
        uls_3: '4',
        consent: true,
        'bad key!': 1,
        $where: 'x',
        nested: { a: 1 },
        list: [1, 2],
        long: 'x'.repeat(3000),
    });
    assert.deepEqual(answers, { ddi_1: 5, uls_3: '4', consent: true });
    assert.deepEqual(baselineAnswers(undefined), {});
});

test('the study routes require a login', () => {
    const stack = (usersRouter() as any).stack;
    for (const path of ['/study-status', '/onboarding-code-seen', '/end-survey', '/prolific-id']) {
        const layer = stack.find((l: any) => l.route && l.route.path === path);
        assert.ok(layer, `${path} is registered`);
        assert.equal(layer.route.stack[0].handle, requireUser, `${path} runs requireUser first`);
    }
});

// ── participation view ───────────────────────────────────────────────────────
import { summarise } from '../services/participation.service';

test('participation: only conversations the participant wrote in count, split by study week', () => {
    const at = (day: number) => onDay(day);
    const user = { username: 'dana', createdAt: REGISTERED, prolific: { pid: 'a'.repeat(24), linkedBy: 'auto' }, registrationAnswers: { ddi_1: 5 } };
    const conversations = [
        { createdAt: at(1), messagesNumber: 3, isFinished: true, postConversation: { q1: 5 }, lastMessageDate: at(1) },
        { createdAt: at(2), messagesNumber: 0 }, // an opener nobody answered: not a conversation
        { createdAt: at(7), messagesNumber: 1, isFinished: false },
        { createdAt: at(8), messagesNumber: 2, isFinished: true, postConversation: {}, lastMessageDate: at(9) },
        { createdAt: at(15), messagesNumber: 4, isFinished: true }, // after the study period
    ];
    const logs = [
        { status: 'sent', tapped_at: new Date(), first_reply_at: new Date() },
        { status: 'sent', tapped_at: new Date() },
        { status: 'sent' },
        { status: 'skipped_quota' },
    ];
    const row = summarise(user, conversations, logs, at(10));
    assert.deepEqual(
        [row.conversations, row.conversationsWeek1, row.conversationsWeek2, row.finished, row.surveysAfterConversation],
        [4, 2, 1, 3, 1],
    );
    assert.deepEqual([row.notificationsSent, row.notificationsTapped, row.notificationsReplied], [3, 2, 1]);
    assert.deepEqual([row.day, row.baselineAnswered, row.endSurveyDone, row.prolificId], [10, true, false, 'a'.repeat(24)]);
});

test('participation: a participant who never did anything gives zeros, not errors', () => {
    const row = summarise({ username: 'ghost', createdAt: REGISTERED }, [], [], onDay(3));
    assert.deepEqual(
        [row.conversations, row.notificationsSent, row.lastActive, row.prolificId, row.baselineAnswered],
        [0, 0, null, null, false],
    );
});
