import React, { useState, useEffect } from 'react';
import {
    Dialog,
    DialogTitle,
    DialogContent,
    DialogActions,
    Button,
    Switch,
    TextField,
    Typography,
    Box,
    IconButton,
    Tooltip,
    Divider,
    MenuItem,
    Select,
    FormControl,
    InputLabel,
    Collapse,
    Chip,
    Alert,
} from '@mui/material';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import { SnackbarStatus, useSnackbar } from '@contexts/SnackbarProvider';
import { updateExperiment } from '@DAL/server-requests/experiments';
import {
    ExperimentType,
    HeuristicWeights,
    HeuristicPrompts,
    ScheduleSettings,
} from '@models/AppModels';

// ── Supported LLM models ───────────────────────────────────────────────────────
const LLM_MODEL_OPTIONS = [
    { value: 'gpt-4o',                       label: 'GPT-4o (OpenAI)' },
    { value: 'gpt-4o-mini',                  label: 'GPT-4o Mini (OpenAI — cheaper)' },
    { value: 'claude-3-5-sonnet-20241022',   label: 'Claude 3.5 Sonnet (Anthropic)' },
    { value: 'claude-3-opus-20240229',       label: 'Claude 3 Opus (Anthropic — most capable)' },
];

// ── Schedule defaults & day labels ──────────────────────────────────────────────
const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const DEFAULT_SCHEDULE: ScheduleSettings = {
    allowedDays: [0, 1, 2, 3, 4, 5, 6],
    mode: 'exact',
    fireTimes: ['13:45', '17:30', '21:15'],
    randomWindows: [{ start: '12:00', end: '14:00', count: 1 }],
};

// ── Heuristic metadata ─────────────────────────────────────────────────────────
type HeuristicKey = 'affective' | 'temporal' | 'behaviouralGap' | 'generic';

interface HeuristicMeta {
    label: string;
    description: string;
    hasMemoryPrompt: boolean;
    defaultMemoryPrompt: string;
    defaultMessagePrompt: string;
}

const HEURISTICS: Record<HeuristicKey, HeuristicMeta> = {
    affective: {
        label: 'Affective',
        description:
            'Scans the user\'s recent conversations for emotional content (stress, sadness, joy). ' +
            'When emotional expressions are found, sends a warm, personalised check-in referencing what the user shared.',
        hasMemoryPrompt: true,
        defaultMemoryPrompt:
            'You analyze conversation messages for deep emotional content.\n' +
            'Extract emotional expressions, personal struggles, vulnerable shares, ' +
            'and meaningful life events shared by the user.\n\n' +
            'Exclude casual mentions, surface-level topics, or purely factual statements.',
        defaultMessagePrompt:
            'You are an empathetic assistant that encourages emotional sharing.\n' +
            'Generate a warm, personal emotional check-in (max 15 words) ' +
            'that directly references the specific emotional memory the user shared.\n' +
            'Acknowledge their feelings without being dramatic or clinical.\n' +
            'Invite them to share how they are feeling about it now.\n' +
            'You MAY use the user\'s name once if it feels natural.',
    },
    temporal: {
        label: 'Temporal',
        description:
            'Detects when the user has mentioned an upcoming event or plan. ' +
            'Sends a timely message asking how they are preparing — or, if the event just passed, how it went.',
        hasMemoryPrompt: true,
        defaultMemoryPrompt:
            'You analyze conversation messages for mentions of upcoming events, ' +
            'plans, appointments, or activities.',
        defaultMessagePrompt:
            'You are a friendly assistant. Generate a warm, timely message ' +
            '(max 15 words) about the user\'s upcoming event or plan.\n' +
            'If the event is still ahead: ask if they are ready or excited.\n' +
            'If the event just passed: ask how it went.\n' +
            'Never confuse past and future timing. ' +
            'You MAY use the user\'s name once.',
    },
    behaviouralGap: {
        label: 'Behavioural Gap',
        description:
            'Notices when the user stated an intention (e.g. "I\'ll go to the gym tomorrow") but has not mentioned it since. ' +
            'Sends a gentle follow-up to check whether they followed through.',
        hasMemoryPrompt: true,
        defaultMemoryPrompt:
            'You analyze conversation messages from a user.\n' +
            'Extract only EXPLICIT, concrete plans or commitments the user expressed.\n\n' +
            'Valid examples:\n' +
            '  - \'I\'ll go to the gym tomorrow\'\n' +
            '  - \'I\'m starting that online course next week\'\n' +
            '  - \'I plan to call my mom tonight\'\n\n' +
            'Invalid (too vague \u2014 do NOT include):\n' +
            '  - \'I want to be healthier\'\n' +
            '  - \'Maybe I\'ll try that someday\'\n' +
            '  - \'I should exercise more\'',
        defaultMessagePrompt:
            'You are a supportive, caring assistant.\n' +
            'Generate a gentle, friendly follow-up message (max 15 words) ' +
            'asking whether the user followed through on their stated plan.\n' +
            'Do NOT assume success or failure \u2014 stay curious and supportive.\n' +
            'You MAY use the user\'s name once.',
    },
    generic: {
        label: 'Generic',
        description:
            'Sends a simple, friendly invitation to chat — no emotional framing, no specific topic. ' +
            'Used as a control condition or baseline.',
        hasMemoryPrompt: false,
        defaultMemoryPrompt: '',
        defaultMessagePrompt:
            'You are a standard assistant. Generate a completely neutral, friendly ' +
            'invitation to chat with zero emotional weight and no specific ' +
            'topics (max 15 words). You MAY use the user\'s name once if it feels natural.',
    },
};

const HEURISTIC_KEYS: HeuristicKey[] = ['generic', 'temporal', 'behaviouralGap', 'affective'];

// ── Component state types ──────────────────────────────────────────────────────
interface HeuristicRowState {
    enabled:       boolean;
    weight:        number;
    memoryPrompt:  string;
    messagePrompt: string;
    promptsOpen:   boolean; // local UI only, not persisted
}

type HeuristicConfigs = Record<HeuristicKey, HeuristicRowState>;

const buildDefaultConfigs = (): HeuristicConfigs =>
    HEURISTIC_KEYS.reduce((acc, key) => {
        acc[key] = {
            enabled:       false,
            weight:        0,
            memoryPrompt:  HEURISTICS[key].defaultMemoryPrompt,
            messagePrompt: HEURISTICS[key].defaultMessagePrompt,
            promptsOpen:   false,
        };
        return acc;
    }, {} as HeuristicConfigs);

const initConfigs = (
    weights?: HeuristicWeights,
    prompts?: HeuristicPrompts,
): HeuristicConfigs =>
    HEURISTIC_KEYS.reduce((acc, key) => {
        const w = (weights as any)?.[key] ?? 0;
        const p = (prompts as any)?.[key] ?? {};
        acc[key] = {
            enabled:       w > 0,
            weight:        w,
            memoryPrompt:  p.memoryPrompt  || HEURISTICS[key].defaultMemoryPrompt,
            messagePrompt: p.messagePrompt || HEURISTICS[key].defaultMessagePrompt,
            promptsOpen:   false,
        };
        return acc;
    }, {} as HeuristicConfigs);

// ── Props ──────────────────────────────────────────────────────────────────────
interface ProactiveSettingsModalProps {
    open:       boolean;
    onClose:    () => void;
    experiment: ExperimentType;
    onUpdate?:  (updatedExperiment: ExperimentType) => void;
}

// ── Component ──────────────────────────────────────────────────────────────────
export const ProactiveSettingsModal: React.FC<ProactiveSettingsModalProps> = ({
    open,
    onClose,
    experiment,
    onUpdate,
}) => {
    const [proactiveEnabled,      setProactiveEnabled]      = useState(false);
    const [frequency,             setFrequency]             = useState(30);
    const [llmModel,              setLlmModel]              = useState('gpt-4o');
    const [configs,               setConfigs]               = useState<HeuristicConfigs>(buildDefaultConfigs);
    const [schedule,              setSchedule]              = useState<ScheduleSettings>(DEFAULT_SCHEDULE);
    const [isLoading,             setIsLoading]             = useState(false);

    const serverBase = process.env.REACT_APP_API_URL || 'https://lexi-server-1rx9.onrender.com';
    const deepLink   = `${serverBase}/join/${experiment._id}`;
    const { openSnackbar } = useSnackbar();

    // ── Sync state when experiment prop changes ────────────────────────────────
    useEffect(() => {
        const ps = experiment.experimentFeatures?.proactiveSettings;
        if (ps) {
            setProactiveEnabled(ps.enabled);
            setFrequency(ps.frequency ?? 30);
            setLlmModel(ps.llmModel ?? 'gpt-4o');
            setConfigs(initConfigs(ps.heuristicWeights, ps.heuristicPrompts));
            setSchedule({
                allowedDays:   ps.schedule?.allowedDays?.length   ? ps.schedule.allowedDays   : DEFAULT_SCHEDULE.allowedDays,
                mode:          ps.schedule?.mode                  ?? DEFAULT_SCHEDULE.mode,
                fireTimes:     ps.schedule?.fireTimes?.length     ? ps.schedule.fireTimes     : DEFAULT_SCHEDULE.fireTimes,
                randomWindows: ps.schedule?.randomWindows?.length ? ps.schedule.randomWindows : DEFAULT_SCHEDULE.randomWindows,
            });
        } else {
            setProactiveEnabled(false);
            setFrequency(30);
            setLlmModel('gpt-4o');
            setConfigs(buildDefaultConfigs());
            setSchedule(DEFAULT_SCHEDULE);
        }
    }, [experiment]);

    // ── Derived state ──────────────────────────────────────────────────────────
    const totalWeight = HEURISTIC_KEYS.reduce(
        (sum, k) => sum + (configs[k].enabled ? (configs[k].weight || 0) : 0),
        0,
    );
    const anyEnabled   = HEURISTIC_KEYS.some(k => configs[k].enabled);
    const isWeightValid = !anyEnabled || totalWeight === 100;
    const isScheduleValid =
        schedule.allowedDays.length > 0 &&
        (schedule.mode === 'exact' ? schedule.fireTimes.length > 0 : schedule.randomWindows.length > 0);

    // ── Row handlers ───────────────────────────────────────────────────────────

    /** Redistribute 100% equally among currently-enabled heuristics. */
    const redistributeWeights = (draft: HeuristicConfigs): HeuristicConfigs => {
        const enabledKeys = HEURISTIC_KEYS.filter(k => draft[k].enabled);
        if (enabledKeys.length === 0) return draft;
        const equalShare = Math.floor(100 / enabledKeys.length);
        const remainder  = 100 - equalShare * enabledKeys.length;
        const next = { ...draft };
        enabledKeys.forEach((k, i) => {
            next[k] = { ...next[k], weight: equalShare + (i === 0 ? remainder : 0) };
        });
        return next;
    };

    const toggleHeuristic = (key: HeuristicKey) => {
        setConfigs(prev => {
            const toggled: HeuristicConfigs = {
                ...prev,
                [key]: {
                    ...prev[key],
                    enabled: !prev[key].enabled,
                    weight:  prev[key].enabled ? 0 : prev[key].weight,
                },
            };
            return redistributeWeights(toggled);
        });
    };

    const setWeight = (key: HeuristicKey, value: number) => {
        setConfigs(prev => ({
            ...prev,
            [key]: { ...prev[key], weight: Math.max(0, Math.min(100, value)) },
        }));
    };

    const setPrompt = (key: HeuristicKey, field: 'memoryPrompt' | 'messagePrompt', value: string) => {
        setConfigs(prev => ({
            ...prev,
            [key]: { ...prev[key], [field]: value },
        }));
    };

    const togglePromptsOpen = (key: HeuristicKey) => {
        setConfigs(prev => ({
            ...prev,
            [key]: { ...prev[key], promptsOpen: !prev[key].promptsOpen },
        }));
    };

    // ── Schedule handlers ────────────────────────────────────────────────────────
    const toggleDay = (day: number) => {
        setSchedule(prev => {
            const has = prev.allowedDays.includes(day);
            const allowedDays = has
                ? prev.allowedDays.filter(d => d !== day)
                : [...prev.allowedDays, day].sort();
            return { ...prev, allowedDays };
        });
    };

    const setScheduleMode = (mode: 'exact' | 'random' | 'ai_agent') => {
        setSchedule(prev => ({ ...prev, mode }));
    };

    const setFireTime = (index: number, value: string) => {
        setSchedule(prev => {
            const fireTimes = [...prev.fireTimes];
            fireTimes[index] = value;
            return { ...prev, fireTimes };
        });
    };

    const addFireTime = () => {
        // Task 6.4: no cap on fire times
        setSchedule(prev => ({ ...prev, fireTimes: [...prev.fireTimes, '12:00'] }));
    };

    const removeFireTime = (index: number) => {
        setSchedule(prev => ({
            ...prev,
            fireTimes: prev.fireTimes.filter((_, i) => i !== index),
        }));
    };

    // Task 6.4: extend to support count mutations alongside start/end
    const setRandomWindow = (field: 'start' | 'end' | 'count', value: string | number) => {
        setSchedule(prev => {
            const windows = prev.randomWindows.length
                ? [...prev.randomWindows]
                : [{ start: '12:00', end: '14:00', count: 1 }];
            windows[0] = { ...windows[0], [field]: value };
            return { ...prev, randomWindows: windows };
        });
    };

    // ── Save ───────────────────────────────────────────────────────────────────
    const handleSave = async () => {
        if (!isWeightValid) {
            openSnackbar(
                `Active heuristic weights must sum to 100% (current: ${totalWeight}%)`,
                SnackbarStatus.ERROR,
            );
            return;
        }
        if (!isScheduleValid) {
            openSnackbar(
                'Select at least one allowed day and at least one fire time / random window',
                SnackbarStatus.ERROR,
            );
            return;
        }
        setIsLoading(true);
        try {
            // Build heuristicWeights (reactive = remainder so Python reads correctly)
            const heuristicWeights: HeuristicWeights = {
                affective:      configs.affective.enabled      ? configs.affective.weight      : 0,
                temporal:       configs.temporal.enabled       ? configs.temporal.weight       : 0,
                behaviouralGap: configs.behaviouralGap.enabled ? configs.behaviouralGap.weight : 0,
                generic:        configs.generic.enabled        ? configs.generic.weight        : 0,
                reactive:       Math.max(0, 100 - totalWeight),
            };

            // Build heuristicPrompts (only save if researcher customised them)
            const heuristicPrompts: HeuristicPrompts = HEURISTIC_KEYS.reduce((acc, key) => {
                const c = configs[key];
                const defaults = HEURISTICS[key];
                // Only write to DB if the prompt differs from the default
                const memDiff = c.memoryPrompt  !== defaults.defaultMemoryPrompt;
                const msgDiff = c.messagePrompt !== defaults.defaultMessagePrompt;
                if (memDiff || msgDiff) {
                    (acc as any)[key] = {
                        memoryPrompt:  memDiff ? c.memoryPrompt  : '',
                        messagePrompt: msgDiff ? c.messagePrompt : '',
                    };
                }
                return acc;
            }, {} as HeuristicPrompts);

            const updatedExperiment: ExperimentType = {
                ...experiment,
                experimentFeatures: {
                    userAnnotation: experiment.experimentFeatures?.userAnnotation || false,
                    streamMessage:  experiment.experimentFeatures?.streamMessage  || false,
                    proactiveSettings: {
                        enabled:               proactiveEnabled,
                        frequency,
                        heuristics:            experiment.experimentFeatures?.proactiveSettings?.heuristics, // keep legacy
                        heuristicWeights,
                        heuristicPrompts,
                        schedule,
                        llmModel,
                    },
                },
            };

            await updateExperiment(updatedExperiment);
            if (onUpdate) onUpdate(updatedExperiment);
            openSnackbar('Proactive settings saved successfully', SnackbarStatus.SUCCESS);
            onClose();
        } catch (error) {
            console.error('Failed to save proactive settings:', error);
            openSnackbar('Failed to save settings', SnackbarStatus.ERROR);
        } finally {
            setIsLoading(false);
        }
    };

    const handleCopyLink = () => {
        navigator.clipboard.writeText(deepLink);
        openSnackbar('Link copied to clipboard', SnackbarStatus.SUCCESS);
    };

    // ── Render ─────────────────────────────────────────────────────────────────
    return (
        <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
            <DialogTitle>
                <Box display="flex" alignItems="center" gap={1}>
                    <NotificationsActiveIcon fontSize="medium" />
                    <Typography variant="h6" fontWeight={700} component="span">
                        Proactive Settings
                    </Typography>
                </Box>
            </DialogTitle>

            <DialogContent>
                <Box display="flex" flexDirection="column" gap={3} pt={1}>

                    {/* ── Enable toggle ──────────────────────────────────────── */}
                    <Box display="flex" alignItems="center" justifyContent="space-between">
                        <Typography variant="subtitle1" fontWeight={600}>
                            Enable Proactive Mode
                        </Typography>
                        <Switch
                            checked={proactiveEnabled}
                            onChange={e => setProactiveEnabled(e.target.checked)}
                            color="primary"
                        />
                    </Box>

                    {/* ── Schedule: Days & Hours ──────────────────────────────── */}
                    <Box>
                        <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                            Notification Schedule
                        </Typography>

                        {/* Allowed days */}
                        <Typography variant="caption" color="textSecondary" sx={{ mb: 0.5, display: 'block' }}>
                            Allowed days
                        </Typography>
                        <Box display="flex" gap={0.5} flexWrap="wrap" mb={2}>
                            {DAY_LABELS.map((label, day) => (
                                <Chip
                                    key={day}
                                    label={label}
                                    clickable={proactiveEnabled}
                                    onClick={() => proactiveEnabled && toggleDay(day)}
                                    color={schedule.allowedDays.includes(day) ? 'primary' : 'default'}
                                    variant={schedule.allowedDays.includes(day) ? 'filled' : 'outlined'}
                                    size="small"
                                    sx={{ opacity: proactiveEnabled ? 1 : 0.5 }}
                                />
                            ))}
                        </Box>

                        {/* Exact vs random mode */}
                        <Typography variant="caption" color="textSecondary" sx={{ mb: 0.5, display: 'block' }}>
                            Notification times
                        </Typography>
                        <Box display="flex" gap={1} mb={1.5} flexWrap="wrap">
                            <Chip
                                label="Exact times"
                                clickable={proactiveEnabled}
                                onClick={() => proactiveEnabled && setScheduleMode('exact')}
                                color={schedule.mode === 'exact' ? 'primary' : 'default'}
                                variant={schedule.mode === 'exact' ? 'filled' : 'outlined'}
                                size="small"
                            />
                            <Chip
                                label="Random window"
                                clickable={proactiveEnabled}
                                onClick={() => proactiveEnabled && setScheduleMode('random')}
                                color={schedule.mode === 'random' ? 'primary' : 'default'}
                                variant={schedule.mode === 'random' ? 'filled' : 'outlined'}
                                size="small"
                            />
                            <Chip
                                label="✨ Let Agent Decide"
                                clickable={proactiveEnabled}
                                onClick={() => proactiveEnabled && setScheduleMode('ai_agent')}
                                color={schedule.mode === 'ai_agent' ? 'secondary' : 'default'}
                                variant={schedule.mode === 'ai_agent' ? 'filled' : 'outlined'}
                                size="small"
                            />
                        </Box>

                        {schedule.mode === 'exact' ? (
                            <Box display="flex" flexDirection="column" gap={1}>
                                {schedule.fireTimes.map((time, idx) => (
                                    <Box key={idx} display="flex" alignItems="center" gap={1}>
                                        <TextField
                                            type="time"
                                            value={time}
                                            onChange={e => setFireTime(idx, e.target.value)}
                                            size="small"
                                            disabled={!proactiveEnabled}
                                            sx={{ width: 150 }}
                                        />
                                        <IconButton
                                            size="small"
                                            onClick={() => removeFireTime(idx)}
                                            disabled={!proactiveEnabled || schedule.fireTimes.length <= 1}
                                        >
                                            ✕
                                        </IconButton>
                                    </Box>
                                ))}
                                <Button
                                    size="small"
                                    onClick={addFireTime}
                                    disabled={!proactiveEnabled}
                                    sx={{ alignSelf: 'flex-start', textTransform: 'none' }}
                                >
                                    + Add time
                                </Button>
                            </Box>
                        ) : schedule.mode === 'random' ? (
                            <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                                <TextField
                                    type="time"
                                    label="Window start"
                                    value={schedule.randomWindows[0]?.start ?? '12:00'}
                                    onChange={e => setRandomWindow('start', e.target.value)}
                                    size="small"
                                    disabled={!proactiveEnabled}
                                    InputLabelProps={{ shrink: true }}
                                    sx={{ width: 160 }}
                                />
                                <Typography variant="body2" color="textSecondary">to</Typography>
                                <TextField
                                    type="time"
                                    label="Window end"
                                    value={schedule.randomWindows[0]?.end ?? '14:00'}
                                    onChange={e => setRandomWindow('end', e.target.value)}
                                    size="small"
                                    disabled={!proactiveEnabled}
                                    InputLabelProps={{ shrink: true }}
                                    sx={{ width: 160 }}
                                />
                                <TextField
                                    type="number"
                                    label="Notifications in window"
                                    value={schedule.randomWindows[0]?.count ?? 1}
                                    onChange={e => setRandomWindow('count', Math.max(1, Math.min(20, Number(e.target.value))))}
                                    size="small"
                                    disabled={!proactiveEnabled}
                                    inputProps={{ min: 1, max: 20 }}
                                    sx={{ width: 180 }}
                                />
                            </Box>
                        ) : (
                            /* ai_agent mode: same window + count inputs, stored in randomWindows[0] */
                            <Box display="flex" alignItems="center" gap={1} flexWrap="wrap">
                                <TextField
                                    type="time"
                                    label="Allowed window start"
                                    value={schedule.randomWindows[0]?.start ?? '16:00'}
                                    onChange={e => setRandomWindow('start', e.target.value)}
                                    size="small"
                                    disabled={!proactiveEnabled}
                                    InputLabelProps={{ shrink: true }}
                                    sx={{ width: 175 }}
                                />
                                <Typography variant="body2" color="textSecondary">to</Typography>
                                <TextField
                                    type="time"
                                    label="Allowed window end"
                                    value={schedule.randomWindows[0]?.end ?? '20:00'}
                                    onChange={e => setRandomWindow('end', e.target.value)}
                                    size="small"
                                    disabled={!proactiveEnabled}
                                    InputLabelProps={{ shrink: true }}
                                    sx={{ width: 175 }}
                                />
                                <TextField
                                    type="number"
                                    label="Notifications per user"
                                    value={schedule.randomWindows[0]?.count ?? 1}
                                    onChange={e => setRandomWindow('count', Math.max(1, Math.min(20, Number(e.target.value))))}
                                    size="small"
                                    disabled={!proactiveEnabled}
                                    inputProps={{ min: 1, max: 20 }}
                                    sx={{ width: 185 }}
                                />
                            </Box>
                        )}
                        <Typography variant="caption" color="textSecondary" sx={{ mt: 1, display: 'block' }}>
                            {schedule.mode === 'exact'
                                ? 'The system fires a cycle at each exact time above, on the allowed days only.'
                                : schedule.mode === 'random'
                                ? 'The system fires the specified number of notifications at random minutes within this window, on the allowed days only.'
                                : 'Each day at 00:01 the AI queries each user\'s personal activity history and asks the LLM to pick the optimal notification times within the allowed window. Each user gets individually personalised scheduling. Note: Schedule changes made here take effect on the next daily run.'}
                        </Typography>
                        {/* Task 6.4: timezone display */}
                        <Typography variant="caption" sx={{ mt: 0.5, display: 'block', color: 'text.secondary', fontStyle: 'italic' }}>
                            🕐 Timezone: <strong>Asia/Jerusalem</strong> (Israel Standard Time / Israel Daylight Time).
                            All times above are interpreted in this timezone.
                        </Typography>
                        {!isScheduleValid && (
                            <Typography variant="caption" color="error" sx={{ display: 'block', mt: 0.5 }}>
                                Select at least one allowed day and at least one time.
                            </Typography>
                        )}
                    </Box>

                    <Divider />

                    {/* ── LLM Model selector ─────────────────────────────────── */}
                    <Box>
                        <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                            LLM Model
                        </Typography>
                        <FormControl size="small" fullWidth disabled={!proactiveEnabled}>
                            <InputLabel>Model</InputLabel>
                            <Select
                                value={llmModel}
                                label="Model"
                                onChange={e => setLlmModel(e.target.value)}
                            >
                                {LLM_MODEL_OPTIONS.map(opt => (
                                    <MenuItem key={opt.value} value={opt.value}>
                                        {opt.label}
                                    </MenuItem>
                                ))}
                            </Select>
                        </FormControl>
                        <Typography variant="caption" color="textSecondary" sx={{ mt: 0.5, display: 'block' }}>
                            This controls which AI model generates all proactive notifications for this experiment.
                            Changing this affects message quality, cost, and generation style.
                            Make sure the corresponding API key is set in the server environment
                            (OPENAI_API_KEY for GPT models, ANTHROPIC_API_KEY for Claude models).
                        </Typography>
                    </Box>

                    <Divider />

                    {/* ── Heuristic probability weights ──────────────────────── */}
                    <Box>
                        <Typography variant="subtitle1" fontWeight={600} gutterBottom>
                            Heuristic Probability Weights
                        </Typography>
                        <Typography variant="caption" color="textSecondary" sx={{ mb: 1, display: 'block' }}>
                            Each active heuristic is assigned a probability weight. On every cycle the system
                            randomly selects one according to those weights. The active weights must sum to
                            exactly 100%. If all heuristics are turned off, the system enters{' '}
                            <strong>Reactive mode</strong> — no notifications will be sent.
                        </Typography>

                        {/* Heuristic rows */}
                        <Box display="flex" flexDirection="column" gap={1.5}>
                            {HEURISTIC_KEYS.map(key => {
                                const meta = HEURISTICS[key];
                                const cfg  = configs[key];
                                return (
                                    <Box
                                        key={key}
                                        sx={{
                                            border: '1px solid',
                                            borderColor: cfg.enabled ? 'primary.main' : 'divider',
                                            borderRadius: 2,
                                            p: 2,
                                            opacity: proactiveEnabled ? 1 : 0.5,
                                            backgroundColor: cfg.enabled ? 'action.selected' : 'transparent',
                                            transition: 'border-color 0.2s, background-color 0.2s',
                                        }}
                                    >
                                        {/* Row header: toggle + name + weight input */}
                                        <Box display="flex" alignItems="center" gap={1}>
                                            <Switch
                                                size="small"
                                                checked={cfg.enabled}
                                                onChange={() => toggleHeuristic(key)}
                                                disabled={!proactiveEnabled}
                                                color="primary"
                                            />
                                            <Box flex={1}>
                                                <Typography variant="body1" fontWeight={600}>
                                                    {meta.label}
                                                </Typography>
                                                <Typography variant="body2" color="textSecondary">
                                                    {meta.description}
                                                </Typography>
                                            </Box>
                                            <TextField
                                                type="number"
                                                label="Weight %"
                                                value={cfg.weight}
                                                onChange={e => setWeight(key, Number(e.target.value))}
                                                size="small"
                                                disabled={!proactiveEnabled || !cfg.enabled}
                                                inputProps={{ min: 0, max: 100 }}
                                                sx={{ width: 100 }}
                                            />
                                        </Box>

                                        {/* Collapsible prompt editor */}
                                        {cfg.enabled && (
                                            <Box mt={1.5}>
                                                <Button
                                                    size="small"
                                                    onClick={() => togglePromptsOpen(key)}
                                                    endIcon={cfg.promptsOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                                                    sx={{ textTransform: 'none', px: 0, color: 'text.secondary' }}
                                                >
                                                    Edit LLM Prompts
                                                </Button>
                                                <Collapse in={cfg.promptsOpen}>
                                                    <Box
                                                        display="flex"
                                                        flexDirection="column"
                                                        gap={2.5}
                                                        mt={1.5}
                                                        pt={2}
                                                        px={2}
                                                        pb={2}
                                                        sx={{
                                                            borderRadius: 1.5,
                                                            border: '1px dashed',
                                                            borderColor: 'primary.light',
                                                            backgroundColor: 'background.paper',
                                                        }}
                                                    >
                                                        {meta.hasMemoryPrompt && (
                                                            <Box>
                                                                <Box display="flex" alignItems="center" gap={0.5} mb={0.75}>
                                                                    <Typography variant="body2" fontWeight={600}>
                                                                        Memory Prompt
                                                                    </Typography>
                                                                    <Tooltip
                                                                        title="What to extract from conversations. Write persona/task instructions only — JSON output constraints are added automatically by the system."
                                                                        placement="right"
                                                                        arrow
                                                                    >
                                                                        <InfoOutlinedIcon sx={{ fontSize: 15, color: 'text.disabled', cursor: 'help' }} />
                                                                    </Tooltip>
                                                                </Box>
                                                                <TextField
                                                                    multiline
                                                                    rows={4}
                                                                    fullWidth
                                                                    size="small"
                                                                    value={cfg.memoryPrompt}
                                                                    onChange={e => setPrompt(key, 'memoryPrompt', e.target.value)}
                                                                />
                                                            </Box>
                                                        )}
                                                        <Box>
                                                            <Box display="flex" alignItems="center" gap={0.5} mb={0.75}>
                                                                <Typography variant="body2" fontWeight={600}>
                                                                    Message Prompt
                                                                </Typography>
                                                                <Tooltip
                                                                    title="Persona and tone for the notification. Output constraints are added automatically — do not include 'Return ONLY the final message' rules."
                                                                    placement="right"
                                                                    arrow
                                                                >
                                                                    <InfoOutlinedIcon sx={{ fontSize: 15, color: 'text.disabled', cursor: 'help' }} />
                                                                </Tooltip>
                                                            </Box>
                                                            <TextField
                                                                multiline
                                                                rows={4}
                                                                fullWidth
                                                                size="small"
                                                                value={cfg.messagePrompt}
                                                                onChange={e => setPrompt(key, 'messagePrompt', e.target.value)}
                                                            />
                                                        </Box>
                                                        <Box>
                                                            <Button
                                                                size="small"
                                                                variant="outlined"
                                                                color="warning"
                                                                sx={{ textTransform: 'none' }}
                                                                onClick={() => setConfigs(prev => ({
                                                                    ...prev,
                                                                    [key]: {
                                                                        ...prev[key],
                                                                        memoryPrompt:  meta.defaultMemoryPrompt,
                                                                        messagePrompt: meta.defaultMessagePrompt,
                                                                    },
                                                                }))}
                                                            >
                                                                Reset to defaults
                                                            </Button>
                                                        </Box>
                                                    </Box>
                                                </Collapse>
                                            </Box>
                                        )}
                                    </Box>
                                );
                            })}
                        </Box>

                        {/* Weight sum indicator */}
                        <Box display="flex" alignItems="center" gap={1} mt={2}>
                            <Typography variant="body1" color="textSecondary" fontWeight={500}>
                                Total active weight:
                            </Typography>
                            <Chip
                                label={`${totalWeight}%`}
                                color={!anyEnabled ? 'default' : isWeightValid ? 'success' : 'error'}
                                size="medium"
                                sx={{ fontWeight: 700, fontSize: '0.85rem' }}
                            />
                            {anyEnabled && !isWeightValid && (
                                <Typography variant="body2" color="error" fontWeight={500}>
                                    Must equal 100% before saving
                                </Typography>
                            )}
                        </Box>

                        {/* Reactive mode info */}
                        {!anyEnabled && (
                            <Alert severity="info" sx={{ mt: 1.5 }}>
                                All heuristics are off — the system will enter{' '}
                                <strong>Reactive mode</strong> and send no proactive notifications.
                            </Alert>
                        )}
                    </Box>

                    <Divider />

                    {/* ── Participant join link ───────────────────────────────── */}
                    {proactiveEnabled && (
                        <Box>
                            <Typography variant="h6" gutterBottom>
                                Participant Join Link
                            </Typography>
                            <Typography variant="body2" color="textSecondary" gutterBottom>
                                Share this link with participants. Opening it on their Android device will
                                download the Lexi app and automatically connect them to this experiment —
                                no manual configuration needed.
                            </Typography>
                            <TextField
                                fullWidth
                                value={deepLink}
                                size="small"
                                disabled
                                InputProps={{
                                    endAdornment: (
                                        <Tooltip title="Copy link">
                                            <IconButton onClick={handleCopyLink} size="small" color="primary">
                                                <ContentCopyIcon />
                                            </IconButton>
                                        </Tooltip>
                                    ),
                                }}
                            />
                        </Box>
                    )}

                </Box>
            </DialogContent>

            <DialogActions>
                <Button onClick={onClose} color="secondary">
                    Close
                </Button>
                <Button
                    onClick={handleSave}
                    color="primary"
                    variant="contained"
                    disabled={isLoading || (anyEnabled && !isWeightValid) || !isScheduleValid}
                >
                    {isLoading ? 'Saving…' : 'Save'}
                </Button>
            </DialogActions>
        </Dialog>
    );
};
