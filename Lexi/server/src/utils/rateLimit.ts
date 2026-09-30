import { NextFunction, Request, Response } from 'express';

/**
 * Minimal in-memory fixed-window limiter per client IP. Good enough to stop a script from
 * flooding a public endpoint; it resets when the server restarts and is per instance.
 * Keep the limit generous: participants in one room share a single public IP.
 */
export const rateLimitByIp = (maxRequests: number, windowMs: number) => {
    const hits = new Map<string, { count: number; resetAt: number }>();

    return (req: Request, res: Response, next: NextFunction): void => {
        const now = Date.now();
        const key = req.ip || 'unknown';
        let entry = hits.get(key);

        if (!entry || entry.resetAt <= now) {
            entry = { count: 0, resetAt: now + windowMs };
            hits.set(key, entry);
            // Opportunistic cleanup so the map cannot grow without bound.
            if (hits.size > 5000) {
                hits.forEach((value, k) => {
                    if (value.resetAt <= now) hits.delete(k);
                });
            }
        }

        entry.count += 1;
        if (entry.count > maxRequests) {
            res.setHeader('Retry-After', String(Math.ceil((entry.resetAt - now) / 1000)));
            res.status(429).send('Too many requests. Please try again in a few minutes.');
            return;
        }
        next();
    };
};
