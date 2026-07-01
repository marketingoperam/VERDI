"""Импорт и проверка Telethon-сессий."""

from __future__ import annotations

import re
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import get_settings
from app.models import SessionPool, SessionType

logger = structlog.get_logger()

SESSION_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{2,64}$")


class SessionImportService:
    def _validate_name(self, session_name: str) -> str:
        name = session_name.strip()
        if not SESSION_NAME_RE.match(name):
            raise ValueError(
                "Имя сессии: только латиница, цифры, _ и - (2–64 символа)"
            )
        return name

    def _resolve_api(self, api_id: int | None, api_hash: str | None) -> tuple[int, str]:
        settings = get_settings()
        resolved_id = api_id or settings.listener_api_id
        resolved_hash = api_hash or settings.listener_api_hash
        if not resolved_id or not resolved_hash:
            raise ValueError("Укажите API ID и API Hash (в форме или в .env)")
        return resolved_id, resolved_hash

    def _session_file_path(self, session_name: str) -> Path:
        settings = get_settings()
        return settings.resolved_sessions_dir / f"{session_name}.session"

    async def _verify_client(self, client: TelegramClient) -> dict:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            raise ValueError("Сессия не авторизована или устарела")
        me = await client.get_me()
        await client.disconnect()
        return {
            "telegram_user_id": me.id,
            "first_name": me.first_name,
            "username": me.username,
            "phone": me.phone,
        }

    async def verify_existing(
        self,
        session_name: str,
        api_id: int,
        api_hash: str,
        session_string: str | None = None,
    ) -> dict:
        if session_string:
            client = TelegramClient(StringSession(session_string), api_id, api_hash)
        else:
            path = self._session_file_path(session_name)
            if not path.exists():
                raise ValueError("Файл сессии не найден")
            client = TelegramClient(
                str(path.parent / path.stem), api_id, api_hash
            )
        return await self._verify_client(client)

    async def _register_session(
        self,
        db: AsyncSession,
        session_name: str,
        api_id: int,
        api_hash: str,
        session_string: str | None,
        user_info: dict,
    ) -> SessionPool:
        result = await db.execute(
            select(SessionPool).where(SessionPool.session_name == session_name)
        )
        pool = result.scalar_one_or_none()
        if pool:
            pool.api_id = api_id
            pool.api_hash = api_hash
            pool.session_string = session_string
            pool.is_active = True
        else:
            pool = SessionPool(
                session_name=session_name,
                session_type=SessionType.USER.value,
                api_id=api_id,
                api_hash=api_hash,
                session_string=session_string,
                is_active=True,
                is_fallback=False,
                binding_mode="permanent",
            )
            db.add(pool)
        await db.flush()
        await db.refresh(pool)
        logger.info(
            "session_imported",
            session_name=session_name,
            user_id=user_info.get("telegram_user_id"),
            has_string=bool(session_string),
        )
        return pool

    async def import_file(
        self,
        db: AsyncSession,
        session_name: str,
        file_bytes: bytes,
        api_id: int | None = None,
        api_hash: str | None = None,
        journal_bytes: bytes | None = None,
    ) -> dict:
        name = self._validate_name(session_name)
        api_id, api_hash = self._resolve_api(api_id, api_hash)

        settings = get_settings()
        settings.resolved_sessions_dir.mkdir(parents=True, exist_ok=True)
        dest = self._session_file_path(name)
        dest.write_bytes(file_bytes)
        if journal_bytes:
            dest.with_name(f"{name}.session-journal").write_bytes(journal_bytes)

        user_info: dict = {}
        verify_warning: str | None = None
        try:
            user_info = await self.verify_existing(name, api_id, api_hash, session_string=None)
        except Exception as exc:
            verify_warning = str(exc)
            logger.warning("session_verify_failed", session_name=name, error=verify_warning)

        pool = await self._register_session(db, name, api_id, api_hash, None, user_info)
        result = {
            "session_id": pool.id,
            "session_name": name,
            "status": "imported" if not verify_warning else "imported_offline",
            **user_info,
        }
        if verify_warning:
            result["verify_warning"] = verify_warning
        return result

    async def import_string(
        self,
        db: AsyncSession,
        session_name: str,
        session_string: str,
        api_id: int | None = None,
        api_hash: str | None = None,
    ) -> dict:
        name = self._validate_name(session_name)
        api_id, api_hash = self._resolve_api(api_id, api_hash)
        session_string = session_string.strip()
        if len(session_string) < 20:
            raise ValueError("Некорректная строка сессии Telethon")

        user_info: dict = {}
        verify_warning: str | None = None
        try:
            user_info = await self.verify_existing(
                name, api_id, api_hash, session_string=session_string
            )
        except Exception as exc:
            verify_warning = str(exc)
            logger.warning("session_verify_failed", session_name=name, error=verify_warning)

        pool = await self._register_session(
            db, name, api_id, api_hash, session_string, user_info
        )
        result = {
            "session_id": pool.id,
            "session_name": name,
            "status": "imported" if not verify_warning else "imported_offline",
            **user_info,
        }
        if verify_warning:
            result["verify_warning"] = verify_warning
        return result

    async def sync_disk_sessions(self, db: AsyncSession) -> int:
        """Register .session files on disk that are missing from the database."""
        settings = get_settings()
        sessions_dir = settings.resolved_sessions_dir
        if not sessions_dir.exists():
            return 0

        try:
            api_id, api_hash = self._resolve_api(None, None)
        except ValueError:
            return 0

        added = 0
        for path in sorted(sessions_dir.glob("*.session")):
            name = path.stem
            if not SESSION_NAME_RE.match(name):
                continue
            result = await db.execute(
                select(SessionPool).where(SessionPool.session_name == name)
            )
            if result.scalar_one_or_none():
                continue
            db.add(
                SessionPool(
                    session_name=name,
                    session_type=SessionType.USER.value,
                    api_id=api_id,
                    api_hash=api_hash,
                    is_active=True,
                    is_fallback=False,
                    binding_mode="permanent",
                )
            )
            added += 1
            logger.info("session_synced_from_disk", session_name=name)

        if added:
            await db.flush()
        return added


session_import_service = SessionImportService()
