import asyncio
import signal

import structlog
from sqlalchemy import select
from telethon import events

from app.config import get_settings
from app.db import async_session_factory
from app.models import SourceChat
from app.telegram.dispatcher import MessageDispatcher
from app.telegram.media_handler import MediaHandler
from app.telegram.mirror_sender import MirrorSender
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()


class TelegramListener:
    def __init__(self):
        self.settings = get_settings()
        self.session_pool = SessionPoolManager(async_session_factory)
        self.mirror_sender = MirrorSender(self.session_pool, MediaHandler())
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def _get_active_chat_ids(self) -> list[int]:
        async with async_session_factory() as db:
            result = await db.execute(
                select(SourceChat.telegram_chat_id).where(SourceChat.is_active.is_(True))
            )
            return list(result.scalars().all())

    async def start(self) -> None:
        self._running = True
        try:
            client = await asyncio.wait_for(
                self.session_pool.get_listener_client(),
                timeout=15.0,
            )
        except Exception as exc:
            logger.error("listener_connect_failed", error=str(exc))
            self._running = False
            return

        chat_ids = await self._get_active_chat_ids()
        if not chat_ids:
            logger.warning("no_active_source_chats_configured")

        @client.on(events.NewMessage())
        async def on_new_message(event):
            if not self._running:
                return
            if event.chat_id not in await self._get_active_chat_ids():
                return
            async with async_session_factory() as db:
                dispatcher = MessageDispatcher(db, self.session_pool, self.mirror_sender)
                await dispatcher.handle_new_message(event.message, event.chat_id)

        @client.on(events.MessageEdited())
        async def on_message_edited(event):
            if not self._running:
                return
            if event.chat_id not in await self._get_active_chat_ids():
                return
            async with async_session_factory() as db:
                dispatcher = MessageDispatcher(db, self.session_pool, self.mirror_sender)
                await dispatcher.handle_edit(event.message, event.chat_id)

        @client.on(events.MessageDeleted())
        async def on_message_deleted(event):
            if not self._running:
                return
            if not event.chat_id:
                return
            async with async_session_factory() as db:
                dispatcher = MessageDispatcher(db, self.session_pool, self.mirror_sender)
                await dispatcher.handle_delete(event.chat_id, list(event.deleted_ids))

        logger.info("listener_started", active_chats=len(chat_ids))

        try:
            await client.run_until_disconnected()
        except Exception as exc:
            if self._running:
                logger.error("listener_crashed", error=str(exc), exc_info=True)
                raise

    async def stop(self) -> None:
        logger.info("listener_stopping")
        self._running = False
        if self.session_pool._listener_client:
            try:
                await self.session_pool._listener_client.disconnect()
            except Exception:
                pass
        await self.session_pool.disconnect_all()
        logger.info("listener_stopped")

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
