from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.models import AppSettings, CollectorRun, Competitor
from app.services import get_or_create_settings, upsert_finding
from collectors.ai_analyzer import analyze_finding

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    name: str = "base"

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory
        self.settings = get_settings()

    async def _get_runtime_settings(self, db: AsyncSession) -> AppSettings:
        return await get_or_create_settings(db)

    async def _start_run(self, db: AsyncSession) -> CollectorRun | None:
        try:
            run = CollectorRun(
                collector_name=self.name,
                status="running",
                started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
            db.add(run)
            await db.commit()
            await db.refresh(run)
            return run
        except Exception as exc:
            logger.warning("Could not log collector run: %s", exc)
            await db.rollback()
            return None

    async def _finish_run(
        self,
        db: AsyncSession,
        run: CollectorRun | None,
        items: int,
        error: str | None = None,
    ) -> None:
        if run is None:
            return
        try:
            run.status = "failed" if error else "completed"
            run.finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            run.items_collected = items
            run.error_text = error
            await db.commit()
        except Exception as exc:
            logger.warning("Could not update collector run: %s", exc)
            await db.rollback()

    async def _get_competitors(self, db: AsyncSession) -> list[Competitor]:
        result = await db.execute(
            select(Competitor).where(Competitor.is_active.is_(True)).order_by(Competitor.id)
        )
        return list(result.scalars().all())

    async def _save_and_analyze(
        self,
        db: AsyncSession,
        finding_data: dict[str, Any],
        app_settings: AppSettings,
    ) -> bool:
        finding = await upsert_finding(db, finding_data)
        if not finding:
            return False

        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        from app.models import Finding

        result = await db.execute(
            select(Finding)
            .options(selectinload(Finding.competitor))
            .where(Finding.id == finding.id)
        )
        finding = result.scalar_one()

        try:
            await analyze_finding(db, finding, app_settings)
        except Exception as exc:
            logger.exception("AI analysis failed for finding %s: %s", finding.id, exc)
        return True

    @abstractmethod
    async def collect(self) -> int:
        pass

    async def run(self, *, auto_export: bool | None = None) -> int:
        async with self.session_factory() as db:
            run = await self._start_run(db)
            try:
                count = await self.collect()
                await self._finish_run(db, run, count)
                should_export = (
                    self.settings.auto_export_docx if auto_export is None else auto_export
                )
                if should_export:
                    from app.auto_export import auto_export_report

                    path = await auto_export_report(trigger=f"collector:{self.name}")
                    if path:
                        print(f"Отчёт DOCX: {path}")
                return count
            except Exception as exc:
                logger.exception("Collector %s failed", self.name)
                await self._finish_run(db, run, 0, str(exc))
                raise


def make_session_factory() -> async_sessionmaker[AsyncSession]:
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return async_sessionmaker(engine, expire_on_commit=False)
