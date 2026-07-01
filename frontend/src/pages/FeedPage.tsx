import { useEffect, useState } from "react";
import { api, type Competitor, type Finding } from "../api";
import FindingCard from "../components/FindingCard";

export default function FeedPage() {
  const [findings, setFindings] = useState<Finding[]>([]);
  const [competitors, setCompetitors] = useState<Competitor[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    source: "",
    competitor_id: "",
    result_type: "",
    tone: "",
    has_cta: "",
    keyword: "",
    q: "",
  });

  const load = async () => {
    setLoading(true);
    try {
      const [f, c] = await Promise.all([
        api.getFindings({
          source: filters.source || undefined,
          competitor_id: filters.competitor_id ? Number(filters.competitor_id) : undefined,
          result_type: filters.result_type || undefined,
          tone: filters.tone || undefined,
          has_cta: filters.has_cta === "" ? undefined : filters.has_cta === "true",
          keyword: filters.keyword || undefined,
          q: filters.q || undefined,
          limit: 50,
        }),
        api.getCompetitors(),
      ]);
      setFindings(f.items);
      setTotal(f.total);
      setCompetitors(c);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleIrrelevant = async (id: number) => {
    await api.markIrrelevant(id);
    setFindings((prev) => prev.filter((f) => f.id !== id));
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold">Лента результатов</h2>
        <p className="text-slate-400 text-sm">Всего: {total}</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 bg-slate-900 p-4 rounded-xl border border-slate-800">
        <select
          className="bg-slate-800 rounded-lg px-2 py-2 text-sm"
          value={filters.source}
          onChange={(e) => setFilters({ ...filters, source: e.target.value })}
        >
          <option value="">Все источники</option>
          <option value="google">Google</option>
          <option value="yandex">Yandex</option>
          <option value="vk">VK</option>
          <option value="telegram">Telegram</option>
        </select>
        <select
          className="bg-slate-800 rounded-lg px-2 py-2 text-sm"
          value={filters.competitor_id}
          onChange={(e) => setFilters({ ...filters, competitor_id: e.target.value })}
        >
          <option value="">Все конкуренты</option>
          {competitors.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        <input
          className="bg-slate-800 rounded-lg px-2 py-2 text-sm"
          placeholder="Тип"
          value={filters.result_type}
          onChange={(e) => setFilters({ ...filters, result_type: e.target.value })}
        />
        <input
          className="bg-slate-800 rounded-lg px-2 py-2 text-sm"
          placeholder="Tone"
          value={filters.tone}
          onChange={(e) => setFilters({ ...filters, tone: e.target.value })}
        />
        <select
          className="bg-slate-800 rounded-lg px-2 py-2 text-sm"
          value={filters.has_cta}
          onChange={(e) => setFilters({ ...filters, has_cta: e.target.value })}
        >
          <option value="">CTA: любой</option>
          <option value="true">С CTA</option>
          <option value="false">Без CTA</option>
        </select>
        <input
          className="bg-slate-800 rounded-lg px-2 py-2 text-sm"
          placeholder="Ключевое слово"
          value={filters.keyword}
          onChange={(e) => setFilters({ ...filters, keyword: e.target.value })}
        />
        <input
          className="bg-slate-800 rounded-lg px-2 py-2 text-sm"
          placeholder="Полнотекстовый поиск"
          value={filters.q}
          onChange={(e) => setFilters({ ...filters, q: e.target.value })}
        />
        <button
          onClick={load}
          className="col-span-2 md:col-span-4 lg:col-span-7 bg-emerald-600 hover:bg-emerald-500 rounded-lg py-2 text-sm font-medium"
        >
          Применить фильтры
        </button>
      </div>

      {loading ? (
        <p className="text-slate-400">Загрузка...</p>
      ) : findings.length === 0 ? (
        <p className="text-slate-400">Результатов пока нет. Запустите поиск в разделе Search.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {findings.map((f) => (
            <FindingCard key={f.id} finding={f} onIrrelevant={handleIrrelevant} />
          ))}
        </div>
      )}
    </div>
  );
}
