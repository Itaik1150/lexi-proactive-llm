import { Router } from 'express';
import { usersController } from '../controllers/usersController.controller';
import { requireUser } from '../utils/authMiddleware';

export const usersRouter = () => {
    const router = Router();
    router.post('/create', usersController.createUser);
    router.post('/login', usersController.login);
    router.post('/logout', usersController.logout);
    router.put('/agent', usersController.updateUsersAgent);
    router.get('/user', usersController.getActiveUser);
    router.get('/validate', usersController.validateUserName);
    // A push token identifies where a participant's notifications go, so only the logged-in user may set their own.
    router.post('/fcm-token', requireUser, usersController.updateFCMToken);
    router.post('/register-device', requireUser, usersController.registerDevice);

    return router;
};
