export const normalizeBody = (text: string): string =>
  text
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .replace(/[^\p{L}\p{N}\s]/gu, '')
    .trim();

export const randomDelay = (minMs: number, maxMs: number): number =>
  Math.floor(Math.random() * (maxMs - minMs + 1)) + minMs;

/** Telegram peer id; ignore UUIDs mistakenly stored as externalChatId. */
export const resolveTelegramPeerId = (
  externalChatId: string | null | undefined,
  telegramUserId: string | bigint,
): string => {
  const peer = String(telegramUserId);
  if (!externalChatId || externalChatId.includes('-')) return peer;
  return externalChatId;
};

export const serializeBigInt = (value: unknown): unknown => {
  if (value instanceof Date) return value.toISOString();
  if (typeof value === 'bigint') return value.toString();
  if (Array.isArray(value)) return value.map(serializeBigInt);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([k, v]) => [k, serializeBigInt(v)]),
    );
  }
  return value;
};
