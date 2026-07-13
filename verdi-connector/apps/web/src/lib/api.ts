export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:3001';
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'http://127.0.0.1:3001';

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

function clearSessionAndRedirectToLogin(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem('verdi_token');
  if (window.location.pathname !== '/') {
    window.location.replace('/');
  }
}

/** Human-readable Russian message for browser/network/proxy failures. */
export function humanizeNetworkError(err: unknown): string {
  const raw = err instanceof Error ? err.message : String(err ?? '');
  const lower = raw.toLowerCase();

  if (err instanceof DOMException && err.name === 'AbortError') {
    return 'Синхронизация превысила лимит ожидания. Попробуйте ещё раз — API на Render обрывает долгие запросы.';
  }
  if (
    lower.includes('failed to fetch') ||
    lower.includes('networkerror') ||
    lower.includes('load failed') ||
    lower.includes('network request failed')
  ) {
    return 'Не удалось связаться с API (сеть, CORS или таймаут Render ~100с). Обновите страницу и повторите — долгий синк мог оборваться.';
  }
  if (lower.includes('telegram sync timeout') || lower.includes('sync timeout')) {
    return 'Синхронизация Telegram не успела за отведённое время. Повторите или синхронизируйте один аккаунт.';
  }
  if (lower.includes('transport_disconnected')) {
    return 'Telegram-воркер отключён (сессия не на Render или AuthKeyDuplicated). Проверьте, что аккаунт не запущен локально одновременно.';
  }
  return raw || 'Неизвестная ошибка запроса';
}

type ApiInit = RequestInit & { timeoutMs?: number };

export async function api<T>(path: string, token?: string, init?: ApiInit): Promise<T> {
  const { timeoutMs, ...fetchInit } = init ?? {};
  const controller = timeoutMs ? new AbortController() : null;
  const timer =
    controller && timeoutMs
      ? setTimeout(() => controller.abort(), timeoutMs)
      : null;

  try {
    const res = await fetch(`${API_URL}/api${path}`, {
      ...fetchInit,
      signal: controller?.signal ?? fetchInit.signal,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(fetchInit.headers ?? {}),
      },
      cache: 'no-store',
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      const message = humanizeNetworkError(err.message ?? 'Request failed');
      if (res.status === 401) {
        // JWT expired / JWT_SECRET rotated after Render redeploy
        clearSessionAndRedirectToLogin();
        throw new ApiError(message, 401);
      }
      throw new ApiError(message, res.status);
    }
    return res.json() as Promise<T>;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError(humanizeNetworkError(err), 0);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
