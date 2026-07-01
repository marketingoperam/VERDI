import { useEffect, useState } from "react";
import { api, type Competitor } from "../api";

const COLLECTORS = [
  { id: "all", label: "Все источники", desc: "Google + Yandex + VK + Telegram" },
  { id: "google", label: "Google", desc: "Органика и реклама" },
  { id: "yandex", label: "Яндекс", desc: "Поиск и Директ" },
  { id: "vk", label: "VK", desc: "Стены и поиск" },
  { id: "telegram", label: "Telegram", desc: "Каналы конкурентов" },
];

const emptyForm = {
  name: "",
  region: "225",
  brand_keywords: "",
  money_keywords: "",
  google_queries: "",
  yandex_queries: "",
  vk_domains: "",
  vk_owner_ids: "",
  telegram_channels: "",
};

function splitLines(s: string) {
  return s
    .split(/[\n,;]+/)
    .map((x) => x.trim())
    .filter(Boolean);
}

export default function SearchPage() {
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [status, setStatus] = useState("");
  const [running, setRunning] = useState<string | null>(null);

  const load = () => api.getCompetitors().then(setCompetitors);
  useEffect(() => {
    load();
  }, []);

  const createCompetitor = async (e: React.FormEvent) => {
    e.preventDefault();
    await api.createCompetitor({
      name: form.name,
      region: form.region,
      brand_keywords: splitLines(form.brand_keywords),
      money_keywords: splitLines(form.money_keywords),
      google_queries: splitLines(form.google_queries),
      yandex_queries: splitLines(form.yandex_queries),
      vk_domains: splitLines(form.vk_domains),
      vk_owner_ids: splitLines(form.vk_owner_ids),
      telegram_channels: splitLines(form.telegram_channels),
      is_active: true,
    });
    setForm(emptyForm);
    setStatus("Конкурент добавлен");
    load();
  };

  const runCollector = async (id: string) => {
    setRunning(id);
    setStatus("");
    try {
      const res = await api.runSearch(id);
      setStatus(res.message);
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Ошибка запуска");
    } finally {
      setRunning(null);
    }
  };

  return (
    <div className="space-y-8 max-w-4xl">
      <div>
        <h2 className="text-2xl font-semibold">Поиск и конкуренты</h2>
        <p className="text-slate-400 text-sm">Добавьте конкурента и запустите сбор данных</p>
      </div>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {COLLECTORS.map((c) => (
          <button
            key={c.id}
            onClick={() => runCollector(c.id)}
            disabled={!!running}
            className="text-left p-4 rounded-xl border border-slate-800 bg-slate-900 hover:border-emerald-600 disabled:opacity-50"
          >
            <div className="font-medium">{c.label}</div>
            <div className="text-xs text-slate-400 mt-1">{c.desc}</div>
            {running === c.id && <div className="text-xs text-emerald-400 mt-2">Запуск...</div>}
          </button>
        ))}
      </section>
      {status && <p className="text-sm text-emerald-400">{status}</p>}

      <form onSubmit={createCompetitor} className="space-y-4 bg-slate-900 border border-slate-800 rounded-xl p-5">
        <h3 className="font-medium">Новый конкурент</h3>
        <div className="grid gap-3 md:grid-cols-2">
          <input
            required
            className="bg-slate-800 rounded-lg px-3 py-2"
            placeholder="Название"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
          <input
            className="bg-slate-800 rounded-lg px-3 py-2"
            placeholder="Регион (225 = Россия)"
            value={form.region}
            onChange={(e) => setForm({ ...form, region: e.target.value })}
          />
        </div>
        {(
          [
            ["brand_keywords", "Брендовые ключи (через запятую)"],
            ["money_keywords", "Коммерческие ключи"],
            ["google_queries", "Google-запросы"],
            ["yandex_queries", "Яндекс-запросы"],
            ["vk_domains", "VK домены"],
            ["vk_owner_ids", "VK owner_id"],
            ["telegram_channels", "Telegram каналы (@name)"],
          ] as const
        ).map(([key, label]) => (
          <textarea
            key={key}
            className="w-full bg-slate-800 rounded-lg px-3 py-2 text-sm min-h-[60px]"
            placeholder={label}
            value={form[key]}
            onChange={(e) => setForm({ ...form, [key]: e.target.value })}
          />
        ))}
        <button type="submit" className="bg-emerald-600 hover:bg-emerald-500 px-4 py-2 rounded-lg text-sm">
          Сохранить конкурента
        </button>
      </form>

      <section>
        <h3 className="font-medium mb-3">Активные конкуренты ({competitors.length})</h3>
        <div className="space-y-2">
          {competitors.map((c) => (
            <div
              key={c.id}
              className="flex items-center justify-between bg-slate-900 border border-slate-800 rounded-lg px-4 py-3"
            >
              <div>
                <div className="font-medium">{c.name}</div>
                <div className="text-xs text-slate-400">
                  {(c.brand_keywords || []).join(", ") || "без ключей"}
                </div>
              </div>
              <button
                onClick={async () => {
                  await api.deleteCompetitor(c.id);
                  load();
                }}
                className="text-xs text-red-400 hover:text-red-300"
              >
                Удалить
              </button>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
