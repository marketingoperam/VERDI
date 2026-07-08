"""Вход по телефону + коду Telegram. Сессия хранится как StringSession в БД."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)
from telethon.sessions import StringSession

from app.config import get_settings
from app.models import Account
from app.telegram.proxy import parse_proxy

logger = structlog.get_logger()


@dataclass
class PendingAuth:
    client: TelegramClient
    phone: str
    phone_code_hash: str
    account_id: int
    needs_password: bool = False
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


class PhoneCodeAuthService:
    _pending: dict[int, PendingAuth] = {}
    _lock = asyncio.Lock()
    _TTL = timedelta(minutes=30)

    async def _cleanup(self) -> None:
        now = datetime.now(timezone.utc)
        for aid, p in list(self._pending.items()):
            if p.created_at and now - p.created_at > self._TTL:
                await self._discard(aid)

    async def _discard(self, account_id: int) -> None:
        pending = self._pending.pop(account_id, None)
        if pending:
            try:
                await pending.client.disconnect()
            except Exception:
                pass

    async def send_code(self, db: AsyncSession, account_id: int, phone: str) -> dict:
        await self._cleanup()
        account = await db.get(Account, account_id)
        if not account:
            raise ValueError("Аккаунт не найден")

        settings = get_settings()
        if not settings.tg_api_id or not settings.tg_api_hash:
            raise ValueError("Нет INV_TG_API_ID / INV_TG_API_HASH в .env")

        await self._discard(account_id)

        phone = phone.strip().replace(" ", "")
        if not phone.startswith("+"):
            phone = "+" + phone

        proxy = None
        if settings.tg_proxy.strip():
            proxy = parse_proxy(settings.tg_proxy.strip(), settings.tg_proxy_type)

        # Always use in-memory StringSession for login — no .session files.
        client = TelegramClient(
            StringSession(account.session_string or ""),
            settings.tg_api_id,
            settings.tg_api_hash,
            proxy=proxy,
        )
        await client.connect()

        if await client.is_user_authorized():
            me = await client.get_me()
            account.session_string = client.session.save()
            account.phone = me.phone
            account.username = me.username
            account.telegram_user_id = int(me.id) if me.id else None
            account.is_authorized = True
            account.last_error = None
            account.updated_at = datetime.utcnow()
            await client.disconnect()
            return {
                "status": "authorized",
                "phone": me.phone,
                "username": me.username,
                "first_name": me.first_name,
            }

        try:
            sent = await client.send_code_request(phone)
        except PhoneNumberInvalidError as exc:
            await client.disconnect()
            raise ValueError("Неверный номер телефона") from exc

        async with self._lock:
            self._pending[account_id] = PendingAuth(
                client=client,
                phone=phone,
                phone_code_hash=sent.phone_code_hash,
                account_id=account_id,
            )

        account.phone = phone
        account.updated_at = datetime.utcnow()
        logger.info("auth_code_sent", account=account.name, phone=phone[-4:])
        return {"status": "code_sent", "phone": phone}

    async def verify_code(self, db: AsyncSession, account_id: int, code: str) -> dict:
        pending = self._pending.get(account_id)
        if not pending:
            raise ValueError("Сначала отправьте код")

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

        return await self._finish(db, account_id, pending)

    async def verify_password(self, db: AsyncSession, account_id: int, password: str) -> dict:
        pending = self._pending.get(account_id)
        if not pending or not pending.needs_password:
            raise ValueError("Пароль 2FA сейчас не требуется")
        try:
            await pending.client.sign_in(password=password)
        except Exception as exc:
            raise ValueError("Неверный пароль 2FA") from exc
        return await self._finish(db, account_id, pending)

    async def _finish(self, db: AsyncSession, account_id: int, pending: PendingAuth) -> dict:
        account = await db.get(Account, account_id)
        if not account:
            await self._discard(account_id)
            raise ValueError("Аккаунт не найден")

        me = await pending.client.get_me()
        account.session_string = pending.client.session.save()
        account.phone = me.phone or pending.phone
        account.username = me.username
        account.telegram_user_id = int(me.id) if me.id else None
        account.is_authorized = True
        account.last_error = None
        account.updated_at = datetime.utcnow()

        await pending.client.disconnect()
        self._pending.pop(account_id, None)
        logger.info("auth_ok", account=account.name, user_id=me.id)
        return {
            "status": "authorized",
            "phone": account.phone,
            "username": account.username,
            "first_name": me.first_name,
            "telegram_user_id": account.telegram_user_id,
        }


auth_service = PhoneCodeAuthService()
