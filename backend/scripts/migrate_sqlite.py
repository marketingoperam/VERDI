#!/usr/bin/env python3
"""Починка SQLite-таблиц с autoincrement (только если схема старая)."""

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy import text

from app.config import get_settings
from app.database import Base, engine
from app.models import CollectorRun, Finding, FindingAnalysis


def _needs_migration() -> bool:
    url = get_settings().database_url
    if not url.startswith("sqlite"):
        return False
    db_path = url.split("///")[-1]
    if not Path(db_path).exists():
        return False
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name='findings'"
    ).fetchone()
    conn.close()
    if not row or not row[0]:
        return False
    return "id BIGINT" in row[0] or "id BIGINT" in row[0].upper()


async def main() -> None:
    if not _needs_migration():
        return

    tables = [FindingAnalysis.__table__, Finding.__table__, CollectorRun.__table__]
    async with engine.begin() as conn:
        for table in tables:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table.name}"))
        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[t for t in tables]
            )
        )
    print("SQLite: таблицы findings пересозданы")


if __name__ == "__main__":
    asyncio.run(main())
