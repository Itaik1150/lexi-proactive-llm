import { Router } from 'express';
import { experimentsController } from '../controllers/experimentsController.controller';
import { requireAdmin } from '../utils/adminMiddleware';

export const experimentsRouter = () => {
    const router = Router();
    // Admin only (S9, S12): the full experiment (prompts, weights, schedule) and every change.
    // Open to participants' browsers: match-session, public, features (two flags), content, forms.
    router.get('/', requireAdmin, experimentsController.getExperiments);
    router.get('/agent', requireAdmin, experimentsController.getAllExperimentsByAgentId);
    router.get('/match-session', experimentsController.matchSession);
    router.get('/:id', requireAdmin, experimentsController.getExperiment);
    router.get('/:id/public', experimentsController.getExperimentPublicInfo);
    router.get('/:id/features', experimentsController.getExperimentFeatures);
    router.get('/:id/content', experimentsController.getExperimentContent);
    router.get('/:id/registrationForm', experimentsController.getRegistrationForm);
    router.get('/:id/conversationForms', experimentsController.getConversationForms);
    router.post('/create', requireAdmin, experimentsController.createExperiment);
    router.put('/', requireAdmin, experimentsController.updateExperiment);
    router.put('/status', requireAdmin, experimentsController.updateExperimentsStatus);
    router.put('/content', requireAdmin, experimentsController.updateExperimentDisplaySetting);
    router.delete('/:id', requireAdmin, experimentsController.deleteExperiment);

    return router;
};
