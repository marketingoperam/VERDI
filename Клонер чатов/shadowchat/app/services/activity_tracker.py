"""Учёт активности пользователей в клон-чатах: сообщения и реакции."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.types import MessageService, PeerUser, User

from app.models import MirrorChat, UserActivity
from app.services.activity_config import ACTIVITY_MIRROR_USERNAMES
from app.telegram.proxy import chat_id_variants

logger = structlog.get_logger()


class ActivityTracker:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _resolve_mirror_chat(self, telegram_chat_id: int) -> MirrorChat | None:
        variants = chat_id_variants(telegram_chat_id)
        result = await self.db.execute(
            select(MirrorChat).where(
                MirrorChat.telegram_chat_id.in_(variants),
                MirrorChat.is_active.is_(True),
                MirrorChat.mirror_username.in_(ACTIVITY_MIRROR_USERNAMES),
            )
        )
        return result.scalar_one_or_none()

    async def _get_or_create(
        self,
        mirror_chat_id: int,
        telegram_user_id: int,
        *,
        first_name: str = "",
        last_name: str | None = None,
        username: str | None = None,
    ) -> UserActivity:
        result = await self.db.execute(
            select(UserActivity).where(
                UserActivity.mirror_chat_id == mirror_chat_id,
                UserActivity.telegram_user_id == telegram_user_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            if first_name and row.first_name != first_name:
                row.first_name = first_name
            if last_name is not None and row.last_name != last_name:
                row.last_name = last_name
            if username is not None and row.username != username:
                row.username = username
            return row

        row = UserActivity(
            mirror_chat_id=mirror_chat_id,
            telegram_user_id=telegram_user_id,
            first_name=first_name or "Unknown",
            last_name=last_name,
            username=username,
            message_count=0,
            reaction_count=0,
        )
        self.db.add(row)
        await self.db.flush()
        return row

    async def record_message(self, message, telegram_chat_id: int) -> None:
        if isinstance(message, MessageService):
            return
        if not message.sender_id:
            return

        mirror_chat = await self._resolve_mirror_chat(telegram_chat_id)
        if not mirror_chat:
            return

        first_name, last_name, username = "", None, None
        sender = message.sender
        if sender is None:
            try:
                sender = await message.get_sender()
            except Exception:
                sender = None
        if isinstance(sender, User):
            if sender.bot:
                return
            first_name = sender.first_name or ""
            last_name = sender.last_name
            username = sender.username

        row = await self._get_or_create(
            mirror_chat.id,
            message.sender_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )
        row.message_count += 1
        row.last_active_at = message.date or datetime.now(timezone.utc)
        await self.db.flush()

    async def record_reaction(
        self,
        telegram_chat_id: int,
        telegram_user_id: int,
        *,
        first_name: str = "",
        last_name: str | None = None,
        username: str | None = None,
    ) -> None:
        mirror_chat = await self._resolve_mirror_chat(telegram_chat_id)
        if not mirror_chat:
            return

        row = await self._get_or_create(
            mirror_chat.id,
            telegram_user_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
        )
        row.reaction_count += 1
        row.last_active_at = datetime.now(timezone.utc)
        await self.db.flush()

    async def record_reaction_peer(self, telegram_chat_id: int, peer) -> None:
        if not isinstance(peer, PeerUser):
            return
        await self.record_reaction(telegram_chat_id, peer.user_id)
