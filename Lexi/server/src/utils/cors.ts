/**
 * Which browser origins may call the API with credentials (cookies).
 *
 * Production allows only the exact web-app origin(s). Development addresses are allowed
 * outside production. Anything else needs to be listed explicitly in CORS_EXTRA_ORIGINS.
 * Vercel preview deployments are allowed only if CORS_PREVIEW_SUFFIX is set to your own
 * Vercel account suffix (e.g. "-myteam.vercel.app"); a bare ".vercel.app" match would let
 * anyone who registers a look-alike project send credentialed requests.
 */
const PRODUCTION_ORIGIN = 'https://master-thesis-2026-2027-code-base.vercel.app';
const PREVIEW_PREFIX = 'https://master-thesis-2026-2027-code-base-';
const DEV_ORIGINS = [
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    'http://0.0.0.0:3000',
    'http://10.0.2.2:3000', // Android emulator
];

export interface CorsEnv {
    NODE_ENV?: string;
    FRONTEND_URL?: string;
    CORS_EXTRA_ORIGINS?: string;
    CORS_PREVIEW_SUFFIX?: string;
}

const list = (value?: string): string[] =>
    (value || '')
        .split(',')
        .map((v) => v.trim().replace(/\/+$/, ''))
        .filter(Boolean);

export const isOriginAllowed = (origin: string | undefined, env: CorsEnv): boolean => {
    // Requests without an Origin header (server-to-server, mobile native, curl) are not browser CORS requests.
    if (!origin) return true;

    const allowed = new Set<string>([PRODUCTION_ORIGIN, ...list(env.FRONTEND_URL), ...list(env.CORS_EXTRA_ORIGINS)]);
    if (env.NODE_ENV !== 'production') {
        DEV_ORIGINS.forEach((o) => allowed.add(o));
    }
    if (allowed.has(origin)) return true;

    const suffix = (env.CORS_PREVIEW_SUFFIX || '').trim();
    if (suffix.startsWith('-') && suffix.endsWith('.vercel.app')) {
        return origin.startsWith(PREVIEW_PREFIX) && origin.endsWith(suffix);
    }
    return false;
};

/** Origin callback for the `cors` package. A refused origin simply gets no CORS headers (no 500 error page). */
export const corsOrigin =
    (env: CorsEnv = process.env as CorsEnv) =>
    (origin: string | undefined, callback: (error: Error | null, allow?: boolean) => void): void => {
        callback(null, isOriginAllowed(origin, env));
    };
