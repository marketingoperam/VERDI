import { useEffect, useState } from "react";
import { api, type Settings } from "../api";

const FIELDS: { key: keyof Settings; label: string; type?: string }[] = [
  { key: "ai_base_url", label: "AI Base URL" },
  { key: "ai_api_key", label: "AI API Key", type: "password" },
  { key: "ai_model", label: "AI Model" },
  { key: "google_api_key", label: "Google API Key", type: "password" },
  { key: "google_cx", label: "Google CX" },
  { key: "yandex_api_key", label: "Yandex API Key", type: "password" },
  { key: "yandex_folder_id", label: "Yandex Folder ID" },
  { key: "vk_access_token", label: "VK Token", type: "password" },
  { key: "telegram_api_id", label: "Telegram API ID", type: "number" },
  { key: "telegram_api_hash", label: "Telegram API Hash", type: "password" },
  { key: "monitor_interval_hours", label: "Интервал мониторинга (часы)", type: "number" },
];

const TOGGLES: { key: keyof Settings; label: string }[] = [
  { key: "google_enabled", label: "Google" },
  { key: "yandex_enabled", label: "Yandex" },
  { key: "vk_enabled", label: "VK" },
  { key: "telegram_enabled", label: "Telegram" },
];

export default function SettingsPage() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getSettings().then(setSettings);
  }, []);

  if (!settings) return <p className="text-slate-400">Загрузка...</p>;

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.updateSettings(settings);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Настройки</h2>
        <p className="text-slate-400 text-sm">API-ключи и расписание мониторинга</p>
      </div>

      <form onSubmit={save} className="space-y-4 bg-slate-900 border border-slate-800 rounded-xl p-5">
        {FIELDS.map(({ key, label, type }) => (
          <label key={key} className="block text-sm">
            <span className="text-slate-400 mb-1 block">{label}</span>
            <input
              type={type || "text"}
              className="w-full bg-slate-800 rounded-lg px-3 py-2"
              value={String(settings[key] ?? "")}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  [key]:
                    type === "number" ? Number(e.target.value) || 0 : e.target.value,
                })
              }
            />
          </label>
        ))}

        <div className="grid grid-cols-2 gap-3 pt-2">
          {TOGGLES.map(({ key, label }) => (
            <label key={key} className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={!!settings[key]}
                onChange={(e) => setSettings({ ...settings, [key]: e.target.checked })}
              />
              {label} включён
            </label>
          ))}
        </div>

        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded-lg text-sm">
          Сохранить
        </button>
        {saved && <span className="text-emerald-400 text-sm ml-3">Сохранено</span>}
      </form>
    </div>
  );
}
