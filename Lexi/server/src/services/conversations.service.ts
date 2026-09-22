import dotenv from 'dotenv';
import mongoose from 'mongoose';
import { OpenAI } from 'openai';
import { IAgent, Message, UserAnnotation } from 'src/types';
import { ConversationsModel } from '../models/ConversationsModel';
import { MetadataConversationsModel } from '../models/MetadataConversationsModel';
import { experimentsService } from './experiments.service';
import { usersService } from './users.service';

dotenv.config();

const { OPENAI_API_KEY } = process.env;
if (!OPENAI_API_KEY) throw new Error('Server is not configured with OpenAI API key');
const openai = new OpenAI({ apiKey: OPENAI_API_KEY });

class ConversationsService {
    message = async (message, conversationId: string, streamResponse?) => {
        const [conversation, metadataConversation] = await Promise.all([
            this.getConversation(conversationId, true),
            this.getConversationMetadata(conversationId),
        ]);

        if (
            metadataConversation.maxMessages &&
            metadataConversation.messagesNumber + 1 > metadataConversation.maxMessages
        ) {
            const error = new Error('Message limit exceeded');
            error['code'] = 403;
            throw error;
        }

        // When a user replies, restore the original firstChatSentence (reset proactive injection).
        // Fire-and-forget: don't block the message flow on the DB update.
        if (message.role === 'user' && metadataConversation?.userId) {
            usersService.resetInjectedPromptIfNeeded(metadataConversation.userId.toString()).catch(() => {});
        }

        const messages: any[] = await this.getConversationMessages(
            metadataConversation.agent,
            conversation,
            message,
            metadataConversation.userId?.toString(),
            conversationId,
        );
        const chatRequest = this.getChatRequest(metadataConversation.agent, messages);
        await this.createMessageDoc(message, conversationId, conversation.length + 1);

        let assistantMessage = '';

        if (!streamResponse) {
            const response = await openai.chat.completions.create(chatRequest);
            assistantMessage = response.choices[0].message.content?.trim();
        } else {
            const responseStream = await openai.chat.completions.create({ ...chatRequest, stream: true });
            for await (const partialResponse of responseStream) {
                const assistantMessagePart = partialResponse.choices[0]?.delta?.content || '';
                await streamResponse(assistantMessagePart);
                assistantMessage += assistantMessagePart;
            }
        }

        const savedMessage = await this.createMessageDoc(
            {
                content: assistantMessage,
                role: 'assistant',
            },
            conversationId,
            conversation.length + 2,
        );

        this.updateConversationMetadata(conversationId, {
            $inc: { messagesNumber: 1 },
            $set: { lastMessageDate: new Date(), lastMessageTimestamp: Date.now() },
        });

        return savedMessage;
    };

    createConversation = async (userId: string, userConversationsNumber: number, experimentId: string) => {
        let agent;
        const [user, experimentBoundries] = await Promise.all([
            usersService.getUserById(userId),
            experimentsService.getExperimentBoundries(experimentId),
        ]);

        if (
            !user.isAdmin &&
            experimentBoundries.maxConversations &&
            userConversationsNumber + 1 > experimentBoundries.maxConversations
        ) {
            const error = new Error('Conversations limit exceeded');
            error['code'] = 403;
            throw error;
        }

        if (user.isAdmin) {
            agent = await experimentsService.getActiveAgent(experimentId);
        }

        const res = await MetadataConversationsModel.create({
            conversationNumber: userConversationsNumber + 1,
            experimentId,
            userId,
            agent: user.isAdmin ? agent : user.agent,
            maxMessages: user.isAdmin ? undefined : experimentBoundries.maxMessages,
        });

        const firstMessage: Message = {
            role: 'assistant',
            content: user.isAdmin ? agent.firstChatSentence : user.agent.firstChatSentence,
        };
        
        // Check if this conversation starts with a proactive opener
        const hasProactiveOpener = !user.isAdmin && !!user.proactiveMemory?.injected_prompt_original;
        
        await Promise.all([
            this.createMessageDoc(firstMessage, res._id.toString(), 1, hasProactiveOpener),
            usersService.addConversation(userId),
            !user.isAdmin && experimentsService.addSession(experimentId),
        ]);

        return res._id.toString();
    };

    getConversation = async (conversationId: string, isLean = false): Promise<Message[]> => {
        const returnValues = isLean
            ? { _id: 0, role: 1, content: 1 }
            : { _id: 1, role: 1, content: 1, userAnnotation: 1, isProactiveOpener: 1 };

        const conversation = await ConversationsModel.find({ conversationId }, returnValues);

        return conversation;
    };

    updateConversationSurveysData = async (conversationId: string, data, isPreConversation: boolean) => {
        const saveField = isPreConversation ? { preConversation: data } : { postConversation: data };
        const res = await this.updateConversationMetadata(conversationId, saveField);

        return res;
    };

    getConversationMetadata = async (conversationId: string): Promise<any> => {
        const res = await MetadataConversationsModel.findOne({ _id: new mongoose.Types.ObjectId(conversationId) });
        return res;
    };

    getUserConversations = async (userId: string): Promise<any> => {
        const conversations = [];
        const metadataConversations = await MetadataConversationsModel.find({ userId }, { agent: 0 }).lean();

        for (const metadataConversation of metadataConversations) {
            const conversation = await ConversationsModel.find({
                conversationId: metadataConversation._id,
            }).lean();
            conversations.push({
                metadata: metadataConversation,
                conversation,
            });
        }

        return conversations;
    };

    finishConversation = async (conversationId: string, experimentId: string, isAdmin: boolean): Promise<void> => {
        const res = await MetadataConversationsModel.updateOne(
            { _id: new mongoose.Types.ObjectId(conversationId) },
            { $set: { isFinished: true } },
        );

        if (res.modifiedCount && !isAdmin) {
            await experimentsService.closeSession(experimentId);
        }
    };

    deleteExperimentConversations = async (experimentId: string): Promise<void> => {
        const conversationIds = await this.getExperimentConversationsIds(experimentId);
        await Promise.all([
            MetadataConversationsModel.deleteMany({ _id: { $in: conversationIds.ids } }),
            ConversationsModel.deleteMany({ conversationId: { $in: conversationIds.strIds } }),
        ]);
    };

    updateUserAnnotation = async (messageId: string, userAnnotation: UserAnnotation): Promise<Message> => {
        const message: Message = await ConversationsModel.findOneAndUpdate(
            { _id: messageId },
            { $set: { userAnnotation } },
            { new: true },
        );

        return message;
    };

    private updateConversationMetadata = async (conversationId, fields) => {
        try {
            const res = await MetadataConversationsModel.updateOne(
                { _id: new mongoose.Types.ObjectId(conversationId) },
                fields,
            );
            return res;
        } catch (error) {
            console.error(`updateConversationMetadata - ${error}`);
        }
    };

    private getConversationMessages = async (
        agent: IAgent,
        conversation: Message[],
        message: Message,
        userId?: string,
        conversationId?: string,
    ) => {
        let systemPrompt = { role: 'system', content: agent.systemStarterPrompt };

        // Inject proactive context on every turn of a proactive conversation (fixes "goldfish syndrome").
        // getProactiveContext returns null if this conversation is not flagged as proactive.
        if (userId && conversationId) {
            const context = await this.getProactiveContext(userId, conversationId);
            if (context) {
                systemPrompt.content +=
                    `\n\n--- Proactive Context (for your internal reference only) ---\n` +
                    `You reached out to the user in this conversation because something from a past session stayed with you. The specific memory that prompted you to reconnect:\n\n` +
                    `"${context.memory}"\n\n` +
                    `Here is an excerpt from the original conversation where that moment occurred:\n${context.transcript}\n` +
                    `---\n\n` +
                    `Carry this awareness naturally into your responses. Do not announce that you reviewed a transcript or that you "looked something up." ` +
                    `Simply let this background inform your understanding of the user — the way any attentive, caring person would when following up on something meaningful from a prior conversation.\n` +
                    `--- End of Proactive Context ---`;
            }
        }

        const beforeUserMessage = { role: 'system', content: agent.beforeUserSentencePrompt };
        const afterUserMessage = { role: 'system', content: agent.afterUserSentencePrompt };

        const messages = [
            systemPrompt,
            ...conversation,
            beforeUserMessage,
            message,
            afterUserMessage,
            { role: 'assistant', content: '' },
        ];

        return messages;
    };

    private getProactiveContext = async (userId: string, conversationId: string) => {
        try {
            console.log('[getProactiveContext] === START ===');
            console.log('[getProactiveContext] Incoming conversationId:', conversationId);
            console.log('[getProactiveContext] userId:', userId);

            // Guard: Query DB directly for the first message to check if it's a proactive opener.
            // Messages are stored as separate documents with conversationId field.
            const firstMessage = await ConversationsModel.findOne(
                { conversationId, messageNumber: 1 },
                { isProactiveOpener: 1 },
            ).lean();

            console.log('[getProactiveContext] First message flag:', firstMessage?.isProactiveOpener);

            if (!firstMessage?.isProactiveOpener) {
                console.log('[getProactiveContext] ❌ Returned NULL: isProactiveOpener is falsy');
                return null;
            }

            const user = await usersService.getUserById(userId);
            const proactiveMem = user.proactiveMemory;

            // Must have a linked memory to fetch context from
            const memoryId = proactiveMem?.linked_memory_id;
            console.log('[getProactiveContext] Linked Memory ID:', memoryId || 'NULL');

            if (!memoryId) {
                console.log('[getProactiveContext] ❌ Returned NULL: no linked_memory_id');
                return null;
            }

            // Locate the specific memory object that triggered this proactive chat.
            const memory = proactiveMem.emotional_memories?.find((m) => m.memory_id === memoryId);
            
            if (!memory) {
                console.log('[getProactiveContext] ❌ Returned NULL: memory not found in emotional_memories');
                console.log('[getProactiveContext] Available memory IDs:', 
                    proactiveMem.emotional_memories?.map(m => m.memory_id) || []);
                return null;
            }

            const memoryContent = memory.content;
            console.log('[getProactiveContext] Memory found:', memoryContent?.substring(0, 100) + '...');
            
            // memory.conversationId is the *original* past conversation this memory was extracted from.
            const originConvId = memory.conversationId;
            console.log('[getProactiveContext] Origin conversation ID:', originConvId || 'NULL');

            if (!originConvId) {
                console.log('[getProactiveContext] ❌ Returned NULL: memory has no conversationId');
                return null;
            }

            // Fetch the last 7 messages (both roles) from the original past conversation.
            const rawMessages = await ConversationsModel.find(
                { conversationId: originConvId, role: { $in: ['user', 'assistant'] } },
                { content: 1, role: 1, messageNumber: 1, _id: 0 },
            )
                .sort({ messageNumber: -1 })
                .limit(7)
                .lean();

            console.log('[getProactiveContext] Historical messages fetched:', rawMessages?.length || 0);

            if (!rawMessages || rawMessages.length === 0) {
                console.log('[getProactiveContext] ❌ Returned NULL: no messages in origin conversation');
                return null;
            }

            // Re-sort ascending so the transcript reads chronologically.
            const transcript = rawMessages
                .reverse()
                .map((m) => `${m.role === 'user' ? 'User' : 'Assistant'}: ${m.content}`)
                .join('\n');

            console.log('[getProactiveContext] Transcript length:', transcript.length, 'characters');
            console.log('[getProactiveContext] ✅ SUCCESS: Returning formatted context');
            return { memory: memoryContent, transcript };
        } catch (error) {
            console.error('[getProactiveContext] ❌ Exception thrown:', error);
            return null;
        }
    };

    private createMessageDoc = async (
        message: Message,
        conversationId: string,
        messageNumber: number,
        isProactiveOpener: boolean = false,
    ): Promise<Message> => {
        const res = await ConversationsModel.create({
            content: message.content,
            role: message.role,
            conversationId,
            messageNumber,
            isProactiveOpener,
        });

        return { _id: res._id, role: res.role, content: res.content, userAnnotation: res.userAnnotation, isProactiveOpener: res.isProactiveOpener };
    };

    private getChatRequest = (agent: IAgent, messages: Message[]) => {
        const chatCompletionsReq = {
            messages,
            model: agent.model,
        };

        if (agent.maxTokens) chatCompletionsReq['max_tokens'] = agent.maxTokens;
        if (agent.frequencyPenalty) chatCompletionsReq['frequency_penalty'] = agent.frequencyPenalty;
        if (agent.topP) chatCompletionsReq['top_p'] = agent.topP;
        if (agent.temperature) chatCompletionsReq['temperature'] = agent.temperature;
        if (agent.presencePenalty) chatCompletionsReq['presence_penalty'] = agent.presencePenalty;
        if (agent.stopSequences) chatCompletionsReq['stop'] = agent.stopSequences;

        return chatCompletionsReq;
    };

    private getExperimentConversationsIds = async (
        experimentId: string,
    ): Promise<{ ids: mongoose.Types.ObjectId[]; strIds: string[] }> => {
        const conversationsIds = await MetadataConversationsModel.aggregate([
            { $match: { experimentId } },
            { $project: { _id: 1, id: { $toString: '$_id' } } },
            { $group: { _id: null, ids: { $push: '$_id' }, strIds: { $push: '$id' } } },
            { $project: { _id: 0, ids: 1, strIds: 1 } },
        ]);
        return conversationsIds[0];
    };
}

export const conversationsService = new ConversationsService();
