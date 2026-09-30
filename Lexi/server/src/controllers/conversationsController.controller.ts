import { Request, Response } from 'express';
import mongoose from 'mongoose';
import { conversationsService } from '../services/conversations.service';
import { proactiveLogsService } from '../services/proactiveLogs.service';
import { requestHandler } from '../utils/requestHandler';

class ConvesationsController {
    message = requestHandler(
        async (req: Request, res: Response) => {
            const { message, conversationId }: { message: any; conversationId: string } = req.body;
            this.validateMessage(message.content);

            const savedResponse = await conversationsService.message(message, conversationId);

            // When the user (not AI) sends a message, the proactive opener has been
            // "consumed" — reset firstChatSentence back to the original greeting.
            if (message.role === 'user') {
                this.resetProactivePromptOnInteraction(conversationId).catch(() => {});
                proactiveLogsService.markReplied(conversationId).catch(() => {});
            }

            res.status(200).send(savedResponse);
        },
        (req, res, error) => {
            if (error.code === 403) {
                res.status(403).json({ message: 'Messages Limit Exceeded' });
                return;
            }
            if (error.code === 'context_length_exceeded') {
                res.status(400).json({ message: 'Message Is Too Long' });
                return;
            }
            res.status(500).json({ message: 'Internal Server Error' });
        },
    );

    streamMessage = requestHandler(
        async (req: Request, res: Response) => {
            const conversationId = req.query.conversationId as string;
            const role = req.query.role as string;
            const content = req.query.content as string;
            const message = { role, content };
            this.validateMessage(message.content);

            res.writeHead(200, {
                'Content-Type': 'text/event-stream',
                'Cache-Control': 'no-cache',
                Connection: 'keep-alive',
            });

            const streamResponse = async (partialMessage) => {
                res.write(`data: ${JSON.stringify({ message: partialMessage })}\n\n`);
            };

            const closeStream = async (message) => {
                res.write(`event: close\ndata: ${JSON.stringify(message)}\n\n`);
                res.end();
            };

            const savedResponse = await conversationsService.message(message, conversationId, streamResponse);

            if (role === 'user') {
                this.resetProactivePromptOnInteraction(conversationId).catch(() => {});
                proactiveLogsService.markReplied(conversationId).catch(() => {});
            }

            closeStream(savedResponse);
        },
        (req, res, error) => {
            if (error.code === 403) {
                res.write(
                    `data: ${JSON.stringify({
                        error: { response: { status: 403, data: 'Messages Limit Exceeded' } },
                    })}\n\n`,
                );
                res.end();
                return;
            }
            if (error.code === 'context_length_exceeded') {
                res.write(
                    `data: ${JSON.stringify({
                        error: { response: { status: 400, data: 'Message Is Too Long' } },
                    })}\n\n`,
                );
                res.end();
                return;
            }
            res.write(
                `data: ${JSON.stringify({
                    error: { response: { status: 500, data: 'Internal Server Error' } },
                })}\n\n`,
            );
            res.end();
        },
    );

    createConversation = requestHandler(
        async (req: Request, res: Response) => {
            const { userId, numberOfConversations, experimentId } = req.body;
            const conversationId = await conversationsService.createConversation(
                userId,
                numberOfConversations,
                experimentId,
            );
            res.cookie('conversationId', conversationId, {
                secure: true,
                sameSite: 'none',
            });
            res.status(200).send(conversationId);
        },
        (_, res, error) => {
            if (error.code === 403) {
                res.status(403).json({ message: 'Conversations Limit Exceeded' });
                return;
            }
            res.status(500).json({ message: 'Internal Server Error' });
        },
    );

    getConversation = requestHandler(async (req: Request, res: Response) => {
        const conversationId = req.query.conversationId as string;

        if (!conversationId || !mongoose.Types.ObjectId.isValid(conversationId)) {
            res.status(401).send('Invalid convesationId');
            console.warn(`Invalid convesationId: ${conversationId}`);
            return;
        }

        const conversation = await conversationsService.getConversation(conversationId);

        // Funnel: the participant's app has fetched the notification's conversation.
        proactiveLogsService.markOpened(conversationId).catch(() => {});
        
        // Add debug logging to verify isProactiveOpener is being sent
        if (conversation.length > 0) {
            console.log(`[getConversation] Returning ${conversation.length} messages. First message isProactiveOpener:`, conversation[0].isProactiveOpener);
        }
        
        res.status(200).send(conversation);
    });

    /**
     * Called when the user sends their first message in any conversation.
     * If the user still has a proactive opener injected (injected_prompt_reset_after is set),
     * we restore firstChatSentence to the original greeting immediately.
     */
    private async resetProactivePromptOnInteraction(conversationId: string): Promise<void> {
        try {
            const db = mongoose.connection.db;

            const meta = await db.collection('metadata_conversations').findOne(
                { _id: new mongoose.Types.ObjectId(conversationId) },
                { projection: { userId: 1 } },
            );
            if (!meta?.userId) return;

            const user = await db.collection('users').findOne(
                {
                    _id: new mongoose.Types.ObjectId(String(meta.userId)),
                    'proactiveMemory.injected_prompt_reset_after': { $exists: true },
                },
                { projection: { 'proactiveMemory.injected_prompt_original': 1 } },
            );
            if (!user) return;

            const original = user.proactiveMemory?.injected_prompt_original ?? '';

            await db.collection('users').updateOne(
                { _id: user._id },
                {
                    $set:   { 'agent.firstChatSentence': original },
                    $unset: {
                        'proactiveMemory.injected_prompt_original':    '',
                        'proactiveMemory.injected_prompt_reset_after': '',
                    },
                },
            );
            console.log(`[proactive] reset firstChatSentence for user ${meta.userId} after user interaction`);
        } catch (_) {
            // Non-critical
        }
    }

    updateConversationMetadata = requestHandler(async (req: Request, res: Response) => {
        const { conversationId, data, isPreConversation } = req.body;

        await conversationsService.updateConversationSurveysData(conversationId, data, isPreConversation);

        res.status(200).send();
    });

    finishConversation = requestHandler(async (req: Request, res: Response) => {
        const { conversationId, experimentId, isAdmin } = req.body;

        await conversationsService.finishConversation(conversationId, experimentId, isAdmin);

        // Reset the proactive opener when the user finishes a conversation
        this.resetProactivePromptOnInteraction(conversationId).catch(() => {});

        res.status(200).send();
    });

    updateUserAnnotation = requestHandler(async (req: Request, res: Response) => {
        const { messageId, userAnnotation } = req.body;
        await conversationsService.updateUserAnnotation(messageId, userAnnotation);

        res.status(200).send();
    });

    private validateMessage(message: string): void {
        if (typeof message !== 'string') {
            const error = new Error('Bad Request');
            error['code'] = 400;
            throw error;
        }

        const tokenLimit = 4096;
        const estimatedTokens = this.estimateTokenCount(message);

        if (estimatedTokens > tokenLimit) {
            const error = new Error('Message Is Too Long');
            error['code'] = 'context_length_exceeded';
            throw error;
        }
    }

    private estimateTokenCount(message: string): number {
        const charsPerToken = 4;
        return Math.ceil(message.length / charsPerToken);
    }
}

export const convesationsController = new ConvesationsController();
