import mongoose from 'mongoose';
import { ipKey } from '../utils/clientIp';

/**
 * Links a first app launch to the invitation link a participant used to download it.
 *
 * The join page stores {ip, ipKey, experimentId, timestamp, matched:false} in `apk_sessions` when the
 * participant downloads the app. The app's first launch asks the server who it is; the server can only
 * compare network addresses, which several participants may share (campus Wi-Fi, a lab, one home router).
 * Rather than guess, it matches only when every candidate belongs to the SAME experiment. If candidates
 * belong to different experiments the answer is "ambiguous" and the app asks the participant instead.
 */
export const MATCH_WINDOW_MS = 60 * 60 * 1000;
const MAX_CANDIDATES = 50;

export interface ApkSession {
    _id: unknown;
    experimentId: string;
    timestamp: Date;
}

export type MatchDecision =
    | { outcome: 'matched'; session: ApkSession }
    | { outcome: 'ambiguous'; experimentIds: string[] }
    | { outcome: 'none' };

/** Pure decision over the unmatched sessions that share the caller's network address. */
export const decideMatch = (candidates: ApkSession[]): MatchDecision => {
    if (!candidates.length) return { outcome: 'none' };

    const experimentIds = Array.from(new Set(candidates.map((c) => String(c.experimentId))));
    if (experimentIds.length > 1) return { outcome: 'ambiguous', experimentIds };

    // Several downloads for the same experiment (e.g. a room of participants): each device takes the newest one.
    const newest = candidates.reduce((a, b) => (new Date(b.timestamp) > new Date(a.timestamp) ? b : a));
    return { outcome: 'matched', session: newest };
};

type Cursor = { sort: (s: object) => { limit: (n: number) => { toArray: () => Promise<any[]> } } };
type Collection = {
    find: (filter: object) => Cursor;
    findOne: (filter: object, options?: object) => Promise<any>;
    updateOne: (filter: object, update: object) => Promise<{ modifiedCount?: number }>;
    insertOne: (doc: object) => Promise<unknown>;
};
type Db = { collection: (name: string) => Collection };

export interface MatchResult {
    status: number;
    body: { experimentId: string | null; reason?: string; experimentTitle?: string };
}

export const matchDevice = async (
    db: Db,
    ip: string,
    now: Date = new Date(),
): Promise<MatchResult> => {
    const key = ipKey(ip);
    const windowStart = new Date(now.getTime() - MATCH_WINDOW_MS);

    // `ip` is matched too so sessions stored before ipKey existed still work.
    const candidates = await db
        .collection('apk_sessions')
        .find({ matched: false, timestamp: { $gte: windowStart }, $or: [{ ipKey: key }, { ip }] })
        .sort({ timestamp: -1 })
        .limit(MAX_CANDIDATES)
        .toArray();

    const decision = decideMatch(candidates);
    const recordOutcome = (outcome: string) =>
        // Counts only (no address), so the match rate and how often links are ambiguous can be measured.
        db
            .collection('apk_match_events')
            .insertOne({
                at: now,
                outcome,
                candidates: candidates.length,
                experiments: new Set(candidates.map((c) => String(c.experimentId))).size,
            })
            .catch(() => undefined);

    if (decision.outcome === 'none') {
        await recordOutcome('none');
        return { status: 404, body: { experimentId: null, reason: 'no_session' } };
    }
    if (decision.outcome === 'ambiguous') {
        await recordOutcome('ambiguous');
        // 200 with no experiment: the app treats it as "no automatic match" and asks the participant.
        return { status: 200, body: { experimentId: null, reason: 'ambiguous' } };
    }

    // Consume the session only if nobody else did in the meantime.
    const claimed = await db
        .collection('apk_sessions')
        .updateOne({ _id: decision.session._id, matched: false }, { $set: { matched: true, matchedAt: now } });
    if (!claimed.modifiedCount) {
        await recordOutcome('lost_race');
        return { status: 404, body: { experimentId: null, reason: 'no_session' } };
    }
    await recordOutcome('matched');

    let experimentTitle: string | undefined;
    try {
        const experiment = await db
            .collection('experiments')
            .findOne({ _id: new mongoose.Types.ObjectId(decision.session.experimentId) }, { projection: { title: 1 } });
        experimentTitle = experiment?.title;
    } catch (_) {
        // The title is only a convenience for a future confirmation screen.
    }
    return { status: 200, body: { experimentId: decision.session.experimentId, experimentTitle } };
};

const OBJECT_ID_PATTERN = /^[a-f0-9]{24}$/i;

/**
 * What the app may learn about an experiment before the participant has joined it: its title and
 * whether it is active, nothing else (the full experiment document contains prompts and settings).
 * Returns null for an invalid or unknown id.
 */
export const publicExperimentInfo = async (
    db: Db,
    experimentId: string,
): Promise<{ title: string | null; isActive: boolean } | null> => {
    if (!OBJECT_ID_PATTERN.test(String(experimentId))) return null;
    const experiment = await db
        .collection('experiments')
        .findOne({ _id: new mongoose.Types.ObjectId(experimentId) }, { projection: { title: 1, isActive: 1 } });
    if (!experiment) return null;
    return { title: experiment.title ?? null, isActive: experiment.isActive !== false };
};

export const publicExperimentInfoFor = (experimentId: string) =>
    publicExperimentInfo(mongoose.connection.db as unknown as Db, experimentId);

export const matchCurrentDevice = (ip: string) => matchDevice(mongoose.connection.db as unknown as Db, ip);
