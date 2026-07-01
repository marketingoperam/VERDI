#!/usr/bin/env python3
"""Запуск Telegram-коллектора."""

import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from app.database import Base, engine
from app.main import _seed_demo_competitor, _seed_settings
from collectors.base import make_session_factory
from collectors.telegram_collector import TelegramCollector

# migrate broken BIGINT tables if needed
from scripts.migrate_sqlite import main as migrate_sqlite


async def main() -> None:
    Path("data").mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate_sqlite()
    await _seed_settings()
    await _seed_demo_competitor()

    print("Сбор из Telegram...")
    collector = TelegramCollector(make_session_factory())
    count = await collector.run()
    print(f"Готово: сохранено {count} новых записей")
    print("Откройте http://127.0.0.1:5173 — раздел Feed")
    print(f"Последний отчёт: output\\competitor_report_latest.docx")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        sys.exit(1)
