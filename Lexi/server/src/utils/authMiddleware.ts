import { NextFunction, Request, Response } from 'express';
import jwt from 'jsonwebtoken';

/**
 * Requires a valid login cookie (the same JWT that /users/login and /users/create set).
 * On success the authenticated user's id is available as `res.locals.userId`; handlers must
 * use that id and never one taken from the request body.
 */
export const requireUser = (req: Request, res: Response, next: NextFunction): void => {
    const token = req.cookies?.token;
    if (!token) {
        res.status(401).json({ message: 'Not authenticated' });
        return;
    }

    try {
        const decoded = jwt.verify(token, process.env.JWT_SECRET_KEY) as jwt.JwtPayload;
        if (!decoded || !decoded.id) {
            throw new Error('Token has no user id');
        }
        res.locals.userId = String(decoded.id);
        next();
    } catch (error) {
        res.status(401).json({ message: 'Not authenticated' });
    }
};

type AdminLookup = (userId: string) => Promise<{ isAdmin?: boolean } | null | undefined>;

/**
 * Requires a valid login cookie of an ADMIN account (docs/REVIEW.md S9, S12). Everything that reads
 * or changes experiments, agents, forms or exported participant data must run behind this.
 * 401 = not logged in, 403 = logged in but not an admin.
 */
export const createRequireAdmin =
    (findUser: AdminLookup) =>
    async (req: Request, res: Response, next: NextFunction): Promise<void> => {
        let allowed = false;
        requireUser(req, res, () => (allowed = true));
        if (!allowed) return; // requireUser already answered 401
        try {
            const user = await findUser(res.locals.userId);
            if (!user || user.isAdmin !== true) {
                res.status(403).json({ message: 'Admin only' });
                return;
            }
            next();
        } catch (error) {
            res.status(403).json({ message: 'Admin only' });
        }
    };
