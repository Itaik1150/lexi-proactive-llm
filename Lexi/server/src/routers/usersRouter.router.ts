import { Router } from 'express';
import { usersController } from '../controllers/usersController.controller';
import { requireAdmin } from '../utils/adminMiddleware';
import { requireUser } from '../utils/authMiddleware';

export const usersRouter = () => {
    const router = Router();
    router.post('/create', usersController.createUser);
    router.post('/login', usersController.login);
    router.post('/logout', usersController.logout);
    router.put('/agent', requireAdmin, usersController.updateUsersAgent);
    router.get('/user', usersController.getActiveUser);
    router.get('/validate', usersController.validateUserName);
    // A push token identifies where a participant's notifications go, so only the logged-in user may set their own.
    router.post('/fcm-token', requireUser, usersController.updateFCMToken);
    router.post('/register-device', requireUser, usersController.registerDevice);
    router.post('/prolific-id', requireUser, usersController.linkProlificId);
    router.get('/study-status', requireUser, usersController.getStudyStatus);
    router.post('/onboarding-code-seen', requireUser, usersController.ackOnboardingCode);
    router.post('/end-survey', requireUser, usersController.submitEndSurvey);

    return router;
};
