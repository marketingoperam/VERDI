import asyncio
from datetime import datetime, timezone
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from app.config import get_settings
from app.models import SessionPool, SessionType

logger = structlog.get_logger()


class SessionPoolManager:
    def __init__(self, db_factory, sessions_dir: Path | None = None):
        self._db_factory = db_factory
        self.settings = get_settings()
        self.sessions_dir = sessions_dir or self.settings.resolved_sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._clients: dict[str, TelegramClient] = {}
        self._listener_client: TelegramClient | None = None
        self._lock = asyncio.Lock()

    def _session_path(self, session_name: str) -> str:
        return str(self.sessions_dir / session_name)

    async def get_listener_client(self) -> TelegramClient:
        if self._listener_client and self._listener_client.is_connected():
            return self._listener_client

        async with self._lock:
            if self._listener_client and self._listener_client.is_connected():
                return self._listener_client

            client = TelegramClient(
                self._session_path(self.settings.listener_session),
                self.settings.listener_api_id,
                self.settings.listener_api_hash,
            )
            await client.connect()
            if not await client.is_user_authorized():
                logger.error("listener_not_authorized", session=self.settings.listener_session)
            self._listener_client = client
            return client

    async def get_client_for_session(self, session: SessionPool) -> TelegramClient:
        if session.session_name in self._clients:
            client = self._clients[session.session_name]
            if client.is_connected():
                return client

        async with self._lock:
            if session.session_name in self._clients:
                client = self._clients[session.session_name]
                if client.is_connected():
                    return client

            if session.session_type == SessionType.BOT.value and session.bot_token:
                client = TelegramClient(
                    StringSession(),
                    session.api_id,
                    session.api_hash,
                )
                await client.start(bot_token=session.bot_token)
            elif getattr(session, "session_string", None):
                client = TelegramClient(
                    StringSession(session.session_string),
                    session.api_id,
                    session.api_hash,
                )
                await client.connect()
                if not await client.is_user_authorized():
                    raise RuntimeError(f"Session {session.session_name} is not authorized")
            else:
                client = TelegramClient(
                    self._session_path(session.session_name),
                    session.api_id,
                    session.api_hash,
                )
                await client.connect()
                if not await client.is_user_authorized():
                    raise RuntimeError(f"Session {session.session_name} is not authorized")

            self._clients[session.session_name] = client
            asyncio.create_task(self._update_last_used(session.id))
            return client

    async def get_client_by_id(self, session_pool_id: int) -> TelegramClient | None:
        async with self._db_factory() as db:
            result = await db.execute(
                select(SessionPool).where(SessionPool.id == session_pool_id)
            )
            session = result.scalar_one_or_none()
            if not session or not session.is_active:
                return None
            return await self.get_client_for_session(session)

    async def load_all_active_sessions(self) -> list[TelegramClient]:
        async with self._db_factory() as db:
            result = await db.execute(
                select(SessionPool).where(SessionPool.is_active.is_(True))
            )
            sessions = result.scalars().all()

        clients = []
        for session in sessions:
            try:
                client = await self.get_client_for_session(session)
                clients.append(client)
            except Exception as exc:
                logger.error(
                    "session_load_failed",
                    session_name=session.session_name,
                    error=str(exc),
                )
        return clients

    async def _update_last_used(self, session_id: int) -> None:
        try:
            async with self._db_factory() as db:
                result = await db.execute(select(SessionPool).where(SessionPool.id == session_id))
                session = result.scalar_one_or_none()
                if session:
                    session.last_used_at = datetime.now(timezone.utc)
                    await db.commit()
        except Exception as exc:
            logger.warning("last_used_update_failed", session_id=session_id, error=str(exc))

    async def disconnect_all(self) -> None:
        for name, client in list(self._clients.items()):
            try:
                await client.disconnect()
            except Exception as exc:
                logger.warning("disconnect_failed", session=name, error=str(exc))
        self._clients.clear()

        if self._listener_client:
            try:
                await self._listener_client.disconnect()
            except Exception:
                pass
            self._listener_client = None

    @staticmethod
    async def with_flood_wait_retry(coro_factory, max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                return await coro_factory()
            except FloodWaitError as exc:
                if attempt == max_retries - 1:
                    raise
                wait_seconds = exc.seconds + 1
                logger.warning("flood_wait", seconds=wait_seconds, attempt=attempt + 1)
                await asyncio.sleep(wait_seconds)
