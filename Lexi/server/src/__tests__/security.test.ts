/**
 * Tests for the API hardening in docs/REVIEW.md (S2 push-token auth, S4 /join validation,
 * S5 CORS). Run with `npm test`. They use Node's built-in test runner and need no database.
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';
import jwt from 'jsonwebtoken';
import { joinController } from '../controllers/joinController';
import { usersController } from '../controllers/usersController.controller';
import { usersRouter } from '../routers/usersRouter.router';
import { requireUser } from '../utils/authMiddleware';
import { isOriginAllowed } from '../utils/cors';
import { rateLimitByIp } from '../utils/rateLimit';

process.env.JWT_SECRET_KEY = 'test-secret';

// Minimal Express-like response double
const makeRes = () => {
    const res: any = { statusCode: 200, body: undefined, headers: {}, locals: {}, redirected: undefined };
    res.status = (code: number) => ((res.statusCode = code), res);
    res.json = (b: unknown) => ((res.body = b), res);
    res.send = (b: unknown) => ((res.body = b), res);
    res.type = () => res;
    res.setHeader = (k: string, v: string) => ((res.headers[k] = v), res);
    res.redirect = (url: string) => ((res.redirected = url), res);
    return res;
};

// ── S2: push-token routes require a login ────────────────────────────────────
test('both push-token routes are protected by requireUser', () => {
    const stack = (usersRouter() as any).stack;
    for (const path of ['/fcm-token', '/register-device']) {
        const layer = stack.find((l: any) => l.route && l.route.path === path);
        assert.ok(layer, `${path} is registered`);
        const handlers = layer.route.stack.map((s: any) => s.handle);
        assert.equal(handlers[0], requireUser, `${path} runs requireUser first`);
    }
});

test('requireUser rejects missing, forged and wrongly-signed cookies', () => {
    const cases: any[] = [
        {},
        { cookies: {} },
        { cookies: { token: 'not-a-jwt' } },
        { cookies: { token: jwt.sign({ id: 'u1' }, 'another-secret') } },
        { cookies: { token: jwt.sign({ nope: true }, 'test-secret') } },
    ];
    for (const req of cases) {
        const res = makeRes();
        let called = false;
        requireUser(req, res, () => (called = true));
        assert.equal(res.statusCode, 401);
        assert.equal(called, false);
    }
});

test('requireUser accepts a valid cookie and exposes the user id', () => {
    const res = makeRes();
    let called = false;
    requireUser({ cookies: { token: jwt.sign({ id: 'user-1' }, 'test-secret') } } as any, res, () => (called = true));
    assert.equal(called, true);
    assert.equal(res.locals.userId, 'user-1');
});

test('a user cannot set the token of a different user', async () => {
    for (const handler of [usersController.updateFCMToken, usersController.registerDevice]) {
        const res = makeRes();
        res.locals.userId = 'user-1';
        await handler(
            { method: 'POST', originalUrl: '/x', body: { userId: 'someone-else', fcmToken: 'x'.repeat(150) } } as any,
            res,
        );
        assert.equal(res.statusCode, 403);
    }
});

test('a token request without fcmToken is a 400', async () => {
    const res = makeRes();
    res.locals.userId = 'user-1';
    await usersController.updateFCMToken({ method: 'POST', originalUrl: '/x', body: {} } as any, res);
    assert.equal(res.statusCode, 400);
});

// ── S4: /join only accepts real-looking experiment ids ───────────────────────
test('/join rejects ids that are not 24 hex characters, without echoing input or touching the database', async () => {
    const hostile = [
        '"><script>alert(1)</script>',
        'abc',
        '../etc/passwd',
        'g'.repeat(24),
        '<img src=x onerror=alert(1)>',
    ];
    for (const experimentId of hostile) {
        const page = makeRes();
        await joinController.landingPage({ params: { experimentId } } as any, page);
        assert.equal(page.statusCode, 404, `landing page 404 for ${experimentId}`);
        assert.ok(!String(page.body).includes('<script'), 'response never echoes the input');

        const dl = makeRes();
        await joinController.downloadApk(
            { params: { experimentId }, headers: {}, socket: {}, ip: '1.2.3.4' } as any,
            dl,
        );
        assert.equal(dl.statusCode, 404);
        assert.equal(dl.redirected, undefined, 'no redirect to the APK');
    }
});

test('the download limiter answers 429 after too many requests from one IP', () => {
    const limit = rateLimitByIp(3, 60_000);
    const results: number[] = [];
    for (let i = 0; i < 5; i++) {
        const res = makeRes();
        let passed = false;
        limit({ ip: '9.9.9.9' } as any, res, () => (passed = true));
        results.push(passed ? 200 : res.statusCode);
    }
    assert.deepEqual(results, [200, 200, 200, 429, 429]);

    const other = makeRes();
    let passed = false;
    limit({ ip: '8.8.8.8' } as any, other, () => (passed = true));
    assert.equal(passed, true, 'a different IP has its own budget');
});

// ── S5: CORS ─────────────────────────────────────────────────────────────────
const PROD = 'https://master-thesis-2026-2027-code-base.vercel.app';

test('production allows exactly the web app, plus configured extras', () => {
    const env = {
        NODE_ENV: 'production',
        FRONTEND_URL: 'https://study.example.org/',
        CORS_EXTRA_ORIGINS: 'https://a.example.org, https://b.example.org',
    };
    assert.equal(isOriginAllowed(PROD, env), true);
    assert.equal(isOriginAllowed('https://study.example.org', env), true, 'trailing slash in config is ignored');
    assert.equal(isOriginAllowed('https://b.example.org', env), true);
    assert.equal(isOriginAllowed('https://evil.example.com', env), false);
});

test('look-alike Vercel projects are refused, even ones containing the project name', () => {
    const env = { NODE_ENV: 'production' };
    assert.equal(isOriginAllowed('https://master-thesis-2026-2027-code-base-evil.vercel.app', env), false);
    assert.equal(isOriginAllowed('https://evil.vercel.app', env), false);
    assert.equal(isOriginAllowed('https://master-thesis-2026-2027-code-base.vercel.app.evil.com', env), false);
});

test('previews are allowed only for your own suffix', () => {
    const env = { NODE_ENV: 'production', CORS_PREVIEW_SUFFIX: '-myteam.vercel.app' };
    assert.equal(isOriginAllowed('https://master-thesis-2026-2027-code-base-git-dev-myteam.vercel.app', env), true);
    assert.equal(isOriginAllowed('https://master-thesis-2026-2027-code-base-git-dev-otherteam.vercel.app', env), false);
    assert.equal(isOriginAllowed('https://other-project-myteam.vercel.app', env), false);
    // a suffix that is just ".vercel.app" is rejected as too broad
    assert.equal(
        isOriginAllowed('https://master-thesis-2026-2027-code-base-x.vercel.app', {
            NODE_ENV: 'production',
            CORS_PREVIEW_SUFFIX: '.vercel.app',
        }),
        false,
    );
});

test('development origins only work outside production', () => {
    assert.equal(isOriginAllowed('http://localhost:3000', { NODE_ENV: 'development' }), true);
    assert.equal(isOriginAllowed('http://localhost:3000', { NODE_ENV: 'production' }), false);
    assert.equal(
        isOriginAllowed('http://192.168.31.200:3000', { NODE_ENV: 'development' }),
        false,
        'a private LAN address is no longer hard-coded',
    );
});

test('requests without an Origin header (server-to-server, mobile) are unaffected', () => {
    assert.equal(isOriginAllowed(undefined, { NODE_ENV: 'production' }), true);
});
