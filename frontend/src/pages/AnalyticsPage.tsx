import { useEffect, useState } from "react";
import { api } from "../api";

export default function AnalyticsPage() {
  const [summary, setSummary] = useState<Awaited<ReturnType<typeof api.getSummary>> | null>(null);
  const [trends, setTrends] = useState<Awaited<ReturnType<typeof api.getTrends>> | null>(null);

  useEffect(() => {
    Promise.all([api.getSummary(), api.getTrends()]).then(([s, t]) => {
      setSummary(s);
      setTrends(t);
    });
  }, []);

  const cards = summary
    ? [
        { label: "Всего за 24ч", value: summary.total_24h },
        { label: "Google", value: summary.google_24h },
        { label: "Яндекс", value: summary.yandex_24h },
        { label: "VK", value: summary.vk_24h },
        { label: "Telegram", value: summary.telegram_24h },
      ]
    : [];

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold">Аналитика</h2>
          <p className="text-slate-400 text-sm">Сводка за последние 24 часа</p>
        </div>
        <a
          href="/api/v1/reports/docx"
          className="shrink-0 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-sm font-medium"
        >
          Выгрузить DOCX
        </a>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        {cards.map((c) => (
          <div key={c.label} className="bg-slate-900 border border-slate-800 rounded-xl p-4">
            <div className="text-2xl font-bold text-emerald-400">{c.value}</div>
            <div className="text-sm text-slate-400">{c.label}</div>
          </div>
        ))}
      </div>

      {summary && summary.by_competitor.length > 0 && (
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="font-medium mb-4">По конкурентам</h3>
          <div className="space-y-2">
            {summary.by_competitor.map((row) => (
              <div key={row.name} className="flex justify-between text-sm">
                <span>{row.name}</span>
                <span className="text-emerald-400">{row.count}</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {trends && trends.daily.length > 0 && (
        <section className="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <h3 className="font-medium mb-4">Тренды (14 дней)</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-slate-400 text-left">
                  <th className="pb-2">День</th>
                  <th className="pb-2">Источник</th>
                  <th className="pb-2">Кол-во</th>
                </tr>
              </thead>
              <tbody>
                {trends.daily.map((row, i) => (
                  <tr key={i} className="border-t border-slate-800">
                    <td className="py-2">{String(row.day).slice(0, 10)}</td>
                    <td className="py-2">{row.source}</td>
                    <td className="py-2 text-emerald-400">{row.cnt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
