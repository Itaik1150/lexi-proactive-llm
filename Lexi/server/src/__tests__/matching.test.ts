/**
 * V9 (docs/REVIEW.md): matching a first launch to a download must never silently pick the wrong experiment.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { decideMatch, matchDevice, ApkSession } from '../services/sessionMatching';
import { expandIpv6, getClientIp, ipKey } from '../utils/clientIp';

const EXP_A = '64b7f0f0f0f0f0f0f0f0f0a1';
const EXP_B = '64b7f0f0f0f0f0f0f0f0f0b2';
const NOW = new Date('2026-10-26T12:00:00Z');
const minutesAgo = (m: number) => new Date(NOW.getTime() - m * 60_000);

// ── IP keys ──────────────────────────────────────────────────────────────────
test('IPv4 addresses are their own key, and IPv4-mapped IPv6 is unwrapped', () => {
    assert.equal(ipKey('84.108.12.7'), '84.108.12.7');
    assert.equal(ipKey('::ffff:84.108.12.7'), '84.108.12.7');
});

test('IPv6 addresses are compared on their /64 prefix, however they are written', () => {
    const a = ipKey('2001:db8:abcd:12:aaaa:bbbb:cccc:dddd'); // browser identifier
    const b = ipKey('2001:0DB8:ABCD:0012:1111:2222:3333:4444'); // app identifier, same network
    assert.equal(a, b);
    assert.equal(a, 'v6:2001:0db8:abcd:0012');
    assert.notEqual(a, ipKey('2001:db8:abcd:13:aaaa:bbbb:cccc:dddd'), 'a different /64 is a different key');
    assert.equal(ipKey('2001:db8::1'), 'v6:2001:0db8:0000:0000', 'abbreviations are expanded');
    assert.equal(ipKey('fe80::1%eth0'), 'v6:fe80:0000:0000:0000', 'zone ids are ignored');
});

test('expandIpv6 rejects malformed addresses instead of guessing', () => {
    for (const bad of ['1:2:3', '1::2::3', 'zzzz::1', '12345::1', '1:2:3:4:5:6:7:8:9', '']) {
        assert.equal(expandIpv6(bad), null, bad);
    }
    assert.deepEqual(expandIpv6('::1'), ['0000', '0000', '0000', '0000', '0000', '0000', '0000', '0001']);
});

test('getClientIp uses the first forwarded address, else the socket', () => {
    assert.equal(getClientIp({ headers: { 'x-forwarded-for': '1.2.3.4, 10.0.0.1' }, socket: {} } as any), '1.2.3.4');
    assert.equal(getClientIp({ headers: {}, socket: { remoteAddress: '::ffff:5.6.7.8' } } as any), '5.6.7.8');
});

// ── The decision ─────────────────────────────────────────────────────────────
const session = (id: string, experimentId: string, ago: number, extra: object = {}): ApkSession & object => ({
    _id: id, experimentId, timestamp: minutesAgo(ago), ...extra,
});

test('no recent download means no match', () => {
    assert.deepEqual(decideMatch([]), { outcome: 'none' });
});

test('one download matches it', () => {
    const d = decideMatch([session('s1', EXP_A, 5)]);
    assert.equal(d.outcome, 'matched');
});

test('several downloads for the same experiment match the newest (a room of participants)', () => {
    const d = decideMatch([session('old', EXP_A, 20), session('new', EXP_A, 2), session('mid', EXP_A, 9)]);
    assert.equal(d.outcome, 'matched');
    assert.equal((d as any).session._id, 'new');
});

test('downloads for DIFFERENT experiments from one address are ambiguous: never guess', () => {
    const d = decideMatch([session('s1', EXP_A, 3), session('s2', EXP_B, 1)]);
    assert.equal(d.outcome, 'ambiguous');
    assert.deepEqual((d as any).experimentIds.sort(), [EXP_A, EXP_B].sort());
});

// ── End to end against a fake database ───────────────────────────────────────
const fakeDb = (sessions: any[]) => {
    const events: any[] = [];
    const updates: any[] = [];
    const matches = (s: any, f: any) =>
        s.matched === f.matched &&
        s.timestamp >= f.timestamp.$gte &&
        f.$or.some((c: any) => (c.ipKey !== undefined && s.ipKey === c.ipKey) || (c.ip !== undefined && s.ip === c.ip));
    const db = {
        collection: (name: string) => {
            if (name === 'apk_sessions') {
                return {
                    find: (f: any) => ({
                        sort: () => ({
                            limit: () => ({
                                toArray: async () =>
                                    sessions.filter((s) => matches(s, f)).sort((a, b) => +b.timestamp - +a.timestamp),
                            }),
                        }),
                    }),
                    updateOne: async (f: any, u: any) => {
                        const s = sessions.find((x) => x._id === f._id && x.matched === f.matched);
                        updates.push({ f, u, found: !!s });
                        if (!s) return { modifiedCount: 0 };
                        Object.assign(s, u.$set);
                        return { modifiedCount: 1 };
                    },
                };
            }
            if (name === 'apk_match_events') return { insertOne: async (d: any) => void events.push(d) };
            if (name === 'experiments') return { findOne: async () => ({ title: 'Study A' }) };
            throw new Error(`unexpected collection ${name}`);
        },
    };
    return { db: db as any, events, updates };
};

const stored = (id: string, experimentId: string, ago: number, ip: string, matched = false) => ({
    _id: id, experimentId, ip, ipKey: ipKey(ip), timestamp: minutesAgo(ago), matched,
});

test('a clear match returns the experiment and its title, and consumes that one session', async () => {
    const { db, events } = fakeDb([stored('s1', EXP_A, 5, '84.108.12.7'), stored('s2', EXP_B, 5, '5.5.5.5')]);
    const r = await matchDevice(db, '84.108.12.7', NOW);
    assert.equal(r.status, 200);
    assert.deepEqual(r.body, { experimentId: EXP_A, experimentTitle: 'Study A' });
    assert.equal(events[0].outcome, 'matched');
    // the same device asking again finds nothing left to consume
    assert.equal((await matchDevice(db, '84.108.12.7', NOW)).status, 404);
});

test('two experiments behind one address: the answer is ambiguous and nothing is consumed', async () => {
    const sessions = [stored('s1', EXP_A, 5, '84.108.12.7'), stored('s2', EXP_B, 2, '84.108.12.7')];
    const { db, events } = fakeDb(sessions);
    const r = await matchDevice(db, '84.108.12.7', NOW);
    assert.equal(r.status, 200, 'the app reads this as "no automatic match" and asks the participant');
    assert.deepEqual(r.body, { experimentId: null, reason: 'ambiguous' });
    assert.ok(sessions.every((s) => s.matched === false), 'no session was consumed');
    assert.equal(events[0].outcome, 'ambiguous');
    assert.equal(events[0].experiments, 2);
});

test('the phone browser and the app match even when their IPv6 identifiers differ', async () => {
    const { db } = fakeDb([stored('s1', EXP_A, 5, '2001:db8:abcd:12:aaaa:bbbb:cccc:dddd')]);
    const r = await matchDevice(db, '2001:db8:abcd:12:1111:2222:3333:4444', NOW);
    assert.equal(r.body.experimentId, EXP_A);
});

test('sessions from before ipKey existed still match on the exact address', async () => {
    const legacy = { _id: 'old', experimentId: EXP_A, ip: '84.108.12.7', timestamp: minutesAgo(5), matched: false };
    const { db } = fakeDb([legacy]);
    assert.equal((await matchDevice(db, '84.108.12.7', NOW)).body.experimentId, EXP_A);
});

test('downloads older than an hour, or already used, do not match', async () => {
    const { db } = fakeDb([stored('s1', EXP_A, 61, '84.108.12.7'), stored('s2', EXP_B, 3, '84.108.12.7', true)]);
    const r = await matchDevice(db, '84.108.12.7', NOW);
    assert.equal(r.status, 404);
    assert.equal(r.body.experimentId, null);
});

test('losing a race for the same session answers "no match" instead of assigning it twice', async () => {
    const sessions = [stored('s1', EXP_A, 5, '84.108.12.7')];
    const { db } = fakeDb(sessions);
    // another device consumes the session between our read and our update
    const collection = db.collection;
    db.collection = (name: string) => {
        const c = collection(name);
        if (name !== 'apk_sessions') return c;
        return { ...c, updateOne: async () => ({ modifiedCount: 0 }) };
    };
    const r = await matchDevice(db, '84.108.12.7', NOW);
    assert.equal(r.status, 404);
});
