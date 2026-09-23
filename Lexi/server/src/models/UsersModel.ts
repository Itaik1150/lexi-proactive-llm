import { Schema } from 'mongoose';
import { mongoDbProvider } from '../mongoDBProvider';
import { IUser } from '../types';
import { agentsSchema } from './AgentsModel';

export const userSchema = new Schema<IUser>(
    {
        experimentId: {
            type: String,
            required() {
                return !this.isAdmin;
            },
        },
        username: { type: String, required: true, unique: true },
        age: { type: Number },
        gender: { type: String },
        biologicalSex: { type: String },
        maritalStatus: { type: String },
        childrenNumber: { type: Number },
        nativeEnglishSpeaker: { type: Boolean },
        createdAt: { type: Date, default: Date.now },
        timestamp: { type: Number, default: () => Date.now() },
        isAdmin: { type: Boolean, default: () => false },
        password: { type: String },
        numberOfConversations: { type: Number, default: () => 0 },
        agent: {
            type: agentsSchema,
            required() {
                return !this.isAdmin;
            },
        },
        proactiveGroup: { 
            type: String, 
            enum: ['affective', 'generic', 'reactive'],
            required: false,
        },
        fcmToken: { type: String },
        fcmTokenUpdatedAt: { type: Date },
        isProactive: { type: Boolean, default: false }, // Will be set in services when FCM token is added
        is_demo_finished: { type: Boolean, default: false },
        conversationSummaries: { type: [String], default: [] }, // Dual-Tier Memory: rolling summaries
    },
    { versionKey: false },
);

export const UsersModel = mongoDbProvider.getModel('users', userSchema);
