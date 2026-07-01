"""Веб-авторизация технических Telegram-аккаунтов через Telethon."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import (
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from app.config import get_settings
from app.models import SessionPool

logger = structlog.get_logger()


@dataclass
class PendingAuth:
    client: TelegramClient
    phone: str
    phone_code_hash: str
    needs_password: bool = False
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


@dataclass
class PendingQrAuth:
    client: TelegramClient
    qr_login: object
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


class SessionAuthService:
    _pending: dict[int, PendingAuth] = {}
    _pending_qr: dict[int, PendingQrAuth] = {}
    _lock = asyncio.Lock()
    _TTL = timedelta(minutes=30)

    def _session_path(self, session_name: str) -> str:
        settings = get_settings()
        return str(settings.resolved_sessions_dir / session_name)

    async def _cleanup_expired(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [
            sid
            for sid, p in self._pending.items()
            if p.created_at and now - p.created_at > self._TTL
        ]
        for sid in expired:
            await self._discard(sid)
        expired_qr = [
            sid
            for sid, p in self._pending_qr.items()
            if p.created_at and now - p.created_at > self._TTL
        ]
        for sid in expired_qr:
            await self._discard(sid)

    async def _discard(self, session_id: int) -> None:
        pending = self._pending.pop(session_id, None)
        if pending:
            try:
                await pending.client.disconnect()
            except Exception:
                pass
        qr = self._pending_qr.pop(session_id, None)
        if qr:
            try:
                await qr.client.disconnect()
            except Exception:
                pass

    async def get_status(self, db: AsyncSession, session_id: int) -> dict:
        session = await self._get_session(db, session_id)
        settings = get_settings()
        path = settings.resolved_sessions_dir / f"{session.session_name}.session"

        if path.exists():
            client = TelegramClient(
                str(path.parent / path.stem),
                session.api_id,
                session.api_hash,
            )
            try:
                await client.connect()
                if await client.is_user_authorized():
                    me = await client.get_me()
                    return {
                        "status": "authorized",
                        "phone": me.phone,
                        "first_name": me.first_name,
                        "username": me.username,
                        "telegram_user_id": me.id,
                    }
            finally:
                await client.disconnect()

        if session.session_string:
            client = TelegramClient(
                StringSession(session.session_string),
                session.api_id,
                session.api_hash,
            )
            try:
                await client.connect()
                if await client.is_user_authorized():
                    me = await client.get_me()
                    return {
                        "status": "authorized",
                        "phone": me.phone,
                        "first_name": me.first_name,
                        "username": me.username,
                        "telegram_user_id": me.id,
                    }
            finally:
                await client.disconnect()

        if session_id in self._pending:
            p = self._pending[session_id]
            return {
                "status": "need_password" if p.needs_password else "code_sent",
                "phone": p.phone,
            }

        if session_id in self._pending_qr:
            return {
                "status": "qr_pending",
                "qr_url": self._pending_qr[session_id].qr_login.url,
            }

        return {
            "status": "need_phone",
            "api_id": session.api_id,
            "api_hash": session.api_hash,
        }

    async def send_code(
        self,
        db: AsyncSession,
        session_id: int,
        phone: str,
        api_id: int | None = None,
        api_hash: str | None = None,
    ) -> dict:
        await self._cleanup_expired()
        session = await self._get_session(db, session_id)

        if api_id and api_hash:
            session.api_id = api_id
            session.api_hash = api_hash
            await db.flush()

        await self._discard(session_id)

        phone = phone.strip().replace(" ", "")
        if not phone.startswith("+"):
            phone = "+" + phone

        client = TelegramClient(
            self._session_path(session.session_name),
            session.api_id,
            session.api_hash,
        )
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            return {
                "status": "authorized",
                "phone": me.phone,
                "first_name": me.first_name,
                "username": me.username,
            }

        try:
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError as exc:
            await client.disconnect()
            raise ValueError("Неверный номер телефона") from exc

        async with self._lock:
            self._pending[session_id] = PendingAuth(
                client=client,
                phone=phone,
                phone_code_hash=sent.phone_code_hash,
            )

        logger.info("auth_code_sent", session_id=session_id, phone=phone[-4:])
        return {"status": "code_sent", "phone": phone}

    async def verify_code(self, db: AsyncSession, session_id: int, code: str) -> dict:
        pending = self._pending.get(session_id)
        if not pending:
            raise ValueError("Сначала отправьте код на номер телефона")

        code = code.strip().replace(" ", "")
        try:
            await pending.client.sign_in(
                pending.phone,
                code,
                phone_code_hash=pending.phone_code_hash,
            )
        except SessionPasswordNeededError:
            pending.needs_password = True
            return {"status": "need_password", "phone": pending.phone}
        except PhoneCodeInvalidError as exc:
            raise ValueError("Неверный код") from exc

        return await self._finish_auth(session_id, pending)

    async def start_qr(self, db: AsyncSession, session_id: int) -> dict:
        await self._cleanup_expired()
        session = await self._get_session(db, session_id)
        await self._discard(session_id)

        client = TelegramClient(
            self._session_path(session.session_name),
            session.api_id,
            session.api_hash,
        )
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            await client.disconnect()
            return {
                "status": "authorized",
                "phone": me.phone,
                "first_name": me.first_name,
                "username": me.username,
                "telegram_user_id": me.id,
            }

        qr = await client.qr_login()
        async with self._lock:
            self._pending_qr[session_id] = PendingQrAuth(client=client, qr_login=qr)

        logger.info("auth_qr_started", session_id=session_id)
        return {"status": "qr_pending", "qr_url": qr.url}

    async def verify_password(self, session_id: int, password: str) -> dict:
        pending = self._pending.get(session_id)
        qr = self._pending_qr.get(session_id)
        if qr:
            try:
                await qr.client.sign_in(password=password)
            except Exception as exc:
                raise ValueError("Неверный пароль двухфакторной аутентификации") from exc
            return await self._finish_qr_auth(session_id, qr)

        if not pending or not pending.needs_password:
            raise ValueError("Пароль не требуется на этом шаге")

        try:
            await pending.client.sign_in(password=password)
        except Exception as exc:
            raise ValueError("Неверный пароль двухфакторной аутентификации") from exc

        return await self._finish_auth(session_id, pending)

    async def wait_qr(self, session_id: int, timeout: float = 90.0) -> dict:
        qr = self._pending_qr.get(session_id)
        if not qr:
            raise ValueError("Сначала запустите QR-вход")

        try:
            await asyncio.wait_for(qr.qr_login.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            await qr.qr_login.recreate()
            return {"status": "qr_pending", "qr_url": qr.qr_login.url}
        except SessionPasswordNeededError:
            return {"status": "need_password"}

        return await self._finish_qr_auth(session_id, qr)

    async def _finish_qr_auth(self, session_id: int, pending: PendingQrAuth) -> dict:
        me = await pending.client.get_me()
        await pending.client.disconnect()
        self._pending_qr.pop(session_id, None)
        logger.info("auth_qr_success", session_id=session_id, user_id=me.id)
        return {
            "status": "authorized",
            "phone": me.phone,
            "first_name": me.first_name,
            "username": me.username,
            "telegram_user_id": me.id,
        }

    async def _finish_auth(self, session_id: int, pending: PendingAuth) -> dict:
        me = await pending.client.get_me()
        await pending.client.disconnect()
        self._pending.pop(session_id, None)
        logger.info("auth_success", session_id=session_id, user_id=me.id)
        return {
            "status": "authorized",
            "phone": me.phone,
            "first_name": me.first_name,
            "username": me.username,
            "telegram_user_id": me.id,
        }

    async def _get_session(self, db: AsyncSession, session_id: int) -> SessionPool:
        result = await db.execute(select(SessionPool).where(SessionPool.id == session_id))
        session = result.scalar_one_or_none()
        if not session:
            raise ValueError("Аккаунт не найден")
        return session


auth_service = SessionAuthService()
