#!/usr/bin/env python3
"""Экспорт полного отчёта в DOCX."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.auto_export import auto_export_report


async def main(output: Path | None, no_ai: bool) -> Path:
    path = await auto_export_report(
        trigger="manual",
        with_ai=not no_ai,
    )
    if path is None:
        from app.config import get_settings

        if not get_settings().auto_export_docx:
            raise SystemExit("AUTO_EXPORT_DOCX=false — автоэкспорт отключён")
        raise SystemExit("Не удалось сформировать отчёт")

    if output and output != path:
        import shutil

        shutil.copy2(path, output)
        path = output

    print(f"Сохранено: {path.resolve()}")
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Экспорт отчёта конкурентной разведки в DOCX")
    parser.add_argument("--output", "-o", help="Путь к выходному файлу .docx")
    parser.add_argument("--no-ai", action="store_true", help="Без AI-сводки (быстрее)")
    args = parser.parse_args()
    out = Path(args.output) if args.output else None
    try:
        asyncio.run(main(out, args.no_ai))
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(1)
