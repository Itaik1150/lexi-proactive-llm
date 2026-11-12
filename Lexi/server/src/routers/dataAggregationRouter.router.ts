import { requireAdmin } from '../utils/adminMiddleware';
import { Router } from 'express';
import { dataAggregationController } from '../controllers/dataAggregationController.controller';

export const dataAggregationRouter = () => {
    const router = Router();
    router.get('/', requireAdmin, dataAggregationController.getExperimentData);
    router.get('/excel', requireAdmin, dataAggregationController.getExperimentExcel);

    return router;
};
