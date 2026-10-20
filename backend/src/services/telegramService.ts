/**
 * Telegram notification service for StockSentinel.
 *
 * Exposes a typed `sendTestMessage()` function that POSTs a test message
 * to the Telegram Bot API using node-fetch. Returns a structured result
 * rather than throwing so callers can handle errors gracefully.
 */

// Global fetch is natively available in Node 18+

/** Shape of a successful Telegram sendMessage response */
interface TelegramOkResponse {
  ok: true;
  result: {
    message_id: number;
    [key: string]: unknown;
  };
}

/** Shape of a failed Telegram API response */
interface TelegramErrorResponse {
  ok: false;
  error_code: number;
  description: string;
}

type TelegramApiResponse = TelegramOkResponse | TelegramErrorResponse;

/** Return value for sendTestMessage() */
export interface SendTestResult {
  success: boolean;
  message_id?: number;
  error?: string;
}

/**
 * Send a test message via the Telegram Bot API.
 *
 * @param botToken - Telegram bot token (from @BotFather)
 * @param chatId   - Target chat / channel ID (numeric string or @channel_name)
 * @param message  - Optional custom message text (defaults to a canned test string)
 * @returns SendTestResult indicating success or failure with error description
 */
export async function sendTestMessage(
  botToken: string,
  chatId: string,
  message?: string,
): Promise<SendTestResult> {
  const text =
    message ??
    `🟢 <b>StockSentinel — Telegram Test</b>\n\n` +
      `✅ Bot credentials verified successfully.\n` +
      `📡 Your Telegram alerts are configured correctly.\n\n` +
      `<i>Sent at: ${new Date().toISOString()}</i>`;

  const url = `https://api.telegram.org/bot${botToken}/sendMessage`;

  let raw: TelegramApiResponse;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: chatId,
        text,
        parse_mode: 'HTML',
      }),
    });

    raw = (await response.json()) as TelegramApiResponse;
  } catch (networkError: unknown) {
    const msg =
      networkError instanceof Error
        ? networkError.message
        : 'Unknown network error contacting Telegram API';
    return { success: false, error: msg };
  }

  if (raw.ok) {
    return { success: true, message_id: raw.result.message_id };
  }

  return {
    success: false,
    error: `Telegram API error ${raw.error_code}: ${raw.description}`,
  };
}
