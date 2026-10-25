import { Request } from 'express';

/** Strip the IPv4-mapped IPv6 prefix so ::ffff:1.2.3.4 and 1.2.3.4 are the same address. */
export const normalizeIp = (ip: string): string => (ip.startsWith('::ffff:') ? ip.slice(7) : ip);

/**
 * The caller's address, accounting for Render's reverse proxy (first X-Forwarded-For entry).
 * Note: that header is client-controlled when no trusted proxy overwrites it, so this is a
 * best-effort identifier for matching a download to a first launch, never for security.
 */
export const getClientIp = (req: Request): string => {
    const forwarded = req.headers['x-forwarded-for'];
    const raw = forwarded
        ? (Array.isArray(forwarded) ? forwarded[0] : forwarded).split(',')[0].trim()
        : req.socket?.remoteAddress || req.ip || 'unknown';
    return normalizeIp(raw);
};

/** The eight 16-bit groups of an IPv6 address, or null if it is not a valid IPv6 address. */
export const expandIpv6 = (address: string): string[] | null => {
    const bare = address.split('%')[0].toLowerCase(); // drop a zone id such as %eth0
    if (!/^[0-9a-f:]+$/.test(bare) || (bare.match(/::/g) || []).length > 1) return null;

    const [head, tail] = bare.includes('::') ? bare.split('::') : [bare, null];
    const headGroups = head ? head.split(':') : [];
    const tailGroups = tail ? tail.split(':') : [];
    const missing = 8 - headGroups.length - tailGroups.length;
    if (tail === null ? headGroups.length !== 8 : missing < 1) return null;

    const groups = [...headGroups, ...(tail === null ? [] : Array(missing).fill('0')), ...tailGroups];
    if (groups.length !== 8 || groups.some((g) => g.length === 0 || g.length > 4)) return null;
    return groups.map((g) => g.padStart(4, '0'));
};

/**
 * The key two requests from the same device are compared on.
 * IPv4: the address itself. IPv6: the /64 network prefix, because a device's browser and app
 * often use different "privacy" interface identifiers inside the same /64.
 */
export const ipKey = (ip: string): string => {
    const normalized = normalizeIp(String(ip || ''));
    const groups = normalized.includes(':') ? expandIpv6(normalized) : null;
    return groups ? `v6:${groups.slice(0, 4).join(':')}` : normalized;
};
