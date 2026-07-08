"""Удаление сервисных сообщений в зеркальных чатах (вступил, пригласил и т.п.)."""

from __future__ import annotations

import asyncio

from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import (
    MessageActionChatAddUser,
    MessageActionChatDeleteUser,
    MessageActionChatJoinedByLink,
    MessageActionChatJoinedByRequest,
    MessageService,
)

JOIN_SERVICE_ACTIONS = (
    MessageActionChatAddUser,
    MessageActionChatJoinedByLink,
    MessageActionChatJoinedByRequest,
    MessageActionChatDeleteUser,
)


def mirror_service_should_delete(message) -> bool:
    if not isinstance(message, MessageService):
        return False
    return isinstance(message.action, JOIN_SERVICE_ACTIONS)


async def delete_mirror_service_message(client: TelegramClient, chat, message) -> bool:
    if not mirror_service_should_delete(message):
        return False
    try:
        await client.delete_messages(chat, message.id)
        return True
    except FloodWaitError as exc:
        await asyncio.sleep(exc.seconds + 1)
        try:
            await client.delete_messages(chat, message.id)
            return True
        except Exception:
            return False
    except Exception:
        return False


async def purge_mirror_service_messages(
    client: TelegramClient,
    mirror,
    *,
    limit: int = 1000,
) -> int:
    deleted = 0
    async for msg in client.iter_messages(mirror, limit=limit):
        if not mirror_service_should_delete(msg):
            continue
        try:
            await client.delete_messages(mirror, msg.id)
            deleted += 1
            if deleted % 20 == 0:
                await asyncio.sleep(0.3)
            else:
                await asyncio.sleep(0.1)
        except FloodWaitError as exc:
            await asyncio.sleep(exc.seconds + 1)
        except Exception:
            continue
    return deleted
