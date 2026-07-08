"""Разовая пересборка статистики активности из истории клон-чата."""

from __future__ import annotations

import asyncio
from datetime import timezone

import structlog
from sqlalchemy import delete, select
from sqlalchemy.exc import OperationalError
from telethon.tl.types import MessageService, User

from app.db import async_session_factory
from app.models import MirrorChat, UserActivity
from app.services.activity_config import ACTIVITY_MIRROR_USERNAMES
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()

_DB_RETRY_ATTEMPTS = 8
_DB_RETRY_BASE_SEC = 0.25


async def _with_db_retry(coro_factory):
    last_exc: Exception | None = None
    for attempt in range(_DB_RETRY_ATTEMPTS):
        try:
            return await coro_factory()
        except OperationalError as exc:
            last_exc = exc
            if "locked" not in str(exc).lower() or attempt == _DB_RETRY_ATTEMPTS - 1:
                raise
            await asyncio.sleep(_DB_RETRY_BASE_SEC * (2**attempt))
    raise last_exc  # pragma: no cover


async def backfill_mirror_chat(
    session_pool: SessionPoolManager,
    mirror_chat_db_id: int,
    *,
    limit: int = 3000,
) -> dict[str, int]:
    async with async_session_factory() as db:
        result = await db.execute(select(MirrorChat).where(MirrorChat.id == mirror_chat_db_id))
        mirror = result.scalar_one_or_none()
        if not mirror or not mirror.is_active:
            raise ValueError("Клон-чат не найден")
        if mirror.mirror_username not in ACTIVITY_MIRROR_USERNAMES:
            raise ValueError("Этот чат не входит в список клонов для учёта активности")
        mirror_id = mirror.id
        telegram_chat_id = mirror.telegram_chat_id

    client = await session_pool.get_listener_client()
    entity = await client.get_entity(telegram_chat_id)

    agg: dict[int, dict] = {}
    messages_scanned = 0
    messages_recorded = 0

    async for msg in client.iter_messages(entity, limit=limit):
        messages_scanned += 1
        if isinstance(msg, MessageService) or not msg.sender_id:
            continue

        sender = msg.sender
        if sender is None:
            try:
                sender = await msg.get_sender()
            except Exception:
                sender = None
        if isinstance(sender, User) and sender.bot:
            continue

        uid = msg.sender_id
        row = agg.get(uid)
        if not row:
            first_name, last_name, username = "Unknown", None, None
            if isinstance(sender, User):
                first_name = sender.first_name or "Unknown"
                last_name = sender.last_name
                username = sender.username
            row = {
                "first_name": first_name,
                "last_name": last_name,
                "username": username,
                "message_count": 0,
                "last_active_at": None,
            }
            agg[uid] = row

        if isinstance(sender, User):
            if sender.first_name:
                row["first_name"] = sender.first_name
            if sender.last_name:
                row["last_name"] = sender.last_name
            if sender.username:
                row["username"] = sender.username

        row["message_count"] += 1
        messages_recorded += 1
        msg_date = msg.date
        if msg_date:
            if msg_date.tzinfo is None:
                msg_date = msg_date.replace(tzinfo=timezone.utc)
            if not row["last_active_at"] or msg_date > row["last_active_at"]:
                row["last_active_at"] = msg_date

    async def _persist() -> None:
        async with async_session_factory() as db:
            existing = await db.execute(
                select(UserActivity).where(UserActivity.mirror_chat_id == mirror_id)
            )
            old_reactions = {
                row.telegram_user_id: row.reaction_count for row in existing.scalars()
            }

            await db.execute(delete(UserActivity).where(UserActivity.mirror_chat_id == mirror_id))
            for uid, data in agg.items():
                db.add(
                    UserActivity(
                        mirror_chat_id=mirror_id,
                        telegram_user_id=uid,
                        first_name=data["first_name"],
                        last_name=data["last_name"],
                        username=data["username"],
                        message_count=data["message_count"],
                        reaction_count=old_reactions.get(uid, 0),
                        last_active_at=data["last_active_at"],
                    )
                )
            await db.commit()

    await _with_db_retry(_persist)

    logger.info(
        "activity_backfill_done",
        mirror_chat_id=mirror_chat_db_id,
        scanned=messages_scanned,
        recorded=messages_recorded,
        users=len(agg),
    )
    return {"scanned": messages_scanned, "recorded": messages_recorded, "users": len(agg)}


async def backfill_all_activity_mirrors(
    session_pool: SessionPoolManager,
    *,
    limit: int = 3000,
) -> dict[int, dict]:
    async with async_session_factory() as db:
        result = await db.execute(
            select(MirrorChat).where(
                MirrorChat.mirror_username.in_(ACTIVITY_MIRROR_USERNAMES),
                MirrorChat.is_active.is_(True),
            )
        )
        mirrors = result.scalars().all()

    stats: dict[int, dict] = {}
    for mirror in mirrors:
        try:
            stats[mirror.id] = await backfill_mirror_chat(
                session_pool, mirror.id, limit=limit
            )
        except Exception as exc:
            logger.warning("activity_backfill_failed", chat=mirror.title, error=str(exc))
            stats[mirror.id] = {"scanned": 0, "recorded": 0, "error": str(exc)}
    return stats
