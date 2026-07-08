"""Разовая очистка сервисных сообщений во всех зеркальных чатах VERDI.

Работает параллельно с клонером (использует копию .session, без блокировки).

Запуск из папки shadowchat:
  python scripts/purge_service_messages.py
  python scripts/purge_service_messages.py --limit 500
  python scripts/purge_service_messages.py --watch
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

from telethon import events

from app.config import get_settings
from app.db import async_session_factory
from app.services.ai_mirror import get_ai_mirror_store
from app.services.mirror_cleanup import (
    delete_mirror_service_message,
    mirror_service_should_delete,
    purge_all_mirror_chats,
)
from app.telegram.session_copy import copy_session_path
from app.telegram.session_pool import SessionPoolManager


async def _mirror_ids() -> list[int]:
    store = get_ai_mirror_store()
    seen: set[int] = set()
    ids: list[int] = []
    for route in store.routes:
        if route.mirror_chat_id not in seen:
            seen.add(route.mirror_chat_id)
            ids.append(route.mirror_chat_id)
    return ids


async def _connect_copy_client():
    settings = get_settings()
    pool = SessionPoolManager(async_session_factory)
    path = copy_session_path(settings.listener_session, tag="purge_script")
    client = pool._make_client(
        path,
        settings.listener_api_id,
        settings.listener_api_hash,
    )
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError("listener_main не авторизован")
    return client


async def run_purge(limit: int) -> None:
    client = await _connect_copy_client()

    mirror_ids = await _mirror_ids()
    print(f"Зеркал: {len(mirror_ids)} | лимит сообщений на чат: {limit}\n")

    stats = await purge_all_mirror_chats(client, mirror_ids, limit=limit)
    total = sum(stats.values())
    for chat_id, count in stats.items():
        if count:
            print(f"  {chat_id}: удалено {count}")
    print(f"\nГотово. Всего удалено: {total}")
    await client.disconnect()


async def run_watch() -> None:
    client = await _connect_copy_client()

    mirror_ids = await _mirror_ids()
    mirrors = []
    for mid in mirror_ids:
        ent = await client.get_entity(mid)
        mirrors.append(ent)
        print(f"  • {getattr(ent, 'title', mid)}")

    print(f"\nСлежу за {len(mirrors)} зеркалами (параллельно с клонером). Ctrl+C для остановки.\n")

    @client.on(events.NewMessage(chats=mirrors))
    async def on_service(event):
        if not mirror_service_should_delete(event.message):
            return
        if await delete_mirror_service_message(client, event.chat_id, event.message):
            label = getattr(event.chat, "title", event.chat_id)
            print(f"  🗑 удалено сервисное в «{label}» #{event.message.id}")

    await client.run_until_disconnected()


def main() -> None:
    p = argparse.ArgumentParser(description="Очистка сервисных сообщений в зеркалах")
    p.add_argument("--limit", type=int, default=1000, help="сколько последних сообщений просмотреть в каждом чате")
    p.add_argument(
        "--watch",
        action="store_true",
        help="не выходить: удалять новые сервисные сообщения по мере появления",
    )
    args = p.parse_args()

    if args.watch:
        asyncio.run(run_watch())
    else:
        asyncio.run(run_purge(args.limit))


if __name__ == "__main__":
    main()
