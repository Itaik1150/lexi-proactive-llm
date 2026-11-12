/**
 * P1 / P5 (docs/REVIEW.md): Prolific id capture and the balanced random assignment link.
 * A tiny in-memory database stands in for MongoDB.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
    createProlificService,
    pickLeastFilled,
    readExperimentList,
    readProlificParams,
} from '../services/prolific.service';

const PID_A = 'aaaaaaaaaaaaaaaaaaaaaaaa';
const PID_B = 'bbbbbbbbbbbbbbbbbbbbbbbb';
const EXP_1 = '111111111111111111111111';
const EXP_2 = '222222222222222222222222';
const EXP_3 = '333333333333333333333333';
const USER_1 = '64b7f0f0f0f0f0f0f0f0f0f1';
const USER_2 = '64b7f0f0f0f0f0f0f0f0f0f2';
const IP = '81.2.3.4';

const get = (doc: any, path: string) => path.split('.').reduce((o, k) => (o == null ? undefined : o[k]), doc);

const matches = (doc: any, filter: any): boolean =>
    Object.entries(filter).every(([key, cond]: [string, any]) => {
        const value = key === '_id' ? String(doc._id) : get(doc, key);
        if (cond !== null && typeof cond === 'object' && !(cond instanceof Date)) {
            if ('$ne' in cond) return value !== cond.$ne;
            if ('$gte' in cond) return value >= cond.$gte;
            return String(value) === String(cond); // ObjectId
        }
        return cond === null ? value == null : value === cond;
    });

const collection = (docs: any[] = []) => ({
    docs,
    findOne: async (filter: any) => docs.find((d) => matches(d, filter)) || null,
    countDocuments: async (filter: any) => docs.filter((d) => matches(d, filter)).length,
    find: (filter: any) => ({
        limit: (n: number) => ({ toArray: async () => docs.filter((d) => matches(d, filter)).slice(0, n) }),
    }),
    insertOne: async (doc: any) => void docs.push(doc),
    updateOne: async (filter: any, update: any, options: any = {}) => {
        let doc = docs.find((d) => matches(d, filter));
        if (!doc) {
            if (!options.upsert) return;
            doc = { ...(update.$setOnInsert || {}) };
            docs.push(doc);
        }
        for (const [path, value] of Object.entries(update.$set || {})) doc[path] = value;
    },
});

const makeDb = (users: any[] = [], joins: any[] = []) => {
    const cols: Record<string, any> = { users: collection(users), prolific_joins: collection(joins) };
    return { db: { collection: (name: string) => cols[name] }, cols };
};

// ── reading the link ─────────────────────────────────────────────────────────
test('Prolific parameters are read only when the participant id is well-formed', () => {
    assert.deepEqual(readProlificParams({ PROLIFIC_PID: PID_A.toUpperCase(), STUDY_ID: EXP_1, SESSION_ID: 'junk' }), {
        pid: PID_A,
        studyId: EXP_1,
        sessionId: undefined,
    });
    for (const bad of [undefined, {}, { PROLIFIC_PID: 'abc' }, { PROLIFIC_PID: ['x'] }, { PROLIFIC_PID: '<script>' }]) {
        assert.equal(readProlificParams(bad as any), null);
    }
});

test('the experiment list keeps only valid, distinct ids', () => {
    assert.deepEqual(readExperimentList(`${EXP_1}, ${EXP_2},bad,${EXP_1},${EXP_3}`), [EXP_1, EXP_2, EXP_3]);
    assert.deepEqual(readExperimentList(undefined), []);
});

// ── balanced random assignment ───────────────────────────────────────────────
test('the least-filled experiment is chosen; equals are chosen at random', () => {
    assert.equal(pickLeastFilled({ a: 3, b: 1, c: 2 }), 'b');
    assert.equal(pickLeastFilled({ a: 2, b: 2, c: 5 }, () => 0), 'a');
    assert.equal(pickLeastFilled({ a: 2, b: 2, c: 5 }, () => 0.99), 'b');
});

test('assignment balances on registered participants plus recent joins that have not registered yet', async () => {
    const users = [
        { _id: 'u1', experimentId: EXP_1 },
        { _id: 'u2', experimentId: EXP_1 },
        { _id: 'u3', experimentId: EXP_2 },
        { _id: 'admin', experimentId: EXP_3, isAdmin: true }, // admins do not count
    ];
    const joins = [{ pid: PID_B, experimentId: EXP_3, claimedBy: null, createdAt: new Date() }];
    const { db } = makeDb(users, joins);
    // counts: EXP_1 = 2, EXP_2 = 1, EXP_3 = 1 (pending) -> tie between 2 and 3
    const svc = createProlificService(() => db);
    assert.equal(await svc.chooseExperiment([EXP_1, EXP_2, EXP_3], () => 0), EXP_2);
    assert.equal(await svc.chooseExperiment([EXP_1, EXP_2, EXP_3], () => 0.99), EXP_3);
});

test('sixty participants in a row end up twenty per condition', async () => {
    const { db, cols } = makeDb();
    const svc = createProlificService(() => db);
    for (let i = 0; i < 60; i++) {
        const chosen = await svc.chooseExperiment([EXP_1, EXP_2, EXP_3]);
        cols.users.docs.push({ _id: `u${i}`, experimentId: chosen });
    }
    for (const id of [EXP_1, EXP_2, EXP_3]) {
        assert.equal(cols.users.docs.filter((u: any) => u.experimentId === id).length, 20);
    }
});

test('a participant keeps their condition when they open the link again', async () => {
    const { db } = makeDb();
    const svc = createProlificService(() => db);
    await svc.recordJoin({ pid: PID_A }, EXP_2, IP);
    await svc.recordJoin({ pid: PID_A }, EXP_3, '9.9.9.9'); // a second visit must not move them
    assert.equal(await svc.assignedExperiment(PID_A), EXP_2);
    assert.equal(await svc.assignedExperiment(PID_B), null);
});

// ── linking the account ──────────────────────────────────────────────────────
test('registration links automatically when exactly one join came from the same address', async () => {
    const { db, cols } = makeDb([{ _id: USER_1, experimentId: EXP_1 }]);
    const svc = createProlificService(() => db);
    await svc.recordJoin({ pid: PID_A, studyId: EXP_3 }, EXP_1, IP);
    assert.equal(await svc.linkAfterRegistration(USER_1, EXP_1, IP), 'linked');
    assert.equal(cols.users.docs[0].prolific.pid, PID_A);
    assert.equal(cols.users.docs[0].prolific.linkedBy, 'auto');
    assert.equal(cols.prolific_joins.docs[0].claimedBy, USER_1);
});

test('two unclaimed joins from one address are not guessed: the app asks instead', async () => {
    const { db, cols } = makeDb([{ _id: USER_1, experimentId: EXP_1 }]);
    const svc = createProlificService(() => db);
    await svc.recordJoin({ pid: PID_A }, EXP_1, IP);
    await svc.recordJoin({ pid: PID_B }, EXP_1, IP);
    assert.equal(await svc.linkAfterRegistration(USER_1, EXP_1, IP), 'missing');
    assert.equal(cols.users.docs[0].prolific, undefined);
});

test('a different address, or a join that is already claimed, is not linked automatically', async () => {
    const { db } = makeDb([{ _id: USER_1, experimentId: EXP_1 }, { _id: USER_2, experimentId: EXP_1 }]);
    const svc = createProlificService(() => db);
    await svc.recordJoin({ pid: PID_A }, EXP_1, IP);
    assert.equal(await svc.linkAfterRegistration(USER_1, EXP_1, '5.5.5.5'), 'missing');
    assert.equal(await svc.linkAfterRegistration(USER_1, EXP_1, IP), 'linked');
    assert.equal(await svc.linkAfterRegistration(USER_2, EXP_1, IP), 'missing', 'the join was already used');
});

test('an experiment never used with Prolific does not ask testers for an id', async () => {
    const { db } = makeDb([{ _id: USER_1, experimentId: EXP_1 }]);
    assert.equal(await createProlificService(() => db).linkAfterRegistration(USER_1, EXP_1, IP), 'not_applicable');
});

test('typing the id links it; a malformed, taken or other-group id is refused', async () => {
    const { db, cols } = makeDb([{ _id: USER_1, experimentId: EXP_1 }, { _id: USER_2, experimentId: EXP_1 }]);
    const svc = createProlificService(() => db);
    await svc.recordJoin({ pid: PID_B }, EXP_2, IP); // PID_B was assigned to another experiment

    assert.equal(((await svc.linkManually(USER_1, EXP_1, 'not-an-id')) as any).status, 400);
    assert.equal(((await svc.linkManually(USER_1, EXP_1, { $ne: '' })) as any).status, 400);
    assert.equal(((await svc.linkManually(USER_1, EXP_1, PID_B)) as any).status, 409, 'belongs to another group');

    assert.deepEqual(await svc.linkManually(USER_1, EXP_1, ` ${PID_A.toUpperCase()} `), { ok: true });
    assert.equal(cols.users.docs[0].prolific.pid, PID_A);
    assert.equal(cols.users.docs[0].prolific.linkedBy, 'manual');

    assert.equal(((await svc.linkManually(USER_2, EXP_1, PID_A)) as any).status, 409, 'already linked to another account');
    assert.deepEqual(await svc.linkManually(USER_1, EXP_1, PID_A), { ok: true }, 'the same account may repeat it');
});
