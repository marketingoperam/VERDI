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

export async function api<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}/api${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
    cache: 'no-store',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }));
    const message = err.message ?? 'Request failed';
    if (res.status === 401) {
      // JWT expired / JWT_SECRET rotated after Render redeploy
      clearSessionAndRedirectToLogin();
      throw new ApiError(message, 401);
    }
    throw new ApiError(message, res.status);
  }
  return res.json() as Promise<T>;
}
