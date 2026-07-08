"""Удаление сервисных сообщений в зеркалах: вступил, пригласил, вышел и т.п."""

from __future__ import annotations

import asyncio

import structlog
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.types import MessageService

logger = structlog.get_logger()

def mirror_service_should_delete(message) -> bool:
    if isinstance(message, MessageService):
        return True
    text = message.message or ""
    if "Сообщение удалено в исходном чате" in text:
        return True
    return False


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
        except Exception as exc2:
            logger.warning("mirror_delete_failed", message_id=message.id, error=str(exc2))
            return False
    except Exception as exc:
        logger.warning("mirror_delete_failed", message_id=message.id, error=str(exc))
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
            await asyncio.sleep(0.15 if deleted % 20 else 0.05)
        except FloodWaitError as exc:
            await asyncio.sleep(exc.seconds + 1)
        except Exception:
            continue
    return deleted


async def purge_all_mirror_chats(
    client: TelegramClient,
    mirror_chat_ids: list[int],
    *,
    limit: int = 1000,
) -> dict[int, int]:
    stats: dict[int, int] = {}
    for chat_id in mirror_chat_ids:
        try:
            entity = await client.get_entity(chat_id)
            count = await purge_mirror_service_messages(client, entity, limit=limit)
            stats[chat_id] = count
            if count:
                title = getattr(entity, "title", chat_id)
                logger.info("mirror_service_purged", chat=title, deleted=count)
        except Exception as exc:
            logger.warning("mirror_purge_failed", chat_id=chat_id, error=str(exc))
            stats[chat_id] = 0
    return stats
