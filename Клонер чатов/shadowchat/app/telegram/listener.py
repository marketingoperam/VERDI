import asyncio
import signal

import structlog
from sqlalchemy import select
from telethon import events, utils
from telethon.tl.types import UpdateMessageReactions

from app.config import get_settings
from app.db import async_session_factory
from app.models import MirrorChat, SourceChat
from app.services.activity_config import ACTIVITY_MIRROR_USERNAMES
from app.services.activity_tracker import ActivityTracker
from app.services.ai_mirror import get_ai_mirror_store
from app.services.mirror_cleanup import (
    delete_mirror_service_message,
    mirror_service_should_delete,
    purge_all_mirror_chats,
)
from app.telegram.dispatcher import MessageDispatcher
from app.telegram.media_handler import MediaHandler
from app.telegram.mirror_sender import MirrorSender
from app.telegram.proxy import chat_id_variants
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()

RECONNECT_DELAY_SEC = 15


class TelegramListener:
    def __init__(self):
        self.settings = get_settings()
        self.session_pool = SessionPoolManager(async_session_factory)
        self.mirror_sender = MirrorSender(self.session_pool, MediaHandler())
        self._running = False
        self._connected = False

    async def _get_active_chat_ids(self) -> set[int]:
        async with async_session_factory() as db:
            result = await db.execute(
                select(SourceChat.telegram_chat_id).where(SourceChat.is_active.is_(True))
            )
            ids: set[int] = set()
            for row in result.scalars().all():
                ids.update(chat_id_variants(row))
            return ids

    def _is_tracked_chat(self, event_chat_id: int, active_ids: set[int]) -> bool:
        return bool(chat_id_variants(event_chat_id) & active_ids)

    async def _get_activity_mirror_ids(self) -> set[int]:
        async with async_session_factory() as db:
            result = await db.execute(
                select(MirrorChat.telegram_chat_id).where(
                    MirrorChat.mirror_username.in_(ACTIVITY_MIRROR_USERNAMES),
                    MirrorChat.is_active.is_(True),
                )
            )
            ids: set[int] = set()
            for row in result.scalars().all():
                ids.update(chat_id_variants(row))
            return ids

    async def _get_mirror_chat_ids(self) -> list[int]:
        store = get_ai_mirror_store()
        seen: set[int] = set()
        ids: list[int] = []
        for route in store.routes:
            if route.mirror_chat_id not in seen:
                seen.add(route.mirror_chat_id)
                ids.append(route.mirror_chat_id)
        return ids

    async def _setup_mirror_cleanup(self, client) -> None:
        mirror_ids = await self._get_mirror_chat_ids()
        if not mirror_ids:
            return

        entities = []
        for mid in mirror_ids:
            try:
                entities.append(await client.get_entity(mid))
            except Exception as exc:
                logger.warning("mirror_entity_resolve_failed", chat_id=mid, error=str(exc))

        if not entities:
            return

        @client.on(events.NewMessage(chats=entities))
        async def on_mirror_message(event):
            if not self._running:
                return

            activity_ids = await self._get_activity_mirror_ids()
            if self._is_tracked_chat(event.chat_id, activity_ids):
                try:
                    async with async_session_factory() as db:
                        await ActivityTracker(db).record_message(event.message, event.chat_id)
                        await db.commit()
                except Exception as exc:
                    logger.warning("activity_record_failed", error=str(exc))

            if not mirror_service_should_delete(event.message):
                return
            if await delete_mirror_service_message(client, event.chat_id, event.message):
                logger.info(
                    "mirror_service_deleted",
                    chat_id=event.chat_id,
                    message_id=event.message.id,
                )

        asyncio.create_task(purge_all_mirror_chats(client, mirror_ids, limit=500))

    def _register_handlers(self, client) -> None:
        @client.on(events.NewMessage())
        async def on_new_message(event):
            if not self._running:
                return
            active = await self._get_active_chat_ids()
            if not self._is_tracked_chat(event.chat_id, active):
                return
            logger.info(
                "new_message_received",
                chat_id=event.chat_id,
                message_id=event.message.id,
                has_text=bool(event.message.message or event.message.text),
            )
            try:
                async with async_session_factory() as db:
                    dispatcher = MessageDispatcher(db, self.session_pool, self.mirror_sender)
                    await dispatcher.handle_new_message(event.message, event.chat_id)
            except Exception as exc:
                logger.error(
                    "new_message_handler_failed",
                    chat_id=event.chat_id,
                    message_id=event.message.id,
                    error=str(exc).encode("ascii", "backslashreplace").decode(),
                    exc_info=True,
                )

        @client.on(events.MessageEdited())
        async def on_message_edited(event):
            if not self._running:
                return
            active = await self._get_active_chat_ids()
            if not self._is_tracked_chat(event.chat_id, active):
                return
            try:
                async with async_session_factory() as db:
                    dispatcher = MessageDispatcher(db, self.session_pool, self.mirror_sender)
                    await dispatcher.handle_edit(event.message, event.chat_id)
            except Exception as exc:
                logger.error("edit_handler_failed", error=str(exc))

        @client.on(events.MessageDeleted())
        async def on_message_deleted(event):
            if not self._running:
                return
            if not event.chat_id:
                return
            active = await self._get_active_chat_ids()
            if not self._is_tracked_chat(event.chat_id, active):
                return
            try:
                async with async_session_factory() as db:
                    dispatcher = MessageDispatcher(db, self.session_pool, self.mirror_sender)
                    await dispatcher.handle_delete(event.chat_id, list(event.deleted_ids))
            except Exception as exc:
                logger.error("delete_handler_failed", error=str(exc))

        @client.on(events.Raw(types=UpdateMessageReactions))
        async def on_reaction_update(update):
            if not self._running:
                return
            active = await self._get_activity_mirror_ids()
            chat_id = utils.get_peer_id(update.peer)
            if not self._is_tracked_chat(chat_id, active):
                return
            recent = getattr(update.reactions, "recent_reactions", None) or []
            if not recent:
                return
            try:
                async with async_session_factory() as db:
                    tracker = ActivityTracker(db)
                    for item in recent:
                        await tracker.record_reaction_peer(chat_id, item.peer_id)
                    await db.commit()
            except Exception as exc:
                logger.warning("activity_reaction_failed", error=str(exc))

    async def _listen_once(self) -> None:
        client = await asyncio.wait_for(
            self.session_pool.get_listener_client(),
            timeout=45.0,
        )
        chat_ids = await self._get_active_chat_ids()
        if not chat_ids:
            logger.warning("no_active_source_chats_configured")

        self._register_handlers(client)
        await self._setup_mirror_cleanup(client)
        self._connected = client.is_connected()
        logger.info("listener_started", active_chats=len(chat_ids))
        await client.run_until_disconnected()
        self._connected = False

    async def start(self) -> None:
        self._running = True
        while self._running:
            try:
                await self._listen_once()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    "listener_session_failed",
                    error=str(exc).encode("ascii", "backslashreplace").decode(),
                    exc_info=True,
                )
                self._connected = False

            if not self._running:
                break

            logger.warning("listener_reconnecting", delay_sec=RECONNECT_DELAY_SEC)
            await self.session_pool.reset_listener_client()
            await asyncio.sleep(RECONNECT_DELAY_SEC)

    async def stop(self) -> None:
        logger.info("listener_stopping")
        self._running = False
        self._connected = False
        await self.session_pool.reset_listener_client()
        await self.session_pool.disconnect_all()
        logger.info("listener_stopped")

    def is_connected(self) -> bool:
        client = self.session_pool._listener_client
        return bool(self._running and client and client.is_connected())

    async def run_until_stopped(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))
            except NotImplementedError:
                pass

        try:
            await self.start()
        except asyncio.CancelledError:
            await self.stop()


async def run_listener() -> None:
    listener = TelegramListener()
    await listener.run_until_stopped()
