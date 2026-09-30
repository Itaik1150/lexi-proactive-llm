import mongoose from 'mongoose';

export interface ABAgents {
    agentA: string;
    distA: number;
    agentB: string;
    distB: number;
}

export interface DisplaySettings {
    welcomeContent: string;
    welcomeHeader: string;
}

export interface ExperimentForms {
    registration: string;
    preConversation: string;
    postConversation: string;
}

export interface ProactiveHeuristicsSettings {
    temporal: boolean;
    affective: boolean;
    behaviouralGap: boolean;
}

/** Probability weights for heuristic selection (must sum to 100). */
export interface HeuristicWeights {
    affective:      number;
    temporal:       number;
    behaviouralGap: number;
    generic:        number;
    reactive?:      number; // 100 - sum(others); managed by UI, not entered by researcher
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

/** A single "HH:MM"–"HH:MM" random-fire window. */
export interface RandomWindow {
    start: string; // "HH:MM"
    end:   string; // "HH:MM"
}

/** Notification schedule: which days are allowed and when to fire each day. */
export interface ScheduleSettings {
    allowedDays:   number[];       // 0=Sun .. 6=Sat; multiple non-consecutive ranges allowed
    mode:          'exact' | 'random';
    fireTimes:     string[];       // 1–3 "HH:MM" fixed times, used when mode === 'exact'
    randomWindows: RandomWindow[]; // used when mode === 'random' — fires once at a random minute per window
}

export interface ExperimentFeatures {
    userAnnotation: boolean;
    streamMessage: boolean;
    proactiveSettings?: {
        enabled: boolean;
        frequency: number; // in minutes (legacy; superseded by `schedule`)
        heuristics?:       ProactiveHeuristicsSettings; // legacy boolean flags (backward compat)
        heuristicWeights?: HeuristicWeights;            // Task 3.1 — probability-based selection
        heuristicPrompts?: HeuristicPrompts;            // Task 4.2 — per-heuristic prompt editor
        schedule?:         ScheduleSettings;            // Task 4.3 — days & hours scheduling
        llmModel?: string; // e.g. "gpt-4o" | "claude-3-5-sonnet-20241022"
        defaultLanguage?: string;        // experiment-level language fallback ('he' | 'en')
        maxDailyNotifications?: number;  // per participant per day; 0 or unset = no limit
    };
}

export interface IExperimentLean {
    _id: mongoose.Types.ObjectId;
    title: string;
}

export interface IExperiment {
    _id: mongoose.Types.ObjectId;
    agentsMode: string;
    activeAgent: string;
    abAgents: ABAgents;
    createdAt: Date;
    timestamp: number;
    displaySettings: DisplaySettings;
    isActive: boolean;
    title: string;
    description: string;
    numberOfParticipants: number;
    experimentForms: ExperimentForms;
    maxMessages: number;
    maxConversations: number;
    maxParticipants: number;
    totalSessions: number;
    openSessions: number;
    experimentFeatures: ExperimentFeatures;
}
