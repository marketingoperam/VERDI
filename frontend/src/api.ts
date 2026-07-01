const API = import.meta.env.VITE_API_URL || "";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export type Competitor = {
  id: number;
  name: string;
  region?: string;
  brand_keywords: string[];
  money_keywords: string[];
  google_queries: string[];
  yandex_queries: string[];
  vk_domains: string[];
  vk_owner_ids: string[];
  telegram_channels: string[];
  is_active: boolean;
};

export type Analysis = {
  entity_type?: string;
  offer?: string;
  cta?: string;
  pain_points?: string[];
  tone?: string;
  hooks?: string[];
  intent?: string;
  sentiment?: string;
  summary?: string;
  is_competitor_related?: boolean;
};

export type Finding = {
  id: number;
  competitor_id?: number;
  competitor_name?: string;
  source: string;
  result_type: string;
  title?: string;
  raw_text?: string;
  snippet?: string;
  url?: string;
  channel_name?: string;
  position?: number;
  views?: number;
  published_at?: string;
  collected_at: string;
  analysis?: Analysis;
};

export type Settings = {
  ai_base_url?: string;
  ai_api_key?: string;
  ai_model?: string;
  google_api_key?: string;
  google_cx?: string;
  yandex_api_key?: string;
  yandex_folder_id?: string;
  vk_access_token?: string;
  telegram_api_id?: number;
  telegram_api_hash?: string;
  monitor_interval_hours: number;
  google_enabled: boolean;
  yandex_enabled: boolean;
  vk_enabled: boolean;
  telegram_enabled: boolean;
};

export const api = {
  getCompetitors: () => request<Competitor[]>("/api/v1/competitors"),
  createCompetitor: (data: Partial<Competitor>) =>
    request<Competitor>("/api/v1/competitors", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  deleteCompetitor: (id: number) =>
    request<void>(`/api/v1/competitors/${id}`, { method: "DELETE" }),
  getFindings: (params: Record<string, string | number | boolean | undefined>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== "") qs.set(k, String(v));
    });
    return request<{ items: Finding[]; total: number }>(`/api/v1/findings?${qs}`);
  },
  markIrrelevant: (id: number) =>
    request<void>(`/api/v1/findings/${id}/irrelevant`, { method: "POST" }),
  runSearch: (collector: string) =>
    request<{ task_id: string; message: string }>(`/api/v1/search/run-${collector}`, {
      method: "POST",
    }),
  getSummary: () =>
    request<{
      total_24h: number;
      google_24h: number;
      yandex_24h: number;
      vk_24h: number;
      telegram_24h: number;
      by_competitor: { name: string; count: number }[];
    }>("/api/v1/analytics/summary"),
  getTrends: () => request<{ daily: { day: string; source: string; cnt: number }[] }>("/api/v1/analytics/trends"),
  getSettings: () => request<Settings>("/api/v1/settings"),
  updateSettings: (data: Partial<Settings>) =>
    request<Settings>("/api/v1/settings", { method: "PUT", body: JSON.stringify(data) }),
};

export const sourceIcon: Record<string, string> = {
  google: "G",
  yandex: "Я",
  vk: "VK",
  telegram: "TG",
};

export const sourceColor: Record<string, string> = {
  google: "bg-blue-600",
  yandex: "bg-red-600",
  vk: "bg-sky-600",
  telegram: "bg-cyan-500",
};
