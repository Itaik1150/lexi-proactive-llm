import { CookieOptions, Request, Response } from 'express';
import mongoose from 'mongoose';
import { usersService } from '../services/users.service';
import { requestHandler } from '../utils/requestHandler';

const isProduction = process.env.NODE_ENV === 'production';
const cookieConfig: CookieOptions = {
    httpOnly: true,
    sameSite: isProduction ? 'none' : 'lax',
    secure: isProduction,
    maxAge: 30 * 24 * 60 * 60 * 1000, // 30 days — participants should stay logged in throughout the experiment
};

class UsersController {
    createUser = requestHandler(
        async (req: Request, res: Response) => {
            const { userInfo, experimentId, fcmToken } = req.body;
            const { user, token } = await usersService.createUser(userInfo, experimentId, fcmToken);

            res.cookie('token', token, cookieConfig);
            res.status(200).send(user);
        },
        (req, res, error) => {
            if (error.code === 11000) {
                res.status(409).json({ message: 'User Already Exists' });
                return;
            }
            if (error.code === 403) {
                res.status(403).json({ message: 'Experiment Is Not Acive' });
                return;
            }
            res.status(500).json({ message: 'Error creating user' });
        },
    );

    login = requestHandler(
        async (req: Request, res: Response) => {
            const { username, userPassword, experimentId } = req.body;
            const { token, user } = await usersService.login(username, experimentId, userPassword);

            res.cookie('token', token, cookieConfig);
            res.status(200).send({ token, user });
        },
        (req, res, error) => {
            if (error.code === 401) {
                res.status(error.code).json({ message: error.message });
                return;
            }
            res.status(500).json({ message: 'Error creating user' });
        },
    );

    getActiveUser = requestHandler(async (req: Request, res: Response) => {
        if (!req.cookies || !req.cookies.token) {
            throw Object.assign(new Error('No token provided.'), { status: 401 });
        }

        const { token } = req.cookies;
        const { user, newToken } = await usersService.getActiveUser(token);

        res.cookie('token', newToken, cookieConfig);
        res.status(200).send(user);

        // Fire-and-forget: reset expired proactive prompt if 2h have passed
        this.expireProactivePromptIfNeeded(String(user._id)).catch(() => {});
    });

    private async expireProactivePromptIfNeeded(userId: string): Promise<void> {
        try {
            const db = mongoose.connection.db;
            const now = new Date();

            const result = await db.collection('users').findOneAndUpdate(
                {
                    _id: new mongoose.Types.ObjectId(userId),
                    'proactiveMemory.injected_prompt_reset_after': { $lte: now },
                },
                [
                    {
                        $set: {
                            'agent.firstChatSentence': '$proactiveMemory.injected_prompt_original',
                            'proactiveMemory.injected_prompt_original':    '$$REMOVE',
                            'proactiveMemory.injected_prompt_reset_after': '$$REMOVE',
                        },
                    },
                ],
                { projection: { username: 1 } },
            );
            if (result) {
                console.log(`[proactive] expired prompt reset for user ${userId} on app open`);
            }
        } catch (_) {
            // Non-critical
        }
    }

    logout = requestHandler(async (req: Request, res: Response) => {
        res.clearCookie('token', { httpOnly: true, sameSite: 'none', secure: true });
        res.status(200).send({ message: 'Logged out successfully' });
    });

    validateUserName = requestHandler(
        async (req, res) => {
            const username = req.query.username as string;
            const experimentId = req.query.experimentId as string;
            const user = await usersService.getUserByName(username, experimentId);
            if (user) {
                const error = new Error('User Already Exist');
                error['code'] = 409;
                throw error;
            }

            res.status(200).send(true);
        },
        (req, res, error) => {
            if (error.code === 409) {
                res.status(409).json({ message: 'User Already Exists' });
            }
        },
    );

    updateUsersAgent = requestHandler(async (req: Request, res: Response) => {
        const { agent } = req.body;
        await usersService.updateUsersAgent(agent);
        res.status(200).send();
    });

    /**
     * Stores the push token for the AUTHENTICATED user (res.locals.userId, set by requireUser).
     * A userId in the body is only accepted if it matches; the response never contains the user record.
     */
    private saveFcmToken(successMessage: string, failureMessage: string) {
        return requestHandler(
            async (req: Request, res: Response) => {
                const { userId: claimedUserId, fcmToken } = req.body;
                const userId: string = res.locals.userId;

                if (!fcmToken) {
                    const error = new Error('fcmToken is required');
                    error['code'] = 400;
                    throw error;
                }
                if (claimedUserId && String(claimedUserId) !== userId) {
                    const error = new Error('Cannot change the token of a different user');
                    error['code'] = 403;
                    throw error;
                }

                await usersService.updateFCMToken(userId, fcmToken);
                res.status(200).json({ message: successMessage });
            },
            (req, res, error) => {
                if (error.code === 404) {
                    res.status(404).json({ message: 'User not found' });
                    return;
                }
                if (error.code === 400) {
                    res.status(400).json({ message: error.message });
                    return;
                }
                if (error.code === 403) {
                    res.status(403).json({ message: 'Forbidden' });
                    return;
                }
                res.status(500).json({ message: failureMessage });
            },
        );
    }

    updateFCMToken = this.saveFcmToken('FCM token updated successfully', 'Error updating FCM token');

    registerDevice = this.saveFcmToken('Device registered successfully', 'Error registering device');
}

export const usersController = new UsersController();
