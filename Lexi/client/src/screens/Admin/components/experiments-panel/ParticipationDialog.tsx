import { getParticipation } from '@DAL/server-requests/experiments';
import {
    Button,
    Dialog,
    DialogActions,
    DialogContent,
    DialogTitle,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    Typography,
} from '@mui/material';
import React, { useEffect, useState } from 'react';

/**
 * Who is really taking part in an experiment (docs/REVIEW.md P5): one row per participant, with the
 * numbers needed to decide who completed the study on Prolific. Read-only; downloadable as CSV.
 */

const COLUMNS: Array<{ key: string; label: string }> = [
    { key: 'username', label: 'Participant' },
    { key: 'prolificId', label: 'Prolific ID' },
    { key: 'day', label: 'Day' },
    { key: 'conversations', label: 'Conversations' },
    { key: 'conversationsWeek1', label: 'Week 1' },
    { key: 'conversationsWeek2', label: 'Week 2' },
    { key: 'finished', label: 'Finished' },
    { key: 'surveysAfterConversation', label: 'Short surveys' },
    { key: 'notificationsSent', label: 'Notif. sent' },
    { key: 'notificationsTapped', label: 'Tapped' },
    { key: 'notificationsReplied', label: 'Replied' },
    { key: 'baselineAnswered', label: 'Baseline' },
    { key: 'endSurveyDone', label: 'End survey' },
    { key: 'lastActive', label: 'Last active' },
];

const show = (value: unknown): string => {
    if (value === true) return 'yes';
    if (value === false) return 'no';
    if (value === null || value === undefined) return '';
    if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) return value.slice(0, 16).replace('T', ' ');
    return String(value);
};

const toCsv = (rows: any[]): string =>
    [COLUMNS.map((c) => c.label), ...rows.map((r) => COLUMNS.map((c) => show(r[c.key])))]
        .map((line) => line.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(','))
        .join('\n');

interface ParticipationDialogProps {
    open: boolean;
    onClose: () => void;
    experimentId: string;
    title: string;
}

export const ParticipationDialog: React.FC<ParticipationDialogProps> = ({ open, onClose, experimentId, title }) => {
    const [rows, setRows] = useState<any[] | null>(null);

    useEffect(() => {
        if (!open) return;
        setRows(null);
        getParticipation(experimentId).then(setRows);
    }, [open, experimentId]);

    const download = () => {
        const url = URL.createObjectURL(new Blob([toCsv(rows || [])], { type: 'text/csv' }));
        const link = document.createElement('a');
        link.href = url;
        link.download = `participation-${title || experimentId}.csv`;
        link.click();
        URL.revokeObjectURL(url);
    };

    return (
        <Dialog open={open} onClose={onClose} maxWidth="xl" fullWidth>
            <DialogTitle>Participation: {title}</DialogTitle>
            <DialogContent>
                {rows === null ? (
                    <Typography>Loading…</Typography>
                ) : rows.length === 0 ? (
                    <Typography>No participants yet.</Typography>
                ) : (
                    <Table size="small" stickyHeader>
                        <TableHead>
                            <TableRow>
                                {COLUMNS.map((c) => (
                                    <TableCell key={c.key}>{c.label}</TableCell>
                                ))}
                            </TableRow>
                        </TableHead>
                        <TableBody>
                            {rows.map((row, index) => (
                                <TableRow key={index}>
                                    {COLUMNS.map((c) => (
                                        <TableCell key={c.key}>{show(row[c.key])}</TableCell>
                                    ))}
                                </TableRow>
                            ))}
                        </TableBody>
                    </Table>
                )}
                <Typography variant="caption" color="textSecondary" sx={{ display: 'block', mt: 2 }}>
                    A conversation counts when the participant wrote at least one message. Week 1 is study days 1–7,
                    week 2 is days 8–14, counted from each participant&apos;s registration.
                </Typography>
            </DialogContent>
            <DialogActions>
                <Button onClick={download} disabled={!rows || rows.length === 0}>
                    Download CSV
                </Button>
                <Button onClick={onClose} variant="contained">
                    Close
                </Button>
            </DialogActions>
        </Dialog>
    );
};
