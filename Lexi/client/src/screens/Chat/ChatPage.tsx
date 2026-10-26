import { getConversation, updateUserAnnotation } from '@DAL/server-requests/conversations';
import FinishConversationDialog from '@components/common/FinishConversationDialog';
import LoadingPage from '@components/common/LoadingPage';
import { SnackbarStatus, useSnackbar } from '@contexts/SnackbarProvider';
import { useConversationId } from '@hooks/useConversationId';
import useEffectAsync from '@hooks/useEffectAsync';
import useActiveUser from '@hooks/useActiveUser';
import ExitToAppOutlinedIcon from '@mui/icons-material/ExitToAppOutlined';
import { Box, Button, Dialog, Grid, Typography, useMediaQuery } from '@mui/material';
import theme from '@root/Theme';
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { getExperimentCoversationForms, getExperimentFeatures } from '../../DAL/server-requests/experiments';
import { ConversationForm } from '../../components/forms/conversation-form/ConversationForm';
import { useExperimentId } from '../../hooks/useExperimentId';
import { UserAnnotation } from '../../models/AppModels';
import FontSizeSwitch from '@components/common/FontSizeSwitch';
import { MainContainer, MessageListContainer, SectionContainer, SectionInnerContainer } from './ChatPage.s';
import MessageList from './components/MessageList';
import InputBox from './components/input-box/InputBox';
import { SidebarChat } from './components/side-bar-chat/SideBarChat';

interface ChatPageProps {
    isFinishDialogOpen: boolean;
    setIsFinishDialogOpen: (open: boolean) => void;
}

const ChatPage: React.FC<ChatPageProps> = ({ isFinishDialogOpen, setIsFinishDialogOpen }) => {
    const { activeUser } = useActiveUser();
    const navigate = useNavigate();
    const messagesRef = useRef(null);
    const { openSnackbar } = useSnackbar();
    const [messages, setMessages] = useState([]);
    const [conversationForms, setConversationForms] = useState({
        preConversation: null,
        postConversation: null,
    });
    const [messageFontSize, setMessageFontSize] = useState<'sm' | 'lg'>('lg');
    const [surveyOpen, setIsSurveyOpen] = useState(false);
    const [isPageLoading, setIsPageLoading] = useState(true);
    const [experimentFeatures, setExperimentFeatures] = useState(null);
    const [isMessageLoading, setIsMessageLoading] = useState(false);
    const isMobile = useMediaQuery(theme.breakpoints.down('sm'));
    const questionnaireLink = 'https://docs.google.com/forms/u/0/?tgif=d&ec=asw-forms-hero-goto';
    const conversationId = useConversationId();
    const experimentId = useExperimentId();

    useEffect(() => {
        if (messagesRef.current) {
            messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
        }
    }, [messages]);

    useEffectAsync(async () => {
        const preConversationFormAnsweredKey = `preConversationFormAnswered-${conversationId}`;
        const preConversationFormAnsweredKeyAnswered = sessionStorage.getItem(preConversationFormAnsweredKey);
        
        // Detect if we came from a notification
        // Priority: Check Android bridge first, then fall back to first-view detection
        let cameFromNotification = false;
        
        if (window.Android?.wasOpenedFromNotification) {
            try {
                cameFromNotification = window.Android.wasOpenedFromNotification();
                console.log('[ChatPage] Android bridge reports notification:', cameFromNotification);
            } catch (err) {
                console.warn('[ChatPage] Error checking Android notification flag:', err);
            }
        }
        
        // Fallback: If conversation not previously viewed, likely from notification
        const conversationViewKey = `conversationViewed-${conversationId}`;
        const previouslyViewed = sessionStorage.getItem(conversationViewKey);
        
        if (!previouslyViewed || cameFromNotification) {
            sessionStorage.setItem('fromNotification', 'true');
            sessionStorage.setItem(conversationViewKey, 'true');
            console.log('[ChatPage] Marking as from notification (Android:', cameFromNotification, ', FirstView:', !previouslyViewed, ')');
        }
        
        try {
            const [conversation, conversationForms, experimentFeaturesRes] = await Promise.all([
                getConversation(conversationId),
                getExperimentCoversationForms(experimentId),
                getExperimentFeatures(experimentId),
            ]);
            if (!preConversationFormAnsweredKeyAnswered && conversationForms.preConversation) {
                setIsSurveyOpen(true);
            }
            setConversationForms(conversationForms);
            setExperimentFeatures(experimentFeaturesRes);
            console.log('[ChatPage] Loaded conversation:', conversation);
            console.log('[ChatPage] First message isProactiveOpener:', conversation[0]?.isProactiveOpener);
            console.log('[ChatPage] Full first message data:', JSON.stringify(conversation[0]));
            setMessages(conversation.length ? conversation : []);
            setIsPageLoading(false);
        } catch (err) {
            openSnackbar('Failed to load conversation', SnackbarStatus.ERROR);
            navigate(-1);
        }
    }, []);

    const handlePreConversationSurveyDone = () => {
        const preConversationFormAnsweredKey = `preConversationFormAnswered-${conversationId}`;
        sessionStorage.setItem(preConversationFormAnsweredKey, 'true');
        setIsSurveyOpen(false);
    };

    const handleUpdateUserAnnotation = async (messageId: string, userAnnotation: UserAnnotation) => {
        try {
            await updateUserAnnotation(messageId, userAnnotation);
            setMessages(
                messages.map((message) => (message._id === messageId ? { ...message, userAnnotation } : message)),
            );
        } catch (error) {
            console.log(error);
        }
    };

    if (activeUser?.is_demo_finished) {
        return (
            <Box
                display="flex"
                flexDirection="column"
                alignItems="center"
                justifyContent="center"
                height="100vh"
                gap={3}
                px={3}
                bgcolor="#f8f9fa"
            >
                <Typography variant="h4" fontWeight={700} textAlign="center" color="primary">
                    Demo Completed
                </Typography>
                <Typography variant="h6" fontWeight={500} textAlign="center" color="text.secondary">
                    Thank you for participating in the live presentation.
                </Typography>
                <Box mt={4} textAlign="center">
                    <Typography variant="body1" color="text.secondary" fontWeight={500}>
                        Itai Kohn | Dr. Guy Laban
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                        Ben-Gurion University of the Negev
                    </Typography>
                </Box>
            </Box>
        );
    }

    return isPageLoading ? (
        <LoadingPage />
    ) : (
        <MainContainer container>
            {!isMobile && (
                <Grid item xs={2} sm={2} md={2} lg={2} style={{ backgroundColor: '#f5f5f5' }}>
                    <SidebarChat
                        setIsOpen={setIsFinishDialogOpen}
                        setMessageFontSize={setMessageFontSize}
                        messageFontSize={messageFontSize}
                    />
                </Grid>
            )}
            <Grid item xs={12} sm={10} md={10} lg={10}>
                <SectionContainer>
                    <SectionInnerContainer container direction="column">
                        <MessageListContainer ref={messagesRef} item>
                            <MessageList
                                isMobile={isMobile}
                                messages={messages}
                                isMessageLoading={isMessageLoading}
                                size={messageFontSize}
                                handleUpdateUserAnnotation={handleUpdateUserAnnotation}
                                experimentHasUserAnnotation={experimentFeatures?.userAnnotation}
                            />
                        </MessageListContainer>
                        {isMobile && (
                            <Grid item display="flex" justifyContent="space-between" alignItems="center" px={1} pb={0.5}>
                                <Button
                                    variant="outlined"
                                    size="small"
                                    startIcon={<ExitToAppOutlinedIcon />}
                                    onClick={() => setIsFinishDialogOpen(true)}
                                    sx={{ textTransform: 'none', fontWeight: 700, minHeight: 36 }}
                                >
                                    Finish
                                </Button>
                                <FontSizeSwitch fontSize={messageFontSize} setFontSize={setMessageFontSize} />
                            </Grid>
                        )}
                        <Grid item display={'flex'} justifyContent={'center'}>
                            <InputBox
                                isMobile={isMobile}
                                messages={messages}
                                setMessages={setMessages}
                                conversationId={conversationId}
                                setIsMessageLoading={setIsMessageLoading}
                                fontSize={messageFontSize}
                                isStreamMessage={experimentFeatures?.streamMessage}
                            />
                        </Grid>
                    </SectionInnerContainer>
                </SectionContainer>
            </Grid>
            {isFinishDialogOpen && (
                <FinishConversationDialog
                    open={isFinishDialogOpen}
                    setIsOpen={setIsFinishDialogOpen}
                    questionnaireLink={questionnaireLink}
                    form={conversationForms.postConversation}
                />
            )}
            <Dialog
                open={surveyOpen}
                maxWidth={'lg'}
                fullScreen={isMobile}
                PaperProps={{
                    style: {
                        maxHeight: isMobile ? 'none' : '70vh',
                        overflow: 'auto',
                    },
                }}
            >
                <ConversationForm
                    form={conversationForms.preConversation}
                    isPreConversation={true}
                    handleDone={handlePreConversationSurveyDone}
                />
            </Dialog>
        </MainContainer>
    );
};

export default ChatPage;
