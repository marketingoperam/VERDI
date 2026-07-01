"""Сбор данных для полного отчёта."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.models import AppSettings, Competitor, Finding, FindingAnalysis
from app.services import get_or_create_settings, list_competitors


def _fmt_dt(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d.%m.%Y %H:%M")


def _join_list(items: list | None) -> str:
    if not items:
        return "—"
    return ", ".join(str(x) for x in items if x)


async def gather_report_data(db: AsyncSession, *, with_ai_summary: bool = True) -> dict[str, Any]:
    competitors = await list_competitors(db)
    settings = await get_or_create_settings(db)

    result = await db.execute(
        select(Finding)
        .options(selectinload(Finding.analysis), selectinload(Finding.competitor))
        .where(Finding.is_irrelevant.is_(False))
        .order_by(Finding.collected_at.desc())
    )
    findings = list(result.scalars().all())

    by_source: Counter[str] = Counter()
    by_competitor: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    by_tone: Counter[str] = Counter()
    by_sentiment: Counter[str] = Counter()
    by_intent: Counter[str] = Counter()
    offers: list[str] = []
    ctas: list[str] = []
    pain_points: list[str] = []
    hooks: list[str] = []
    summaries: list[str] = []

    findings_data: list[dict[str, Any]] = []
    for f in findings:
        comp_name = f.competitor.name if f.competitor else "Без конкурента"
        by_source[f.source] += 1
        by_competitor[comp_name] += 1
        by_type[f.result_type] += 1

        a = f.analysis
        if a:
            if a.tone:
                by_tone[a.tone] += 1
            if a.sentiment:
                by_sentiment[a.sentiment] += 1
            if a.intent:
                by_intent[a.intent] += 1
            if a.offer:
                offers.append(a.offer)
            if a.cta:
                ctas.append(a.cta)
            if a.pain_points:
                pain_points.extend(a.pain_points)
            if a.hooks:
                hooks.extend(a.hooks)
            if a.summary:
                summaries.append(a.summary)

        findings_data.append(
            {
                "id": f.id,
                "competitor": comp_name,
                "source": f.source,
                "result_type": f.result_type,
                "title": f.title,
                "raw_text": f.raw_text,
                "snippet": f.snippet,
                "url": f.url,
                "channel_name": f.channel_name,
                "author_name": f.author_name,
                "position": f.position,
                "views": f.views,
                "likes": f.likes,
                "reposts": f.reposts,
                "comments": f.comments,
                "published_at": _fmt_dt(f.published_at),
                "collected_at": _fmt_dt(f.collected_at),
                "analysis": {
                    "entity_type": a.entity_type if a else None,
                    "offer": a.offer if a else None,
                    "cta": a.cta if a else None,
                    "pain_points": a.pain_points if a else [],
                    "tone": a.tone if a else None,
                    "hooks": a.hooks if a else [],
                    "intent": a.intent if a else None,
                    "sentiment": a.sentiment if a else None,
                    "summary": a.summary if a else None,
                    "is_competitor_related": a.is_competitor_related if a else None,
                    "model_used": a.model_used if a else None,
                    "analyzed_at": _fmt_dt(a.analyzed_at) if a else None,
                }
                if a
                else None,
            }
        )

    analyzed_count = sum(1 for f in findings if f.analysis)
    competitors_data = [
        {
            "id": c.id,
            "name": c.name,
            "region": c.region,
            "is_active": c.is_active,
            "brand_keywords": c.brand_keywords or [],
            "money_keywords": c.money_keywords or [],
            "google_queries": c.google_queries or [],
            "yandex_queries": c.yandex_queries or [],
            "vk_domains": c.vk_domains or [],
            "vk_owner_ids": c.vk_owner_ids or [],
            "telegram_channels": c.telegram_channels or [],
            "created_at": _fmt_dt(c.created_at),
            "findings_count": by_competitor.get(c.name, 0),
        }
        for c in competitors
    ]

    by_competitor_source: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for f in findings:
        name = f.competitor.name if f.competitor else "Без конкурента"
        by_competitor_source[name][f.source] += 1

    data: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%d.%m.%Y %H:%M"),
        "settings": {
            "ai_model": settings.ai_model or get_settings().ai_model,
            "monitor_interval_hours": settings.monitor_interval_hours,
            "google_enabled": settings.google_enabled,
            "yandex_enabled": settings.yandex_enabled,
            "vk_enabled": settings.vk_enabled,
            "telegram_enabled": settings.telegram_enabled,
        },
        "stats": {
            "total_findings": len(findings),
            "analyzed_findings": analyzed_count,
            "competitors_count": len(competitors),
            "by_source": dict(by_source),
            "by_competitor": dict(by_competitor),
            "by_type": dict(by_type),
            "by_tone": dict(by_tone),
            "by_sentiment": dict(by_sentiment),
            "by_intent": dict(by_intent),
            "unique_offers": len(set(offers)),
            "unique_ctas": len(set(ctas)),
            "unique_pain_points": len(set(pain_points)),
            "unique_hooks": len(set(hooks)),
        },
        "aggregates": {
            "offers": list(dict.fromkeys(offers)),
            "ctas": list(dict.fromkeys(ctas)),
            "pain_points": list(dict.fromkeys(pain_points)),
            "hooks": list(dict.fromkeys(hooks)),
            "summaries": summaries,
        },
        "by_competitor_source": {
            k: dict(v) for k, v in by_competitor_source.items()
        },
        "competitors": competitors_data,
        "findings": findings_data,
        "ai_executive_summary": None,
        "ai_recommendations": None,
        "ai_market_picture": None,
    }

    if with_ai_summary and findings:
        ai_text = await _generate_strategic_analysis(
            settings, competitors_data, findings_data, data["stats"], data["aggregates"]
        )
        if ai_text:
            data["ai_executive_summary"] = ai_text.get("executive_summary")
            data["ai_market_picture"] = ai_text.get("market_picture")
            data["ai_recommendations"] = ai_text.get("recommendations")

    return data


async def _generate_strategic_analysis(
    settings: AppSettings,
    competitors: list[dict],
    findings: list[dict],
    stats: dict,
    aggregates: dict,
) -> dict[str, str] | None:
    env = get_settings()
    api_key = settings.ai_api_key or env.ai_api_key
    base_url = settings.ai_base_url or env.ai_base_url
    model = settings.ai_model or env.ai_model
    if not api_key:
        return None

    sample_lines = []
    for f in findings[:40]:
        a = f.get("analysis") or {}
        sample_lines.append(
            f"- [{f['source']}] {f['competitor']}: "
            f"{(a.get('summary') or f.get('title') or f.get('raw_text') or '')[:300]}"
        )

    prompt = f"""На основе данных конкурентной разведки сформируй стратегический отчёт на русском языке.

КОНКУРЕНТЫ:
{competitors}

СТАТИСТИКА:
{stats}

ОФФЕРЫ: {aggregates.get('offers', [])[:20]}
CTA: {aggregates.get('ctas', [])[:20]}
БОЛИ АУДИТОРИИ: {aggregates.get('pain_points', [])[:20]}
ТРИГГЕРЫ: {aggregates.get('hooks', [])[:20]}

ВЫБОРКА НАХОДОК:
{chr(10).join(sample_lines)}

Верни JSON с тремя полями (каждое — развёрнутый текст, 3-8 абзацев):
- executive_summary: исполнительное резюме, главные выводы
- market_picture: полная картина рынка, позиционирование конкурентов, каналы, тактики
- recommendations: конкретные рекомендации для мониторинга и ответных действий
"""

    client = AsyncOpenAI(base_url=base_url, api_key=api_key)
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "Ты стратегический аналитик. Отвечай только валидным JSON без markdown.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
        )
        import json

        raw = response.choices[0].message.content or "{}"
        return json.loads(raw)
    except Exception:
        return None
