/**
 * V9 option 1 (docs/REVIEW.md): the join page hands the experiment to the installed app ("Open Lexi"),
 * and the app can confirm the experiment's title without seeing anything else about it.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { buildLandingPage } from '../controllers/joinController';
import { publicExperimentInfo } from '../services/sessionMatching';

const ID = '64b7f0f0f0f0f0f0f0f0f0a1';

test('the join page links straight into the installed app with the experiment id', () => {
    const html = buildLandingPage(ID);
    assert.ok(
        html.includes(`href="intent://join/${ID}#Intent;scheme=lexi;package=com.example.lexiparticipant;end"`),
        'Android intent link for Chrome and other browsers',
    );
    assert.ok(html.includes(`href="lexi://join/${ID}"`), 'plain custom-scheme fallback');
    assert.ok(html.includes(`href="/join/${ID}/download"`), 'download link is still there');
    assert.ok(html.includes('Open Lexi'));
});

test('the experiment id is escaped everywhere it is placed in the page', () => {
    const html = buildLandingPage('"><script>alert(1)</script>');
    assert.ok(!html.includes('<script>alert'), 'no raw script injection');
    assert.ok(!html.includes('"><script'), 'no attribute break-out');
});

const fakeDb = (doc: any) => {
    const filters: any[] = [];
    const db = {
        collection: () => ({
            findOne: async (filter: any, options: any) => {
                filters.push({ filter, options });
                return doc;
            },
        }),
    };
    return { db: db as any, filters };
};

test('public info exposes only title and active flag, never the rest of the experiment', async () => {
    const full = { _id: ID, title: 'Study A', isActive: true, experimentFeatures: { proactiveSettings: { heuristicPrompts: 'secret' } } };
    const { db, filters } = fakeDb(full);
    const info = await publicExperimentInfo(db, ID);
    assert.deepEqual(info, { title: 'Study A', isActive: true });
    assert.deepEqual(filters[0].options.projection, { title: 1, isActive: 1 }, 'only these fields are read');
    assert.ok(!JSON.stringify(info).includes('secret'));
});

test('an inactive experiment is reported as inactive; a missing flag counts as active', async () => {
    assert.equal((await publicExperimentInfo(fakeDb({ title: 'T', isActive: false }).db, ID))!.isActive, false);
    assert.equal((await publicExperimentInfo(fakeDb({ title: 'T' }).db, ID))!.isActive, true);
});

test('unknown or malformed ids give no information and never reach the database', async () => {
    assert.equal(await publicExperimentInfo(fakeDb(null).db, ID), null);
    const { db, filters } = fakeDb({ title: 'x' });
    for (const bad of ['', 'abc', '../x', '<script>', '{"$ne":""}', 'g'.repeat(24)]) {
        assert.equal(await publicExperimentInfo(db, bad), null, bad);
    }
    assert.equal(filters.length, 0);
});
