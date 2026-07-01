#!/usr/bin/env python3
"""Повторный AI-анализ для находок без analysis."""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.orm import selectinload

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.database import async_session
from app.models import Finding, FindingAnalysis
from app.services import get_or_create_settings
from collectors.ai_analyzer import analyze_finding


async def main() -> None:
    analyzed = 0
    failed = 0
    async with async_session() as db:
        settings = await get_or_create_settings(db)
        from app.config import get_settings

        env = get_settings()
        settings.ai_base_url = env.ai_base_url
        settings.ai_api_key = env.ai_api_key
        settings.ai_model = env.ai_model
        await db.commit()

        result = await db.execute(
            select(Finding)
            .outerjoin(FindingAnalysis)
            .where(FindingAnalysis.id.is_(None), Finding.is_irrelevant.is_(False))
            .options(selectinload(Finding.competitor))
        )
        findings = list(result.scalars().all())
        print(f"Находок без анализа: {len(findings)}")

        for finding in findings:
            try:
                out = await analyze_finding(db, finding, settings)
                if out:
                    analyzed += 1
                    print(f"  OK #{finding.id}")
                else:
                    failed += 1
                    print(f"  SKIP #{finding.id}")
            except Exception as exc:
                failed += 1
                print(f"  ERR #{finding.id}: {exc}", file=sys.stderr)

    print(f"\nГотово: проанализировано {analyzed}, ошибок {failed}")

    if analyzed > 0:
        from app.auto_export import auto_export_report

        path = await auto_export_report(trigger="ai_analysis")
        if path:
            print(f"Отчёт DOCX: {path}")


if __name__ == "__main__":
    asyncio.run(main())
