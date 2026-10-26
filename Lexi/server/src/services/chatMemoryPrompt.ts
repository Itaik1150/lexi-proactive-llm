/**
 * What the chat model is told about the participant's past (docs/REVIEW.md M2, M3, D15).
 *
 * These are pure functions with NO knowledge of the experimental condition: every participant,
 * in every condition, gets the same kind of memory section built from the same dated notes
 * (written by the shared memory pipeline, logic-python/services/memory_pipeline.py).
 * The only extra section is the memory behind a notification, which exists only when the
 * conversation was opened from a notification that was based on a memory.
 */

export interface ConversationNote {
    summary?: string;
    conversation_date?: string; // YYYY-MM-DD (UTC date of the newest participant message)
    updated_at?: string;
}

export interface ProactiveContext {
    memory: string; // the event the notification was about
    transcript: string; // short excerpt of the conversation where it was shared
    sharedOn?: string; // YYYY-MM-DD, when the participant shared it
    when?: string; // when the event happens/happened, as the participant said it
    whenDate?: string; // YYYY-MM-DD, if known
}

const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const MONTHS = [
    'January',
    'February',
    'March',
    'April',
    'May',
    'June',
    'July',
    'August',
    'September',
    'October',
    'November',
    'December',
];

const parseDay = (iso?: string): Date | null => {
    const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
    if (!m) return null;
    const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3])));
    return Number.isNaN(d.getTime()) ? null : d;
};

/** "Monday 26 October 2026" from a Date (UTC) or an ISO day; '' if it is not a date. */
export const formatDay = (value: Date | string | undefined): string => {
    const d = value instanceof Date ? value : parseDay(value);
    if (!d || Number.isNaN(d.getTime())) return '';
    return `${WEEKDAYS[d.getUTCDay()]} ${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`;
};

export const todayLine = (now: Date): string => `Today is ${formatDay(now)}.`;

/**
 * The dated notes of all earlier conversations, oldest first. The note of the conversation that is
 * going on right now is left out (its content is in the transcript). Returns '' when there is nothing.
 */
export const buildMemorySection = (
    notes: Record<string, ConversationNote> | undefined | null,
    currentConversationId?: string,
): string => {
    const items = Object.entries(notes || {})
        .filter(([id, n]) => id !== currentConversationId && n && String(n.summary || '').trim())
        .map(([, n]) => ({
            day: n.conversation_date || '',
            at: n.updated_at || '',
            text: String(n.summary).trim(),
        }))
        .sort((a, b) => (a.day + a.at).localeCompare(b.day + b.at));
    if (!items.length) return '';

    const lines = items.map((n) => `- ${formatDay(n.day) || 'Earlier'}: ${n.text}`);
    return (
        `\n\n--- What you remember from earlier conversations (oldest first) ---\n` +
        lines.join('\n') +
        `\n--- End of memory ---\n\n` +
        `Use this naturally to keep continuity, and use the dates to talk about when things happened ("yesterday", "last week"). ` +
        `Mention something only if it appears above; never invent or guess past events. ` +
        `Do not say that you read notes, summaries or memory.`
    );
};

/** The memory behind a notification, for a conversation that was opened from that notification. */
export const buildProactiveSection = (ctx: ProactiveContext | null | undefined): string => {
    if (!ctx || !ctx.memory) return '';
    const shared = formatDay(ctx.sharedOn);
    const whenDay = formatDay(ctx.whenDate);
    const timing = [
        shared ? `The participant told you this on ${shared}.` : '',
        ctx.when ? `About when it happens or happened, they said: "${ctx.when}"${whenDay ? ` (${whenDay})` : ''}.` : '',
    ]
        .filter(Boolean)
        .join(' ');
    return (
        `\n\n--- Why you reached out (for your internal reference only) ---\n` +
        `You started this conversation with a notification about something the participant shared earlier:\n` +
        `"${ctx.memory}"\n` +
        (timing ? `${timing}\n` : '') +
        `\nHere is an excerpt from the conversation where that came up:\n${ctx.transcript}\n` +
        `---\n\n` +
        `Let this inform you the way an attentive person would when following up on something that mattered. ` +
        `Do not announce that you looked anything up.\n` +
        `--- End ---`
    );
};

/** The complete system prompt: persona, today's date, dated memory, and (if any) the notification's memory. */
export const composeSystemPrompt = (args: {
    persona: string;
    now: Date;
    notes?: Record<string, ConversationNote> | null;
    currentConversationId?: string;
    proactive?: ProactiveContext | null;
}): string =>
    `${args.persona}\n\n${todayLine(args.now)}` +
    buildMemorySection(args.notes, args.currentConversationId) +
    buildProactiveSection(args.proactive);
