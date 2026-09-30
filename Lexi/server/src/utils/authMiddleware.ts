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
