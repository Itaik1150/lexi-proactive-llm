import { Router } from 'express';
import { joinController } from '../controllers/joinController';
import { rateLimitByIp } from '../utils/rateLimit';

export const joinRouter = () => {
    const router = Router();
    // One link for the whole study: assigns each Prolific participant to one of the listed experiments
    // at random (balanced) and sends them to that experiment's landing page. Must come before '/:experimentId'.
    router.get('/study', rateLimitByIp(120, 10 * 60 * 1000), joinController.randomStudyLink);
    // Landing page: participant opens this URL in their browser
    router.get('/:experimentId', joinController.landingPage);
    // Download trigger: logs IP + experimentId, then redirects to APK file
    // Generous limit: a whole room of participants can share one public IP.
    router.get('/:experimentId/download', rateLimitByIp(60, 10 * 60 * 1000), joinController.downloadApk);
    return router;
};
