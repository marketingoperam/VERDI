"""Автоматическая выгрузка DOCX-отчёта."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from app.config import get_settings
from app.database import async_session
from app.report_data import gather_report_data
from app.report_docx import save_report_docx

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[2]


def _output_dir() -> Path:
    settings = get_settings()
    raw = settings.report_output_dir.strip() or "output"
    path = Path(raw)
    if not path.is_absolute():
        path = _ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


async def auto_export_report(
    *,
    trigger: str = "manual",
    with_ai: bool | None = None,
) -> Path | None:
    """Сформировать DOCX и сохранить в output/. Возвращает путь к файлу."""
    settings = get_settings()
    if not settings.auto_export_docx:
        return None

    use_ai = settings.auto_export_with_ai if with_ai is None else with_ai
    out_dir = _output_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped = out_dir / f"competitor_report_{ts}.docx"
    latest = out_dir / "competitor_report_latest.docx"

    try:
        async with async_session() as db:
            data = await gather_report_data(db, with_ai_summary=use_ai)
        save_report_docx(data, stamped)
        shutil.copy2(stamped, latest)
        logger.info(
            "Auto-export DOCX [%s]: %s (%s findings)",
            trigger,
            stamped,
            data["stats"]["total_findings"],
        )
        return stamped
    except Exception as exc:
        logger.exception("Auto-export DOCX failed [%s]: %s", trigger, exc)
        return None
