"""Лёгкая миграция SQLite: create_all не добавляет колонки в существующие таблицы."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


async def migrate_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        # accounts table may be missing entirely — create_all handles that
        cols = await _table_columns(conn, "invite_targets")
        if cols:
            if "is_messaged" not in cols:
                await conn.execute(
                    text("ALTER TABLE invite_targets ADD COLUMN is_messaged BOOLEAN NOT NULL DEFAULT 0")
                )
            if "messaged_at" not in cols:
                await conn.execute(text("ALTER TABLE invite_targets ADD COLUMN messaged_at DATETIME"))
            if "outreach_error" not in cols:
                await conn.execute(text("ALTER TABLE invite_targets ADD COLUMN outreach_error TEXT"))
            if "is_skipped" not in cols:
                await conn.execute(
                    text("ALTER TABLE invite_targets ADD COLUMN is_skipped BOOLEAN NOT NULL DEFAULT 0")
                )


async def _table_columns(conn, table: str) -> set[str]:
    try:
        res = await conn.execute(text(f"PRAGMA table_info({table})"))
        rows = res.fetchall()
        return {r[1] for r in rows}
    except Exception:
        return set()
