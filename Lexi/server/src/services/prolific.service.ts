import mongoose from 'mongoose';
import { ipKey } from '../utils/clientIp';

/**
 * Prolific linkage (docs/REVIEW.md P1, P5).
 *
 * `prolific_joins` has one document per Prolific participant who opened the study link:
 *   { pid, studyId, sessionId, experimentId, ipKey, createdAt, lastSeenAt, claimedBy, claimedAt, how }
 * It is at the same time the RANDOMISATION LOG: `experimentId` is the condition the participant was
 * assigned to, and it never changes for that participant (opening the link again gives the same one).
 *
 * A registered participant carries `users.prolific = { pid, studyId, sessionId, linkedBy, linkedAt }`.
 * The link is made automatically at registration when exactly one unclaimed join of that experiment
 * came from the same network address; otherwise the app asks the participant to paste their id.
 */

export const PROLIFIC_ID_PATTERN = /^[a-f0-9]{24}$/i;
const OBJECT_ID_PATTERN = /^[a-f0-9]{24}$/i;

const AUTO_LINK_WINDOW_MS = 24 * 60 * 60 * 1000; // a join older than this is not linked automatically
const PENDING_WINDOW_MS = 2 * 60 * 60 * 1000; // joins this recent count as "about to register" when balancing

export interface ProlificParams {
    pid: string;
    studyId?: string;
    sessionId?: string;
}

/** The three ids Prolific appends to the study link; null unless the participant id is well-formed. */
export const readProlificParams = (query: Record<string, unknown> | undefined): ProlificParams | null => {
    const pick = (name: string): string | undefined => {
        const value = query?.[name];
        return typeof value === 'string' && PROLIFIC_ID_PATTERN.test(value) ? value.toLowerCase() : undefined;
    };
    const pid = pick('PROLIFIC_PID');
    if (!pid) return null;
    return { pid, studyId: pick('STUDY_ID'), sessionId: pick('SESSION_ID') };
};

/** Experiment ids from "?e=id1,id2,id3": valid, distinct, at most 6. */
export const readExperimentList = (value: unknown): string[] => {
    if (typeof value !== 'string') return [];
    const ids = value
        .split(',')
        .map((s) => s.trim().toLowerCase())
        .filter((s) => OBJECT_ID_PATTERN.test(s));
    return Array.from(new Set(ids)).slice(0, 6);
};

/** The experiment with the fewest participants; a random one among equals. */
export const pickLeastFilled = (counts: Record<string, number>, random: () => number = Math.random): string => {
    const ids = Object.keys(counts);
    const min = Math.min(...ids.map((id) => counts[id]));
    const candidates = ids.filter((id) => counts[id] === min);
    return candidates[Math.floor(random() * candidates.length)];
};

type Db = { collection: (name: string) => any };

export const createProlificService = (getDb: () => Db = () => mongoose.connection.db as unknown as Db) => {
    const joins = () => getDb().collection('prolific_joins');
    const users = () => getDb().collection('users');

    /** The condition already assigned to this Prolific participant, if any (it never changes). */
    const assignedExperiment = async (pid: string): Promise<string | null> => {
        const join = await joins().findOne({ pid });
        return join?.experimentId || null;
    };

    /**
     * Balanced random assignment over the given experiments: the one with the fewest participants
     * (registered, plus recent joins that have not registered yet), random among equals.
     */
    const chooseExperiment = async (experimentIds: string[], random: () => number = Math.random): Promise<string> => {
        const since = new Date(Date.now() - PENDING_WINDOW_MS);
        const counts: Record<string, number> = {};
        for (const id of experimentIds) {
            const [registered, pending] = await Promise.all([
                users().countDocuments({ experimentId: id, isAdmin: { $ne: true } }),
                joins().countDocuments({ experimentId: id, claimedBy: null, createdAt: { $gte: since } }),
            ]);
            counts[id] = registered + pending;
        }
        return pickLeastFilled(counts, random);
    };

    /** Remember that this Prolific participant opened the link for this experiment, from this address. */
    const recordJoin = async (params: ProlificParams, experimentId: string, ip: string): Promise<void> => {
        const now = new Date();
        await joins().updateOne(
            { pid: params.pid },
            {
                $set: { ipKey: ipKey(ip), lastSeenAt: now, studyId: params.studyId, sessionId: params.sessionId },
                // the assignment is written once and never overwritten
                $setOnInsert: { pid: params.pid, experimentId, createdAt: now, claimedBy: null },
            },
            { upsert: true },
        );
    };

    const attach = async (userId: string, join: any, linkedBy: 'auto' | 'manual'): Promise<void> => {
        const now = new Date();
        await users().updateOne(
            { _id: new mongoose.Types.ObjectId(userId) },
            {
                $set: {
                    prolific: {
                        pid: join.pid,
                        studyId: join.studyId,
                        sessionId: join.sessionId,
                        linkedBy,
                        linkedAt: now,
                    },
                },
            },
        );
        await joins().updateOne({ pid: join.pid }, { $set: { claimedBy: userId, claimedAt: now, how: linkedBy } });
    };

    /**
     * After registration: 'linked' if exactly one unclaimed, recent join of this experiment came from
     * the same network address; 'missing' if the experiment is used with Prolific but no unambiguous
     * join was found (the app then asks for the id); 'not_applicable' if nobody ever joined this
     * experiment through Prolific (internal testing).
     */
    const linkAfterRegistration = async (
        userId: string,
        experimentId: string,
        ip: string,
    ): Promise<'linked' | 'missing' | 'not_applicable'> => {
        try {
            const usedWithProlific = await joins().countDocuments({ experimentId });
            if (!usedWithProlific) return 'not_applicable';
            const candidates = await joins()
                .find({
                    experimentId,
                    ipKey: ipKey(ip),
                    claimedBy: null,
                    lastSeenAt: { $gte: new Date(Date.now() - AUTO_LINK_WINDOW_MS) },
                })
                .limit(2)
                .toArray();
            if (candidates.length !== 1) return 'missing';
            await attach(userId, candidates[0], 'auto');
            return 'linked';
        } catch (error) {
            console.warn('[prolific] automatic link failed:', error);
            return 'missing';
        }
    };

    /**
     * The participant typed their Prolific id. Rejects an id that is malformed, already used by another
     * account, or assigned to a different experiment (so nobody can end up in two conditions).
     */
    const linkManually = async (
        userId: string,
        experimentId: string,
        prolificId: unknown,
    ): Promise<{ ok: true } | { ok: false; status: number; message: string }> => {
        if (typeof prolificId !== 'string' || !PROLIFIC_ID_PATTERN.test(prolificId.trim())) {
            return { ok: false, status: 400, message: 'A Prolific ID has 24 letters and digits. Please check it.' };
        }
        const pid = prolificId.trim().toLowerCase();
        const other = await users().findOne({ 'prolific.pid': pid });
        if (other && String(other._id) !== userId) {
            return { ok: false, status: 409, message: 'This Prolific ID is already linked to another account.' };
        }
        const join = await joins().findOne({ pid });
        if (join && join.experimentId !== experimentId) {
            return { ok: false, status: 409, message: 'This Prolific ID belongs to a different study group.' };
        }
        if (!join) {
            await joins().insertOne({ pid, experimentId, createdAt: new Date(), lastSeenAt: new Date(), claimedBy: null });
        }
        await attach(userId, join || { pid }, 'manual');
        return { ok: true };
    };

    return { assignedExperiment, chooseExperiment, recordJoin, linkAfterRegistration, linkManually };
};

export const prolificService = createProlificService();
