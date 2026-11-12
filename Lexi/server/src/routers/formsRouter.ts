import { requireAdmin } from '../utils/adminMiddleware';
import { Router } from 'express';
import { formsController } from '../controllers/formsController';

export const formsRouter = () => {
    const router = Router();
    router.post('/', requireAdmin, formsController.saveForm);
    router.get('/', requireAdmin, formsController.getForms);
    router.get('/:id', requireAdmin, formsController.getForm);
    router.put('/', requireAdmin, formsController.updateForm);
    router.delete('/:id', requireAdmin, formsController.deleteForm);

    return router;
};
