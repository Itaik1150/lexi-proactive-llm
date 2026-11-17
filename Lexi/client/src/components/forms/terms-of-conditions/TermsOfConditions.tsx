import { Box, Checkbox, Typography } from '@mui/material';
import React from 'react';
import { FitButton } from '../CommonFormStyles.s';
import {
    TermsBox,
    TermsButtonContainer,
    TermsFormControl,
    TermsMainContainer,
    TermsPaper,
} from './TermsOfConditions.s';

/**
 * Informed consent, shown at registration when the experiment's registration form has
 * `termsOfConditions: true`.
 *
 * DRAFT (17 Nov 2026): placeholder written for testing. It must be replaced by the text approved by
 * the ethics committee of Ben-Gurion University before any real participant is recruited
 * (docs/REVIEW.md P8, X1). It describes what the system really does with the data; keep it that way.
 */
const htmlContent = `
<p><b>Study:</b> Lexi Takes the Lead &ndash; conversations with an AI companion</p>
<p><b>Researchers:</b> Itai Kohn and Dr. Guy Laban, Department of Industrial Engineering and Management,
Ben-Gurion University of the Negev.</p>

<h4>What is this study about?</h4>
<p>We study how people talk with an AI companion over time. You will use an application called Lexi on your
Android phone for 14 days. Lexi is a computer program based on artificial intelligence. It is not a person and it
is not a therapist.</p>

<h4>What will you be asked to do?</h4>
<ul>
<li>Answer a questionnaire now, and another one at the end of the 14 days (a few minutes each).</li>
<li>Talk with Lexi in writing, whenever you like and about whatever you like, at least 6 times a week. Please end
each conversation with the Finish button and answer four short questions about it.</li>
<li>Depending on the group you were assigned to at random, Lexi may send you notifications during the day.</li>
</ul>

<h4>What information is collected?</h4>
<ul>
<li>What you write to Lexi and what Lexi answers, and summaries of your conversations that the system creates so
that Lexi can remember them.</li>
<li>When you use the application and how you respond to notifications.</li>
<li>Your answers to the questionnaires, your age and gender, the user name you choose, and your Prolific ID.</li>
</ul>
<p>To produce Lexi's answers, the text of your conversations is processed by an external artificial-intelligence
service (OpenAI). Please do not write names, addresses or other details that identify you or other people.</p>

<h4>How is the information protected?</h4>
<p>The information is stored on secured servers and is available only to the research team. It is identified by
your user name and your Prolific ID, not by your real name. Results are published only in a form that does not
identify individual participants. Excerpts of conversations may be quoted in publications only after removing
any identifying detail.</p>

<h4>Risks and benefits</h4>
<p>Talking about personal matters may sometimes be uncomfortable. You decide what to share, and you can stop a
conversation at any time. Lexi cannot help in an emergency. If you feel that you are in danger or in crisis,
please contact your local emergency services or a crisis line. There is no direct benefit to you apart from the
payment; the study may help to design AI companions that respect their users.</p>

<h4>Voluntary participation</h4>
<p>Taking part is voluntary. You may stop at any time without giving a reason, and you may ask the researchers
to delete your data as long as it has not been analysed or published. Payment is made through Prolific as
described in the study listing.</p>

<h4>Questions</h4>
<p>For any question about the study, please contact the researchers through Prolific.</p>

<h4>Consent</h4>
<p>By ticking the box below you confirm that you are 18 or older, that you have read and understood this
information, and that you agree to take part in the study and to the use of your data as described above.</p>
`;

interface TermsOfConditionsProps {
    setPage: (page: number) => void;
    isAgreed: boolean;
    setIsAgreed: (isAgreed: boolean) => void;
    onSubmit: () => void;
}

const TermsOfConditions: React.FC<TermsOfConditionsProps> = ({ setPage, onSubmit, isAgreed, setIsAgreed }) => {
    const handleAgreeChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        setIsAgreed(event.target.checked);
    };

    return (
        <TermsMainContainer>
            <Typography variant="h5" gutterBottom>
                Information and Consent
            </Typography>
            <TermsPaper>
                <TermsBox>
                    <Box dangerouslySetInnerHTML={{ __html: htmlContent }} />
                </TermsBox>
            </TermsPaper>
            <TermsFormControl
                control={
                    <Checkbox checked={isAgreed} onChange={handleAgreeChange} name="agreed" color="primary" />
                }
                label="I have read the information above and I agree to take part"
            />
            <TermsButtonContainer>
                <FitButton
                    variant="outlined"
                    color="primary"
                    onClick={() => {
                        setPage(1);
                    }}
                >
                    Back
                </FitButton>
                <FitButton
                    variant="contained"
                    color="primary"
                    disabled={!isAgreed}
                    onClick={() => {
                        onSubmit();
                    }}
                >
                    Continue
                </FitButton>
            </TermsButtonContainer>
        </TermsMainContainer>
    );
};

export default TermsOfConditions;
