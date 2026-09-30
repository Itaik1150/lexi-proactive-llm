import bodyParser from 'body-parser';
import cookieParser from 'cookie-parser';
import cors from 'cors';
import dotenv from 'dotenv';
import express from 'express';
import { mongoDbProvider } from './mongoDBProvider';
import { agentsRouter } from './routers/agentsRouter.router';
import { conversationsRouter } from './routers/conversationsRouter.router';
import { dataAggregationRouter } from './routers/dataAggregationRouter.router';
import { experimentsRouter } from './routers/experimentsRouter.router';
import { formsRouter } from './routers/formsRouter';
import { joinRouter } from './routers/joinRouter';
import { usersRouter } from './routers/usersRouter.router';
import { usersService } from './services/users.service';
import { corsOrigin } from './utils/cors';

dotenv.config();

mongoDbProvider.initialize();

const createAdminUser = (username: string, password: string) => {
    if (!username || !password) {
        console.warn('Username and password are required');
        process.exit(1);
    }

    usersService
        .createAdminUser(username, password)
        .then(() => {
            console.log('Admin user created successfully');
            process.exit(0);
        })
        .catch((error) => {
            console.error('Error creating admin user:', error);
            process.exit(1);
        });
};

const setupServer = () => {
    const app = express();
    // Trust Render's reverse proxy so req.ip / x-forwarded-for returns the real client IP.
    app.set('trust proxy', true);
    app.use(bodyParser.json());
    const corsOptions = {
        origin: corsOrigin(),
        credentials: true,
        methods: ['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        allowedHeaders: ['Content-Type', 'Authorization', 'X-Requested-With']
    };
    app.use(cors(corsOptions));
    app.use(cookieParser());

    const PORT = Number(process.env.PORT) || 5000;
    app.use('/health', (req, res) => res.status(200).send('OK'));
    // /join serves the participant landing page — public, but validated and rate-limited (see joinRouter).
    app.use('/join', joinRouter());
    app.use('/conversations', conversationsRouter());
    app.use('/experiments', experimentsRouter());
    app.use('/users', usersRouter());
    app.use('/agents', agentsRouter());
    app.use('/dataAggregation', dataAggregationRouter());
    app.use('/forms', formsRouter());

    app.listen(PORT, '0.0.0.0', () => {
        console.log(`Server started on http://0.0.0.0:${PORT}`);
        console.log(`Local access: http://localhost:${PORT}`);
        console.log(`Emulator access: http://10.0.2.2:${PORT}`);
    });
};

if (process.argv[2] === 'create-user') {
    const [, , , username, password] = process.argv;
    createAdminUser(username, password);
} else {
    setupServer();
}
