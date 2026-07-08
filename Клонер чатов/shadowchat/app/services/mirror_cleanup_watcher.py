"""Фоновая очистка сервисных сообщений в зеркалах (параллельно с listener)."""

from __future__ import annotations

import asyncio

import structlog
from telethon import events

from app.config import get_settings
from app.db import async_session_factory
from app.services.ai_mirror import get_ai_mirror_store
from app.services.mirror_cleanup import (
    delete_mirror_service_message,
    mirror_service_should_delete,
    purge_all_mirror_chats,
)
from app.telegram.session_copy import copy_session_path, refresh_session_copy
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()

RECONNECT_DELAY_SEC = 20


class MirrorCleanupWatcher:
    def __init__(self, *, startup_purge_limit: int = 500):
        self.settings = get_settings()
        self.startup_purge_limit = startup_purge_limit
        self._running = False
        self._pool = SessionPoolManager(async_session_factory)
        self._client = None

    async def _mirror_ids(self) -> list[int]:
        store = get_ai_mirror_store()
        seen: set[int] = set()
        ids: list[int] = []
        for route in store.routes:
            if route.mirror_chat_id not in seen:
                seen.add(route.mirror_chat_id)
                ids.append(route.mirror_chat_id)
        return ids

    async def _connect(self):
        session_name = self.settings.listener_session
        path = copy_session_path(session_name, tag="cleanup")
        client = self._pool._make_client(
            path,
            self.settings.listener_api_id,
            self.settings.listener_api_hash,
        )
        await client.connect()
        if not await client.is_user_authorized():
            raise RuntimeError(f"{session_name} не авторизован")
        self._client = client
        return client

    async def _disconnect(self) -> None:
        if self._client:
            try:
                await self._client.disconnect()
            except Exception:
                pass
        self._client = None

    async def _watch_once(self) -> None:
        client = await self._connect()
        mirror_ids = await self._mirror_ids()
        if not mirror_ids:
            logger.warning("mirror_cleanup_no_chats")
            return

        entities = []
        for mid in mirror_ids:
            try:
                entities.append(await client.get_entity(mid))
            except Exception as exc:
                logger.warning("mirror_cleanup_entity_failed", chat_id=mid, error=str(exc))

        if not entities:
            return

        asyncio.create_task(self._startup_purge(client, mirror_ids))

        @client.on(events.NewMessage(chats=entities))
        async def on_mirror_service(event):
            if not self._running:
                return
            if not mirror_service_should_delete(event.message):
                return
            if await delete_mirror_service_message(client, event.chat_id, event.message):
                logger.info(
                    "mirror_service_deleted",
                    chat_id=event.chat_id,
                    message_id=event.message.id,
                )

        logger.info("mirror_cleanup_watcher_started", mirrors=len(entities))
        await client.run_until_disconnected()

    async def _startup_purge(self, client, mirror_ids: list[int]) -> None:
        try:
            stats = await purge_all_mirror_chats(
                client, mirror_ids, limit=self.startup_purge_limit
            )
            total = sum(stats.values())
            if total:
                logger.info("mirror_service_startup_purge", deleted=total)
        except Exception as exc:
            logger.warning("mirror_service_startup_purge_failed", error=str(exc))

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._watch_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "mirror_cleanup_session_failed",
                    error=str(exc).encode("ascii", "backslashreplace").decode(),
                    exc_info=True,
                )

            await self._disconnect()
            if not self._running:
                break

            refresh_session_copy(self.settings.listener_session, tag="cleanup")
            logger.warning("mirror_cleanup_reconnecting", delay_sec=RECONNECT_DELAY_SEC)
            await asyncio.sleep(RECONNECT_DELAY_SEC)

    async def stop(self) -> None:
        self._running = False
        await self._disconnect()
        logger.info("mirror_cleanup_watcher_stopped")

    def is_connected(self) -> bool:
        return bool(self._running and self._client and self._client.is_connected())
