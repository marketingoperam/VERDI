export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://127.0.0.1:3001';
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? 'http://127.0.0.1:3001';
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
    throw new Error(err.message ?? 'Request failed');
  }
  return res.json() as Promise<T>;
}
