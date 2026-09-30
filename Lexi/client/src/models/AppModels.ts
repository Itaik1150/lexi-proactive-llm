import { QuestionType, QuestionTypeProps } from '../components/questions/Question';

export interface MessageType {
    _id?: string;
    role: 'system' | 'user' | 'assistant';
    content: string;
    userAnnotation?: UserAnnotation;
    isProactiveOpener?: boolean;
}

export type UserAnnotation = 1 | 0 | -1;

export interface ConversationType {
    conversationId: string;
    content: string;
    role: string;
    createdAt: Date;
    timestamp: number;
    messageNumber: number;
}

export interface MetadataConversationType {
    _id: string;
    experimentId: string;
    messagesNumber: number;
    createdAt: Date;
    timestamp: number;
    lastMessageDate: Date;
    lastMessageTimestamp: number;
    conversationNumber: number;
    agent: AgentType;
    userId: string;
}

export interface UserType {
    _id: string;
    experimentId: string;
    username: string;
    age: number;
    gender: 'male' | 'female' | 'other';
    biologicalSex: string;
    maritalStatus: string;
    childrenNumber: number;
    nativeEnglishSpeaker: boolean;
    createdAt: Date;
    timestamp: number;
    isAdmin: boolean;
    password?: string;
    numberOfConversations: number;
    agent: AgentType;
    fcmToken?: string;
}

export interface AgentType {
    _id: string;
    title: string;
    summary: string;
    systemStarterPrompt: string;
    beforeUserSentencePrompt: string;
    afterUserSentencePrompt: string;
    firstChatSentence: string;
    model: string;
    temperature: number;
    maxTokens: number;
    topP: number;
    frequencyPenalty: number;
    presencePenalty: number;
    stopSequences: { value: string; id: string }[];
    createdAt?: Date;
    timestamp?: number;
}

export interface AgentLeanType {
    _id: string;
    title: string;
}

export type AbAgentsType = {
    agentA: string;
    distA: number;
    agentB: string;
    distB: number;
};

export const AgentsModes = {
    SINGLE: 'Single',
    AB: 'A/B',
} as const;

export interface DisplaySettings {
    welcomeContent: string;
    welcomeHeader: string;
}

export interface ExperimentType {
    _id: string;
    agentsMode: string;
    activeAgent: string;
    abAgents: AbAgentsType;
    createdAt: Date;
    timestamp: number;
    welcomeText: string;
    welcomeCSS: object;
    displaySettings: DisplaySettings;
    isActive: boolean;
    title: string;
    description: string;
    numberOfParticipants: number;
    maxMessages: number | undefined;
    maxConversations: number | undefined;
    maxParticipants: number | undefined;
    totalSessions: number;
    openSessions: number;
    experimentFeatures: ExperimentFeatures;
}

export interface ExperimentLeanType {
    _id: string;
    title: string;
}

export interface ProactiveHeuristicsSettings {
    temporal: boolean;
    affective: boolean;
    behaviouralGap: boolean;
}

/** Probability weights for heuristic selection (active weights must sum to 100). */
export interface HeuristicWeights {
    affective:      number;
    temporal:       number;
    behaviouralGap: number;
    generic:        number;
    reactive?:      number;
}

/** A memory/message prompt pair for one heuristic. */
export interface HeuristicPromptPair {
    memoryPrompt?:  string;
    messagePrompt?: string;
}

/** Per-heuristic LLM prompts set by the researcher in the dashboard. */
export interface HeuristicPrompts {
    affective?:      HeuristicPromptPair;
    temporal?:       HeuristicPromptPair;
    behaviouralGap?: HeuristicPromptPair;
    generic?:        HeuristicPromptPair;
}

/** A single "HH:MM"–"HH:MM" random-fire window with an optional count of notifications. */
export interface RandomWindow {
    start: string;
    end:   string;
    count: number; // Task 6.4: how many notifications to fire within this window (default 1)
}

/** Notification schedule: which days are allowed and when to fire each day. */
export interface ScheduleSettings {
    allowedDays:   number[];                    // 0=Sun .. 6=Sat
    mode:          'exact' | 'random' | 'ai_agent';
    fireTimes:     string[];                    // unlimited "HH:MM" strings, used when mode === 'exact'
    randomWindows: RandomWindow[];              // used when mode === 'random' or 'ai_agent' (stores the allowed window + count)
}

export interface ExperimentFeatures {
    userAnnotation: boolean;
    streamMessage: boolean;
    proactiveSettings?: {
        enabled: boolean;
        frequency: number;
        heuristics?:           ProactiveHeuristicsSettings; // legacy boolean flags (backward compat)
        heuristicWeights?:     HeuristicWeights;            // Task 3.1 — probability-based selection
        heuristicPrompts?:     HeuristicPrompts;            // Task 4.2 — per-heuristic prompt editor
        schedule?:             ScheduleSettings;            // Task 4.3 — days & hours scheduling
        llmModel?:             string;
        defaultLanguage?:      string;                      // Task 6.3 — experiment-level language fallback
    };
}

export interface NewUserInfoType {
    username: string;
    age: number | string;
    gender: string;
    biologicalSex: string;
    maritalStatus: string;
    childrenNumber: number;
    nativeEnglishSpeaker: string | boolean;
}

export interface ExperimentContentType {
    content: DisplaySettings;
    isActive: boolean;
}

export interface FormType {
    name: string;
    title: string;
    instructions: string;
    questions: Array<{ type: QuestionType; props: QuestionTypeProps }>;
}
