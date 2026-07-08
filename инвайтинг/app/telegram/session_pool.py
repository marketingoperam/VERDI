from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.sessions import StringSession

from app.config import get_settings
from app.models import Account
from app.telegram.proxy import parse_proxy, proxy_label

logger = structlog.get_logger()


class LocalSessionPool:
    """Клиенты Telethon из StringSession в БД (не из файлов .session)."""

    def __init__(
        self,
        db_factory: async_sessionmaker[AsyncSession] | None = None,
        sessions_dir: Path | None = None,
    ):
        self.settings = get_settings()
        self._db_factory = db_factory
        self.sessions_dir = sessions_dir or self.settings.resolved_sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._clients: dict[str, TelegramClient] = {}
        self._lock = asyncio.Lock()

    def bind_db(self, db_factory: async_sessionmaker[AsyncSession]) -> None:
        self._db_factory = db_factory

    def _proxy(self) -> tuple | None:
        raw = self.settings.tg_proxy.strip()
        if not raw:
            return None
        proxy = parse_proxy(raw, self.settings.tg_proxy_type)
        logger.info("telethon_proxy", via=proxy_label(proxy))
        return proxy

    async def _load_account(self, name: str) -> Account | None:
        if not self._db_factory:
            return None
        async with self._db_factory() as db:
            res = await db.execute(select(Account).where(Account.name == name))
            return res.scalar_one_or_none()

    async def get_client(self, session_name: str) -> TelegramClient:
        if session_name in self._clients and self._clients[session_name].is_connected():
            return self._clients[session_name]

        async with self._lock:
            if session_name in self._clients and self._clients[session_name].is_connected():
                return self._clients[session_name]

            account = await self._load_account(session_name)
            if not account or not account.session_string or not account.is_authorized:
                raise RuntimeError(
                    f"Аккаунт '{session_name}' не авторизован. Войдите по телефону+коду во вкладке «Аккаунты»."
                )

            proxy = self._proxy()
            client = TelegramClient(
                StringSession(account.session_string),
                self.settings.tg_api_id,
                self.settings.tg_api_hash,
                proxy=proxy,
                use_ipv6=False,
                connection_retries=8,
                retry_delay=2,
                timeout=30,
                request_retries=5,
            )
            await client.connect()
            if not await client.is_user_authorized():
                raise RuntimeError(f"Аккаунт '{session_name}' потерял авторизацию — войдите заново по коду")
            self._clients[session_name] = client
            return client

    async def drop_client(self, session_name: str) -> None:
        client = self._clients.pop(session_name, None)
        if not client:
            return
        try:
            await client.disconnect()
        except Exception:
            pass

    async def disconnect_all(self) -> None:
        for name, client in list(self._clients.items()):
            try:
                await client.disconnect()
            except Exception:
                pass
            self._clients.pop(name, None)

    @staticmethod
    async def with_flood_wait_retry(coro_factory, max_retries: int = 3):
        for attempt in range(max_retries):
            try:
                return await coro_factory()
            except FloodWaitError as exc:
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep(exc.seconds + 1)
