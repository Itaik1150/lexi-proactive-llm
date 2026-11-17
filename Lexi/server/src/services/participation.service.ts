import mongoose from 'mongoose';
import { studyDay } from './study.service';

/**
 * Who is really taking part (docs/REVIEW.md P5): one row per participant of an experiment, for the
 * researcher's dashboard. Used to decide who has completed the study on Prolific.
 *
 * A conversation counts as "real" when the participant wrote at least one message in it (the
 * conversation a notification opens exists before the participant replies). A SESSION, the unit of the
 * study's participation requirement (protocol: at least 3 sessions in each week), is a conversation in
 * which the participant wrote at least MIN_SESSION_MESSAGES messages.
 */

export const MIN_SESSION_MESSAGES = 3;
export const REQUIRED_SESSIONS_PER_WEEK = 3;

export interface ParticipationRow {
    username: string;
    prolificId: string | null;
    linkedBy: string | null;
    registeredAt: Date | string | undefined;
    day: number;
    conversations: number; // real conversations in total
    conversationsWeek1: number; // study days 1-7
    conversationsWeek2: number; // study days 8-14
    sessionsWeek1: number; // conversations with at least MIN_SESSION_MESSAGES participant messages, days 1-7
    sessionsWeek2: number; // the same, days 8-14
    requirementMet: boolean; // at least REQUIRED_SESSIONS_PER_WEEK sessions in each of the two weeks
    finished: number; // closed with the Finish button
    surveysAfterConversation: number; // post-conversation survey answered
    lastActive: Date | string | null;
    notificationsSent: number;
    notificationsTapped: number;
    notificationsReplied: number;
    baselineAnswered: boolean;
    endSurveyDone: boolean;
    onboardingCodeConfirmed: boolean;
}

const DAY_MS = 24 * 60 * 60 * 1000;

export const summarise = (user: any, conversations: any[], logs: any[], now: Date): ParticipationRow => {
    const start = user.createdAt ? new Date(user.createdAt).getTime() : now.getTime();
    const real = conversations.filter((c) => Number(c.messagesNumber) > 0);
    const dayOf = (c: any) => Math.floor((new Date(c.createdAt).getTime() - start) / DAY_MS) + 1;
    const last = real.reduce(
        (latest: number, c) => Math.max(latest, new Date(c.lastMessageDate || c.createdAt).getTime()),
        0,
    );
    const sent = logs.filter((l) => l.status === 'sent');
    const sessions = real.filter((c) => Number(c.messagesNumber) >= MIN_SESSION_MESSAGES);
    const sessionsWeek1 = sessions.filter((c) => dayOf(c) <= 7).length;
    const sessionsWeek2 = sessions.filter((c) => dayOf(c) >= 8 && dayOf(c) <= 14).length;
    return {
        username: user.username,
        prolificId: user.prolific?.pid || null,
        linkedBy: user.prolific?.linkedBy || null,
        registeredAt: user.createdAt,
        day: studyDay(user.createdAt, now),
        conversations: real.length,
        conversationsWeek1: real.filter((c) => dayOf(c) <= 7).length,
        conversationsWeek2: real.filter((c) => dayOf(c) >= 8 && dayOf(c) <= 14).length,
        sessionsWeek1,
        sessionsWeek2,
        requirementMet: sessionsWeek1 >= REQUIRED_SESSIONS_PER_WEEK && sessionsWeek2 >= REQUIRED_SESSIONS_PER_WEEK,
        finished: real.filter((c) => c.isFinished).length,
        surveysAfterConversation: real.filter((c) => c.postConversation && Object.keys(c.postConversation).length > 0)
            .length,
        lastActive: last ? new Date(last) : null,
        notificationsSent: sent.length,
        notificationsTapped: sent.filter((l) => l.tapped_at).length,
        notificationsReplied: sent.filter((l) => l.first_reply_at).length,
        baselineAnswered: !!user.registrationAnswers && Object.keys(user.registrationAnswers).length > 0,
        endSurveyDone: !!user.study?.endSurvey?.submittedAt,
        onboardingCodeConfirmed: !!user.study?.onboardingCodeAckAt,
    };
};

export const getParticipation = async (experimentId: string, now: Date = new Date()): Promise<ParticipationRow[]> => {
    const db = mongoose.connection.db;
    const users = await db
        .collection('users')
        .find(
            { experimentId, isAdmin: { $ne: true } },
            { projection: { username: 1, createdAt: 1, prolific: 1, registrationAnswers: 1, study: 1 } },
        )
        .toArray();
    const ids = users.map((u) => String(u._id));
    const [conversations, logs] = await Promise.all([
        db
            .collection('metadata_conversations')
            .find(
                { userId: { $in: ids } },
                {
                    projection: {
                        userId: 1,
                        createdAt: 1,
                        lastMessageDate: 1,
                        isFinished: 1,
                        messagesNumber: 1,
                        postConversation: 1,
                    },
                },
            )
            .toArray(),
        db
            .collection('proactive_logs')
            .find({ user_id: { $in: ids } }, { projection: { user_id: 1, status: 1, tapped_at: 1, first_reply_at: 1 } })
            .toArray(),
    ]);
    return users
        .map((u) =>
            summarise(
                u,
                conversations.filter((c) => c.userId === String(u._id)),
                logs.filter((l) => l.user_id === String(u._id)),
                now,
            ),
        )
        .sort((a, b) => String(a.registeredAt).localeCompare(String(b.registeredAt)));
};
