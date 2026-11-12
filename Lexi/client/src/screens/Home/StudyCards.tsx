import { ackOnboardingCode, getStudyStatus, submitEndSurvey } from '@DAL/server-requests/users';
import { Alert, Box, Button, Dialog, Grid, Typography, useMediaQuery } from '@mui/material';
import theme from '@root/Theme';
import React, { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import Question from '../../components/questions/Question';

/**
 * The participant's study steps on the home screen (docs/REVIEW.md P2, P5): the Prolific completion
 * code after onboarding, the end-of-study questionnaire when it opens, and the final completion code.
 * The server decides what may be shown; a test account that is not linked to Prolific sees nothing.
 */

const CodeCard: React.FC<{ title: string; text: string; code: string; onDone?: () => void }> = ({
    title,
    text,
    code,
    onDone,
}) => {
    const [copied, setCopied] = useState(false);
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(code);
            setCopied(true);
        } catch (err) {
            setCopied(false); // the code stays visible and selectable
        }
    };
    return (
        <Alert severity="success" icon={false} sx={{ width: '100%', '& .MuiAlert-message': { width: '100%' } }}>
            <Typography fontWeight={700}>{title}</Typography>
            <Typography variant="body2" sx={{ my: 1 }}>
                {text}
            </Typography>
            <Typography
                sx={{ fontFamily: 'monospace', fontSize: '1.4rem', fontWeight: 700, userSelect: 'all', mb: 1 }}
            >
                {code}
            </Typography>
            <Box display="flex" gap={1} flexWrap="wrap">
                <Button size="small" variant="contained" onClick={copy}>
                    {copied ? 'Copied' : 'Copy code'}
                </Button>
                {onDone && (
                    <Button size="small" variant="outlined" onClick={onDone}>
                        I have entered it on Prolific
                    </Button>
                )}
            </Box>
        </Alert>
    );
};

const StudyCards: React.FC = () => {
    const isMobile = useMediaQuery(theme.breakpoints.down('sm'));
    const [status, setStatus] = useState<any | null>(null);
    const [surveyOpen, setSurveyOpen] = useState(false);
    const [saving, setSaving] = useState(false);
    const {
        register,
        handleSubmit,
        getValues,
        setValue,
        control,
        formState: { errors },
    } = useForm();

    const refresh = () => getStudyStatus().then(setStatus);
    useEffect(() => {
        refresh();
    }, []);

    if (!status) return null;

    const onSubmitSurvey = async (answers) => {
        setSaving(true);
        try {
            await submitEndSurvey(answers);
            setSurveyOpen(false);
            await refresh();
        } finally {
            setSaving(false);
        }
    };

    const form = status.endSurveyForm;
    if (!status.onboardingCode && !status.finalCode && !(status.endSurveyDue && form)) return null;

    return (
        <Box display="flex" flexDirection="column" gap={1.5} width={isMobile ? '92%' : '60%'}>
            {status.onboardingCode && (
                <CodeCard
                    title="You are all set"
                    text="To complete the first part on Prolific, go back to Prolific and enter this completion code:"
                    code={status.onboardingCode}
                    onDone={async () => {
                        await ackOnboardingCode();
                        await refresh();
                    }}
                />
            )}
            {status.endSurveyDue && form && (
                <Alert severity="info" icon={false} sx={{ width: '100%', '& .MuiAlert-message': { width: '100%' } }}>
                    <Typography fontWeight={700}>Final questionnaire</Typography>
                    <Typography variant="body2" sx={{ my: 1 }}>
                        The study period is over. Please answer the final questionnaire to receive your completion
                        code.
                    </Typography>
                    <Button size="small" variant="contained" onClick={() => setSurveyOpen(true)}>
                        Start the questionnaire
                    </Button>
                </Alert>
            )}
            {status.finalCode && (
                <CodeCard
                    title="Thank you for taking part"
                    text="To complete the final part on Prolific, enter this completion code there:"
                    code={status.finalCode}
                />
            )}
            {form && (
                <Dialog open={surveyOpen} fullScreen={isMobile} maxWidth="md" fullWidth onClose={() => setSurveyOpen(false)}>
                    <Box p={isMobile ? 2 : 4}>
                        <Typography variant="h5" gutterBottom>
                            {form.title}
                        </Typography>
                        <Typography variant="subtitle1" gutterBottom sx={{ mb: 2 }}>
                            {form.instructions}
                        </Typography>
                        {form.questions.map((question, index) => (
                            <Grid item xs={12} key={index}>
                                <Question
                                    type={question.type}
                                    props={question.props}
                                    errors={errors}
                                    register={register}
                                    getValues={getValues}
                                    setValue={setValue}
                                    control={control}
                                />
                            </Grid>
                        ))}
                        <Box display="flex" gap={1} mt={3}>
                            <Button variant="contained" disabled={saving} onClick={handleSubmit(onSubmitSurvey)}>
                                Submit
                            </Button>
                            <Button variant="text" disabled={saving} onClick={() => setSurveyOpen(false)}>
                                Later
                            </Button>
                        </Box>
                    </Box>
                </Dialog>
            )}
        </Box>
    );
};

export default StudyCards;
