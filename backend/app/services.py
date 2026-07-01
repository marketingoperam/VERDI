import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import is_postgres
from app.models import AppSettings, Competitor, Finding, FindingAnalysis
from app.schemas import CompetitorCreate, CompetitorUpdate, FindingFilters, SettingsUpdate


def content_hash(source: str, url: str | None, raw_text: str | None) -> str:
    payload = f"{source}|{url or ''}|{raw_text or ''}"
    return hashlib.sha256(payload.encode()).hexdigest()


async def get_or_create_settings(db: AsyncSession) -> AppSettings:
    result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = AppSettings(id=1)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


async def list_competitors(db: AsyncSession, active_only: bool = False) -> list[Competitor]:
    query = select(Competitor).order_by(Competitor.id)
    if active_only:
        query = query.where(Competitor.is_active.is_(True))
    result = await db.execute(query)
    return list(result.scalars().all())


async def create_competitor(db: AsyncSession, data: CompetitorCreate) -> Competitor:
    competitor = Competitor(**data.model_dump())
    db.add(competitor)
    await db.commit()
    await db.refresh(competitor)
    return competitor


async def update_competitor(
    db: AsyncSession, competitor_id: int, data: CompetitorUpdate
) -> Competitor | None:
    result = await db.execute(select(Competitor).where(Competitor.id == competitor_id))
    competitor = result.scalar_one_or_none()
    if not competitor:
        return None
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(competitor, key, value)
    await db.commit()
    await db.refresh(competitor)
    return competitor


async def delete_competitor(db: AsyncSession, competitor_id: int) -> bool:
    result = await db.execute(select(Competitor).where(Competitor.id == competitor_id))
    competitor = result.scalar_one_or_none()
    if not competitor:
        return False
    await db.delete(competitor)
    await db.commit()
    return True


async def upsert_finding(db: AsyncSession, finding_data: dict) -> Finding | None:
    source = finding_data["source"]
    external_id = finding_data.get("external_id")
    url = finding_data.get("url")
    raw_text = finding_data.get("raw_text")
    chash = content_hash(source, url, raw_text)

    if external_id:
        existing = await db.execute(
            select(Finding).where(
                Finding.source == source,
                Finding.external_id == external_id,
            )
        )
        row = existing.scalar_one_or_none()
        if row:
            return None

    existing_hash = await db.execute(
        select(Finding).where(Finding.content_hash == chash)
    )
    if existing_hash.scalar_one_or_none():
        return None

    finding = Finding(**finding_data, content_hash=chash)
    db.add(finding)
    await db.commit()
    await db.refresh(finding)
    return finding


async def list_findings(db: AsyncSession, filters: FindingFilters) -> tuple[list[Finding], int]:
    query = (
        select(Finding)
        .options(
            selectinload(Finding.analysis),
            selectinload(Finding.competitor),
        )
        .where(Finding.is_irrelevant.is_(False))
    )

    if filters.source:
        query = query.where(Finding.source == filters.source)
    if filters.competitor_id:
        query = query.where(Finding.competitor_id == filters.competitor_id)
    if filters.result_type:
        query = query.where(Finding.result_type == filters.result_type)
    if filters.date_from:
        query = query.where(Finding.collected_at >= filters.date_from)
    if filters.date_to:
        query = query.where(Finding.collected_at <= filters.date_to)
    if filters.tone:
        query = query.join(FindingAnalysis).where(FindingAnalysis.tone == filters.tone)
    if filters.has_cta is True:
        query = query.join(FindingAnalysis).where(FindingAnalysis.cta.isnot(None))
    if filters.has_cta is False:
        query = query.outerjoin(FindingAnalysis).where(
            or_(FindingAnalysis.cta.is_(None), FindingAnalysis.id.is_(None))
        )
    if filters.keyword:
        pattern = f"%{filters.keyword}%"
        query = query.where(
            or_(
                Finding.raw_text.ilike(pattern),
                Finding.title.ilike(pattern),
                Finding.snippet.ilike(pattern),
            )
        )
    if filters.q:
        pattern = f"%{filters.q}%"
        if is_postgres():
            query = query.where(
                text("findings.search_vector @@ plainto_tsquery('russian', :q)")
            ).params(q=filters.q)
        else:
            query = query.where(
                or_(
                    Finding.raw_text.ilike(pattern),
                    Finding.title.ilike(pattern),
                    Finding.snippet.ilike(pattern),
                    Finding.url.ilike(pattern),
                    Finding.channel_name.ilike(pattern),
                )
            )

    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar_one()

    query = (
        query.order_by(Finding.collected_at.desc())
        .offset(filters.offset)
        .limit(filters.limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all()), total


async def get_finding(db: AsyncSession, finding_id: int) -> Finding | None:
    result = await db.execute(
        select(Finding)
        .options(
            selectinload(Finding.analysis),
            selectinload(Finding.competitor),
        )
        .where(Finding.id == finding_id)
    )
    return result.scalar_one_or_none()


async def mark_irrelevant(db: AsyncSession, finding_id: int) -> bool:
    result = await db.execute(select(Finding).where(Finding.id == finding_id))
    finding = result.scalar_one_or_none()
    if not finding:
        return False
    finding.is_irrelevant = True
    await db.commit()
    return True


async def save_analysis(
    db: AsyncSession, finding_id: int, analysis_data: dict, model_used: str
) -> FindingAnalysis:
    result = await db.execute(
        select(FindingAnalysis).where(FindingAnalysis.finding_id == finding_id)
    )
    analysis = result.scalar_one_or_none()
    if analysis is None:
        analysis = FindingAnalysis(finding_id=finding_id)
        db.add(analysis)

    for key, value in analysis_data.items():
        setattr(analysis, key, value)
    analysis.model_used = model_used
    analysis.analyzed_at = datetime.now(timezone.utc).replace(tzinfo=None)

    await db.commit()
    await db.refresh(analysis)
    return analysis


async def analytics_summary(db: AsyncSession) -> dict:
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)

    async def count_source(source: str) -> int:
        result = await db.execute(
            select(func.count())
            .select_from(Finding)
            .where(Finding.source == source, Finding.collected_at >= since)
        )
        return result.scalar_one()

    total = await db.execute(
        select(func.count()).select_from(Finding).where(Finding.collected_at >= since)
    )

    by_comp = await db.execute(
        select(Competitor.name, func.count(Finding.id))
        .join(Finding, Finding.competitor_id == Competitor.id)
        .where(Finding.collected_at >= since)
        .group_by(Competitor.name)
    )

    return {
        "total_24h": total.scalar_one(),
        "google_24h": await count_source("google"),
        "yandex_24h": await count_source("yandex"),
        "vk_24h": await count_source("vk"),
        "telegram_24h": await count_source("telegram"),
        "by_competitor": [
            {"name": name, "count": count} for name, count in by_comp.all()
        ],
    }


async def analytics_trends(db: AsyncSession, days: int = 14) -> dict:
    if is_postgres():
        result = await db.execute(
            text(
                """
                SELECT date_trunc('day', collected_at)::date AS day,
                       source,
                       COUNT(*) AS cnt
                FROM findings
                WHERE collected_at >= NOW() - make_interval(days => :days)
                GROUP BY 1, 2
                ORDER BY 1
                """
            ),
            {"days": days},
        )
        return {"daily": [dict(row._mapping) for row in result]}

    result = await db.execute(
        text(
            """
            SELECT date(collected_at) AS day, source, COUNT(*) AS cnt
            FROM findings
            WHERE collected_at >= datetime('now', :offset)
            GROUP BY 1, 2
            ORDER BY 1
            """
        ),
        {"offset": f"-{days} days"},
    )
    return {"daily": [dict(row._mapping) for row in result]}


async def update_settings(db: AsyncSession, data: SettingsUpdate) -> AppSettings:
    settings = await get_or_create_settings(db)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(settings, key, value)
    await db.commit()
    await db.refresh(settings)
    return settings
