import { Request, Response } from 'express';
import mongoose from 'mongoose';
import { conversationsService } from '../services/conversations.service';
import { experimentsService } from '../services/experiments.service';
import { formsService } from '../services/forms.service';
import { usersService } from '../services/users.service';
import { matchCurrentDevice } from '../services/sessionMatching';
import { getClientIp } from '../utils/clientIp';
import { requestHandler } from '../utils/requestHandler';

// Strip IPv4-mapped IPv6 prefix so ::ffff:1.2.3.4 and 1.2.3.4 match.

class ExperimentsController {
    getExperiments = requestHandler(async (req: Request, res: Response) => {
        const page = req.query.page as string;
        const limit = req.query.limit as string;
        const experiments = await experimentsService.getExperiments(page, limit);
        res.status(200).send(experiments);
    });

    getExperiment = requestHandler(async (req: Request, res: Response) => {
        const experimentId = req.params.id as string;
        const experiments = await experimentsService.getExperiment(experimentId);
        res.status(200).send(experiments);
    });

    getExperimentContent = requestHandler(async (req: Request, res: Response) => {
        const experimentId = req.params.id as string;
        const experiment = await experimentsService.getExperiment(experimentId);
        res.status(200).send({ content: experiment.displaySettings, isActive: experiment.isActive });
    });

    createExperiment = requestHandler(async (req: Request, res: Response) => {
        const { experiment } = req.body;
        const savedExperiment = await experimentsService.createExperiment(experiment);
        res.status(200).send(savedExperiment);
    });

    updateExperimentsStatus = requestHandler(async (req: Request, res: Response) => {
        const { modifiedExperiments } = req.body;
        await experimentsService.updateExperimentsStatus(modifiedExperiments);

        // When an experiment is deactivated, set all its users to isProactive: false
        // so the Python engine stops sending them nudges immediately.
        const db = mongoose.connection.db;
        for (const exp of modifiedExperiments) {
            if (exp.isActive === false) {
                await db.collection('users').updateMany(
                    { experimentId: String(exp.id), isProactive: { $ne: false } },
                    { $set: { isProactive: false } },
                );
            }
        }

        res.status(200).send();
    });

    updateExperimentDisplaySetting = requestHandler(async (req: Request, res: Response) => {
        const { experimentId, displaySettings } = req.body;
        await experimentsService.updateExperimentDisplaySettings(experimentId, displaySettings);
        res.status(200).send();
    });

    updateExperiment = requestHandler(async (req: Request, res: Response) => {
        console.log('UPDATING EXPERIMENT:', req.body);
        const { experiment } = req.body;
        await experimentsService.updateExperiment(experiment);

        // Sync isProactive flag for all users in this experiment based on the
        // proactive toggle — handles late enables and explicit disables.
        const proactiveEnabled = experiment?.experimentFeatures?.proactiveSettings?.enabled;
        if (proactiveEnabled !== undefined) {
            const db = mongoose.connection.db;
            const filter = proactiveEnabled
                ? { experimentId: String(experiment._id), fcmToken: { $exists: true, $ne: '' }, isProactive: { $ne: true } }
                : { experimentId: String(experiment._id), isProactive: { $ne: false } };
            const result = await db.collection('users').updateMany(filter, {
                $set: { isProactive: proactiveEnabled },
            });
            if (result.modifiedCount > 0) {
                console.log(`[updateExperiment] set isProactive=${proactiveEnabled} on ${result.modifiedCount} user(s) in experiment ${experiment._id}`);
            }
        }

        res.status(200).send();
    });

    getRegistrationForm = requestHandler(async (req: Request, res: Response) => {
        const experimentId = req.params.id as string;
        const experiment = await experimentsService.getExperiment(experimentId);
        if (experiment.experimentForms?.registration) {
            const form = await formsService.getForm(experiment.experimentForms?.registration);
            res.status(200).send(form);
            return;
        }
        res.status(200).send(null);
    });

    getConversationForms = requestHandler(async (req: Request, res: Response) => {
        const experimentId = req.params.id as string;
        const experiment = await experimentsService.getExperiment(experimentId);
        const forms = await formsService.getConversationForms(
            experiment.experimentForms?.preConversation,
            experiment.experimentForms?.postConversation,
        );
        res.status(200).send(forms);
    });

    getAllExperimentsByAgentId = requestHandler(async (req: Request, res: Response) => {
        const { agentId } = req.query;
        const experiments = await experimentsService.getAllExperimentsByAgentId(agentId as string);
        res.status(200).send(experiments);
    });

    getExperimentFeatures = requestHandler(async (req: Request, res: Response) => {
        const experimentId = req.params.id as string;
        const experimentFeatures = await experimentsService.getExperimentFeatures(experimentId);

        res.status(200).send(experimentFeatures);
    });

    deleteExperiment = requestHandler(async (req: Request, res: Response) => {
        const experimentId = req.params.id as string;
        await Promise.all([
            experimentsService.deleteExperiment(experimentId),
            usersService.deleteExperimentUsers(experimentId),
            conversationsService.deleteExperimentConversations(experimentId),
        ]);

        res.status(200).send();
    });

    // Called by the Android app on first launch.
    // Links the device to the invitation link used to download the app (see services/sessionMatching.ts):
    //   200 {experimentId}                  matched
    //   200 {experimentId: null, ambiguous} the same network address downloaded for DIFFERENT experiments;
    //                                       the app then asks the participant instead of guessing
    //   404 {experimentId: null}            no recent download from this address
    matchSession = requestHandler(async (req: Request, res: Response) => {
        const result = await matchCurrentDevice(getClientIp(req));
        console.log(`[match-session] ${result.body.experimentId ? 'matched' : result.body.reason}`);
        res.status(result.status).json(result.body);
    });
}

export const experimentsController = new ExperimentsController();
