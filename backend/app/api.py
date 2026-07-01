from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.report_data import gather_report_data
from app.report_docx import save_report_docx
from app.schemas import (
    AnalyticsSummary,
    AnalyticsTrends,
    CompetitorCreate,
    CompetitorOut,
    CompetitorUpdate,
    FindingFilters,
    FindingOut,
    SearchRunResponse,
    SettingsOut,
    SettingsUpdate,
)
from app.services import (
    analytics_summary,
    analytics_trends,
    create_competitor,
    delete_competitor,
    get_finding,
    get_or_create_settings,
    list_competitors,
    list_findings,
    mark_irrelevant,
    update_competitor,
    update_settings,
)

router = APIRouter(prefix="/api/v1")


def _finding_out(finding) -> FindingOut:
    return FindingOut(
        id=finding.id,
        competitor_id=finding.competitor_id,
        competitor_name=finding.competitor.name if finding.competitor else None,
        source=finding.source,
        result_type=finding.result_type,
        external_id=finding.external_id,
        title=finding.title,
        raw_text=finding.raw_text,
        snippet=finding.snippet,
        url=finding.url,
        author_name=finding.author_name,
        channel_name=finding.channel_name,
        position=finding.position,
        views=finding.views,
        likes=finding.likes,
        reposts=finding.reposts,
        comments=finding.comments,
        published_at=finding.published_at,
        collected_at=finding.collected_at,
        is_irrelevant=finding.is_irrelevant,
        analysis=finding.analysis,
    )


@router.get("/competitors", response_model=list[CompetitorOut])
async def api_list_competitors(db: AsyncSession = Depends(get_db)):
    return await list_competitors(db)


@router.post("/competitors", response_model=CompetitorOut, status_code=201)
async def api_create_competitor(data: CompetitorCreate, db: AsyncSession = Depends(get_db)):
    return await create_competitor(db, data)


@router.put("/competitors/{competitor_id}", response_model=CompetitorOut)
async def api_update_competitor(
    competitor_id: int, data: CompetitorUpdate, db: AsyncSession = Depends(get_db)
):
    competitor = await update_competitor(db, competitor_id, data)
    if not competitor:
        raise HTTPException(404, "Competitor not found")
    return competitor


@router.delete("/competitors/{competitor_id}", status_code=204)
async def api_delete_competitor(competitor_id: int, db: AsyncSession = Depends(get_db)):
    if not await delete_competitor(db, competitor_id):
        raise HTTPException(404, "Competitor not found")


@router.get("/findings")
async def api_list_findings(
    source: str | None = None,
    competitor_id: int | None = None,
    result_type: str | None = None,
    tone: str | None = None,
    has_cta: bool | None = None,
    keyword: str | None = None,
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    filters = FindingFilters(
        source=source,
        competitor_id=competitor_id,
        result_type=result_type,
        tone=tone,
        has_cta=has_cta,
        keyword=keyword,
        q=q,
        limit=limit,
        offset=offset,
    )
    items, total = await list_findings(db, filters)
    return {
        "items": [_finding_out(f) for f in items],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/findings/{finding_id}", response_model=FindingOut)
async def api_get_finding(finding_id: int, db: AsyncSession = Depends(get_db)):
    finding = await get_finding(db, finding_id)
    if not finding:
        raise HTTPException(404, "Finding not found")
    return _finding_out(finding)


@router.post("/findings/{finding_id}/irrelevant", status_code=204)
async def api_mark_irrelevant(finding_id: int, db: AsyncSession = Depends(get_db)):
    if not await mark_irrelevant(db, finding_id):
        raise HTTPException(404, "Finding not found")


@router.get("/analytics/summary", response_model=AnalyticsSummary)
async def api_analytics_summary(db: AsyncSession = Depends(get_db)):
    return await analytics_summary(db)


@router.get("/analytics/trends", response_model=AnalyticsTrends)
async def api_analytics_trends(db: AsyncSession = Depends(get_db)):
    return await analytics_trends(db)


@router.get("/settings", response_model=SettingsOut)
async def api_get_settings(db: AsyncSession = Depends(get_db)):
    from app.config import get_settings

    env = get_settings()
    row = await get_or_create_settings(db)
    return SettingsOut(
        ai_base_url=row.ai_base_url or env.ai_base_url,
        ai_api_key=row.ai_api_key or env.ai_api_key or None,
        ai_model=row.ai_model or env.ai_model,
        google_api_key=row.google_api_key or env.google_api_key or None,
        google_cx=row.google_cx or env.google_cx or None,
        yandex_api_key=row.yandex_api_key or env.yandex_api_key or None,
        yandex_folder_id=row.yandex_folder_id or env.yandex_folder_id or None,
        vk_access_token=row.vk_access_token or env.vk_access_token or None,
        telegram_api_id=row.telegram_api_id or env.telegram_api_id or None,
        telegram_api_hash=row.telegram_api_hash or env.telegram_api_hash or None,
        monitor_interval_hours=row.monitor_interval_hours,
        google_enabled=row.google_enabled,
        yandex_enabled=row.yandex_enabled,
        vk_enabled=row.vk_enabled,
        telegram_enabled=row.telegram_enabled,
    )


@router.put("/settings", response_model=SettingsOut)
async def api_update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    row = await update_settings(db, data)
    return SettingsOut.model_validate(row)


async def _enqueue(collector: str) -> SearchRunResponse:
    try:
        from workers.tasks import run_collector_task

        task = run_collector_task.delay(collector)
        return SearchRunResponse(
            task_id=task.id,
            collector=collector,
            message=f"Collector '{collector}' queued",
        )
    except Exception:
        import asyncio

        from workers.tasks import run_collector_task

        result = await asyncio.to_thread(run_collector_task.run, collector)
        return SearchRunResponse(
            task_id="sync",
            collector=collector,
            message=f"Collector '{collector}' finished: {result}",
        )


@router.post("/search/run-all", response_model=SearchRunResponse)
async def api_run_all():
    return await _enqueue("all")


@router.post("/search/run-google", response_model=SearchRunResponse)
async def api_run_google():
    return await _enqueue("google")


@router.post("/search/run-yandex", response_model=SearchRunResponse)
async def api_run_yandex():
    return await _enqueue("yandex")


@router.post("/search/run-vk", response_model=SearchRunResponse)
async def api_run_vk():
    return await _enqueue("vk")


@router.post("/search/run-telegram", response_model=SearchRunResponse)
async def api_run_telegram():
    return await _enqueue("telegram")


@router.get("/reports/docx")
async def api_export_docx(
    with_ai: bool = Query(True, description="Включить AI-сводку и рекомендации"),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime
    from pathlib import Path

    data = await gather_report_data(db, with_ai_summary=with_ai)
    out_dir = Path("output")
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = out_dir / f"competitor_report_{ts}.docx"
    save_report_docx(data, path)
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=path.name,
    )
