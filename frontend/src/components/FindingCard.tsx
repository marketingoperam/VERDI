import { sourceColor, sourceIcon, type Finding } from "../api";

type Props = {
  finding: Finding;
  onIrrelevant: (id: number) => void;
};

export default function FindingCard({ finding, onIrrelevant }: Props) {
  const a = finding.analysis;
  const title = finding.title || finding.raw_text?.slice(0, 120) || "Без заголовка";

  return (
    <article className="bg-slate-900 border border-slate-800 rounded-xl p-4 flex flex-col gap-3">
      <div className="flex items-start gap-3">
        <span
          className={`w-9 h-9 rounded-lg flex items-center justify-center text-xs font-bold ${sourceColor[finding.source] || "bg-slate-700"}`}
        >
          {sourceIcon[finding.source] || "?"}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap gap-2 text-xs text-slate-400 mb-1">
            <span>{finding.competitor_name || "—"}</span>
            <span>·</span>
            <span>{finding.result_type}</span>
            <span>·</span>
            <span>{new Date(finding.collected_at).toLocaleString("ru-RU")}</span>
          </div>
          <h3 className="font-medium text-slate-100 truncate">{title}</h3>
        </div>
      </div>

      {a?.summary && <p className="text-sm text-slate-300">{a.summary}</p>}

      <div className="grid grid-cols-2 gap-2 text-xs">
        {a?.tone && (
          <div>
            <span className="text-slate-500">Tone: </span>
            {a.tone}
          </div>
        )}
        {a?.offer && (
          <div>
            <span className="text-slate-500">Offer: </span>
            {a.offer}
          </div>
        )}
        {a?.cta && (
          <div className="col-span-2">
            <span className="text-slate-500">CTA: </span>
            {a.cta}
          </div>
        )}
      </div>

      <div className="flex gap-2 mt-1">
        {finding.url && (
          <a
            href={finding.url}
            target="_blank"
            rel="noreferrer"
            className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-slate-700"
          >
            Open
          </a>
        )}
        <button
          onClick={() => onIrrelevant(finding.id)}
          className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-red-900/50"
        >
          Mark irrelevant
        </button>
        {a?.summary && (
          <button
            onClick={() => navigator.clipboard.writeText(a.summary!)}
            className="px-3 py-1.5 text-xs rounded-lg bg-slate-800 hover:bg-slate-700"
          >
            Copy summary
          </button>
        )}
      </div>
    </article>
  );
}
