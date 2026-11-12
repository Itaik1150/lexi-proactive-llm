/**
 * The participant's path through the study (docs/REVIEW.md P2, P5): baseline at registration,
 * the onboarding completion code, the end-of-study survey, the final completion code.
 *
 * The rules are pure functions so they can be tested without a database:
 *   - day 1 is the day of registration;
 *   - the onboarding code is shown to a participant who is linked to a Prolific id, until they
 *     confirm that they submitted it;
 *   - the end survey opens on the last day of the study (settings.durationDays, default 14);
 *   - the final code is shown only after the end survey was submitted (or, if the experiment has
 *     no end survey, once the study period is over).
 * Completion codes never leave the server before the participant is entitled to them.
 */

export const DEFAULT_DURATION_DAYS = 14;
const DAY_MS = 24 * 60 * 60 * 1000;

/** Fields of the registration request that are stored as the participant's own columns. */
export const FIXED_REGISTRATION_FIELDS = [
    'username',
    'age',
    'gender',
    'biologicalSex',
    'maritalStatus',
    'childrenNumber',
    'nativeEnglishSpeaker',
];

export interface StudySettings {
    durationDays?: number;
    endSurveyForm?: string;
    onboardingCompletionCode?: string;
    finalCompletionCode?: string;
}

export interface StudyStatus {
    day: number;
    durationDays: number;
    prolificLinked: boolean;
    onboardingCode: string | null;
    endSurveyFormId: string | null;
    endSurveyDue: boolean;
    endSurveyDone: boolean;
    finalCode: string | null;
}

type StudyUser = {
    createdAt?: Date | string;
    prolific?: { pid?: string };
    study?: { onboardingCodeAckAt?: Date; endSurvey?: { submittedAt?: Date } };
};

/** 1 on the day of registration, 2 the next day, and so on. */
export const studyDay = (createdAt: Date | string | undefined, now: Date): number => {
    const start = createdAt ? new Date(createdAt).getTime() : now.getTime();
    return Math.max(1, Math.floor((now.getTime() - start) / DAY_MS) + 1);
};

export const studyStatus = (user: StudyUser, settings: StudySettings | undefined, now: Date): StudyStatus => {
    const s = settings || {};
    const durationDays = Number(s.durationDays) > 0 ? Number(s.durationDays) : DEFAULT_DURATION_DAYS;
    const day = studyDay(user.createdAt, now);
    const prolificLinked = !!user.prolific?.pid;
    const endSurveyFormId = s.endSurveyForm || null;
    const endSurveyDone = !!user.study?.endSurvey?.submittedAt;
    const periodOver = day >= durationDays;
    const entitledToFinal = endSurveyFormId ? endSurveyDone : day > durationDays;

    return {
        day,
        durationDays,
        prolificLinked,
        onboardingCode:
            prolificLinked && s.onboardingCompletionCode && !user.study?.onboardingCodeAckAt
                ? s.onboardingCompletionCode
                : null,
        endSurveyFormId,
        endSurveyDue: !!endSurveyFormId && periodOver && !endSurveyDone,
        endSurveyDone,
        finalCode: prolificLinked && entitledToFinal && s.finalCompletionCode ? s.finalCompletionCode : null,
    };
};

/**
 * The answers to the experiment's own registration questionnaire (the baseline): everything in the
 * registration request that is not one of the fixed columns. Keys must look like form field keys,
 * and values must be plain (text, number, boolean), so nothing unexpected is stored.
 */
export const baselineAnswers = (userInfo: Record<string, unknown> | undefined): Record<string, string | number | boolean> => {
    const answers: Record<string, string | number | boolean> = {};
    for (const [key, value] of Object.entries(userInfo || {})) {
        if (FIXED_REGISTRATION_FIELDS.includes(key)) continue;
        if (!/^[A-Za-z0-9_-]{1,64}$/.test(key)) continue;
        if (typeof value === 'string' ? value.length <= 2000 : typeof value === 'number' || typeof value === 'boolean') {
            answers[key] = value as string | number | boolean;
        }
    }
    return answers;
};

/** Same cleaning for the end survey. */
export const cleanAnswers = baselineAnswers;
