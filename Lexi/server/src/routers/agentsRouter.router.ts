import { requireAdmin } from '../utils/adminMiddleware';
import { Router } from 'express';
import { agentsController } from '../controllers/agentsController.controller';

export const agentsRouter = () => {
    const router = Router();
    router.post('/', requireAdmin, agentsController.saveAgent);
    router.get('/', requireAdmin, agentsController.getAgents);
    router.get('/:id', requireAdmin, agentsController.getAgentLean);
    router.put('/', requireAdmin, agentsController.updateAgent);
    router.delete('/:id', requireAdmin, agentsController.deleteAgent);

    return router;
};
