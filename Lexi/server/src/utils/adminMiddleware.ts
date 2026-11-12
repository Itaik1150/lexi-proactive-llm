import { usersService } from '../services/users.service';
import { createRequireAdmin } from './authMiddleware';

/** Admin-only gate for routes (docs/REVIEW.md S9, S12): the login cookie must belong to an admin account. */
export const requireAdmin = createRequireAdmin((userId) => usersService.getUserById(userId));
