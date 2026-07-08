from __future__ import annotations

from typing import Any

from telethon import TelegramClient
from telethon.errors import UserIdInvalidError

from app.models import InviteTarget


def normalize_username(raw: str | None) -> str | None:
    if not raw:
        return None
    username = raw.strip().lstrip("@").lower()
    return username or None


async def resolve_target_user(client: TelegramClient, target: InviteTarget) -> Any:
    """Всегда по @username — не по числовому user_id (кэш Telethon)."""
    username = normalize_username(target.username)
    if not username:
        raise UserIdInvalidError(request=None)  # type: ignore[arg-type]
    return await client.get_entity(username)
