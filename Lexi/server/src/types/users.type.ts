import mongoose from 'mongoose';
import { IAgent } from '../types/agents.type';

export interface IUser {
    _id?: mongoose.Types.ObjectId;
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
    agent: IAgent;
    proactiveGroup?: 'affective' | 'generic' | 'reactive';
    fcmToken?: string;
    fcmTokenUpdatedAt?: Date;
    isProactive?: boolean;
    is_demo_finished?: boolean;
    proactiveMemory?: {
        injected_prompt_original?: string;
        injected_prompt_reset_after?: Date;
        linked_memory_id?: string;
        linked_conversation_id?: string;
        emotional_memories?: Array<{
            memory_id: string;
            content: string;
            affective_score: number;
            conversationId: string;
            timestamp_iso: string;
            used: boolean;
        }>;
        [key: string]: any;
    };
    conversationSummaries?: string[];
}
