import { Request, Response } from 'express';
import mongoose from 'mongoose';

const APK_DOWNLOAD_URL =
    process.env.APK_DOWNLOAD_URL ||
    'https://github.com/Itaik1150/Master-Thesis-2026-2027-CodeBase/releases/download/v1.0-generic/app-debug.apk';

const FRONTEND_BASE_URL =
    process.env.FRONTEND_URL || 'https://master-thesis-2026-2027-code-base.vercel.app';

// Experiment ids are 24-character hex ObjectIds. Anything else is rejected before it reaches HTML or the database.
const OBJECT_ID_PATTERN = /^[a-f0-9]{24}$/i;

const escapeHtml = (value: string): string =>
    value
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');

const experimentExists = async (experimentId: string): Promise<boolean> => {
    if (!OBJECT_ID_PATTERN.test(experimentId)) return false;
    const found = await mongoose.connection.db
        .collection('experiments')
        .findOne({ _id: new mongoose.Types.ObjectId(experimentId) }, { projection: { _id: 1 } });
    return !!found;
};

const sendInvalidLink = (res: Response): void => {
    res.status(404).type('text/plain').send('This invitation link is not valid. Please ask the researcher for a new one.');
};

// Strip IPv4-mapped IPv6 prefix so ::ffff:1.2.3.4 and 1.2.3.4 match.
const normalizeIp = (ip: string): string =>
    ip.startsWith('::ffff:') ? ip.slice(7) : ip;

// Extract the real client IP, accounting for Render's reverse proxy.
const getClientIp = (req: Request): string => {
    const forwarded = req.headers['x-forwarded-for'];
    const raw = forwarded
        ? (Array.isArray(forwarded) ? forwarded[0] : forwarded).split(',')[0].trim()
        : req.socket?.remoteAddress || req.ip || 'unknown';
    return normalizeIp(raw);
};

// Minimal mobile-first landing page returned as raw HTML.
const buildLandingPage = (experimentId: string): string => `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Join Lexi Experiment</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background: #f0f4f8;
      display: flex; justify-content: center; align-items: center;
      min-height: 100vh; padding: 24px;
    }
    .card {
      background: #fff;
      border-radius: 16px;
      box-shadow: 0 4px 24px rgba(0,0,0,0.10);
      padding: 40px 32px;
      max-width: 420px;
      width: 100%;
      text-align: center;
    }
    .logo { font-size: 2.4rem; font-weight: 700; color: #1a73e8; margin-bottom: 8px; }
    .subtitle { color: #555; font-size: 0.95rem; margin-bottom: 32px; line-height: 1.5; }
    .btn {
      display: inline-block;
      background: #1a73e8;
      color: #fff;
      font-size: 1.05rem;
      font-weight: 600;
      padding: 14px 32px;
      border-radius: 50px;
      text-decoration: none;
      transition: background 0.2s;
    }
    .btn:hover { background: #1558b0; }
    .note { color: #888; font-size: 0.82rem; margin-top: 20px; line-height: 1.5; }
    .steps { text-align: left; margin: 24px 0 8px; color: #444; font-size: 0.9rem; line-height: 2; }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">Lexi</div>
    <p class="subtitle">
      You have been invited to participate in an academic research study
      at <strong>Ben-Gurion University of the Negev (BGU)</strong>.
    </p>
    <a class="btn" href="/join/${escapeHtml(experimentId)}/download">
      Download &amp; Join
    </a>
    <div class="steps">
      <strong>After downloading:</strong><br/>
      1. Open the downloaded file to install Lexi.<br/>
      2. If prompted, allow installation from unknown sources.<br/>
      3. Open Lexi — you will be connected automatically.
    </div>
    <p class="note">
      The app requires Android 8.0 or above.<br/>
      All interactions are fully anonymous.
    </p>
  </div>
</body>
</html>`;

class JoinController {
    // GET /join/:experimentId  →  serve landing page HTML
    landingPage = async (req: Request, res: Response): Promise<void> => {
        const { experimentId } = req.params;
        try {
            if (!(await experimentExists(experimentId))) {
                sendInvalidLink(res);
                return;
            }
        } catch (err) {
            console.error('[join] experiment lookup failed:', err);
            res.status(500).type('text/plain').send('Something went wrong. Please try again.');
            return;
        }
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        res.status(200).send(buildLandingPage(experimentId));
    };

    // GET /join/:experimentId/download  →  log IP + redirect to APK
    downloadApk = async (req: Request, res: Response): Promise<void> => {
        const { experimentId } = req.params;
        const ip = getClientIp(req);

        try {
            if (!(await experimentExists(experimentId))) {
                sendInvalidLink(res);
                return;
            }
            const db = mongoose.connection.db;
            await db.collection('apk_sessions').insertOne({
                ip,
                experimentId,
                timestamp: new Date(),
                matched: false,
            });
            console.log(`[join/download] logged session — ip: "${ip}", experimentId: "${experimentId}"`);
        } catch (err) {
            console.error('[join] Failed to log apk_session:', err);
        }

        res.redirect(APK_DOWNLOAD_URL);
    };
}

export const joinController = new JoinController();
