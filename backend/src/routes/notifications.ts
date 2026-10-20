/**
 * Notifications routes — /api/notifications/*
 *
 * Endpoints:
 *   POST /api/notifications/telegram-test — verify bot credentials by sending a test message
 */

import { Router, Request, Response, NextFunction } from 'express';
import { sendTestMessage } from '../services/telegramService';

const router = Router();

// ---------------------------------------------------------------------------
// POST /api/notifications/telegram-test
// ---------------------------------------------------------------------------
router.post(
  '/telegram-test',
  async (req: Request, res: Response, next: NextFunction): Promise<void> => {
    try {
      // Use strictly server-configured credentials to prevent open relay abuse
      const botToken: string = process.env.TELEGRAM_BOT_TOKEN || '';
      const chatId: string = process.env.TELEGRAM_CHAT_ID || '';

      // Validate that credentials are configured on server
      if (!botToken || !chatId) {
        res.status(400).json({
          success: false,
          error: {
            code: 'MISSING_CREDENTIALS',
            message:
              'Telegram bot token or chat ID is not configured on the server. ' +
              'Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.',
          },
        });
        return;
      }

      // Dispatch standard canned test message via the Telegram Bot API
      const result = await sendTestMessage(botToken, chatId);

      if (result.success) {
        res.json({
          success: true,
          message: 'Test message sent successfully to Telegram.',
          telegram_message_id: result.message_id,
        });
      } else {
        // Telegram returned an error — treat as a bad gateway
        res.status(502).json({
          success: false,
          error: {
            code: 'TELEGRAM_API_ERROR',
            message: result.error ?? 'Telegram API returned an unknown error.',
          },
        });
      }
    } catch (err) {
      next(err);
    }
  },
);

export default router;
