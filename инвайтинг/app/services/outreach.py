from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon.errors import (
    AuthKeyDuplicatedError,
    FloodWaitError,
    PeerFloodError,
    UserIdInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    UserPrivacyRestrictedError,
)

from app.models import Account, InviteLog, InviteTarget
from app.schemas import RuntimeSettings
from app.services.connector_sync import sync_outreach_to_inbox
from app.services.settings_store import get_runtime_settings
from app.telegram.entities import normalize_username, resolve_target_user
from app.telegram.session_pool import LocalSessionPool

logger = structlog.get_logger()


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _target_label(t: InviteTarget) -> str:
    if t.username:
        return f"@{t.username}"
    return str(t.user_id or "unknown")


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(day, datetime.max.time(), tzinfo=timezone.utc)
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


@dataclass
class OutreachRuntimeState:
    running: bool = False
    last_tick_at: datetime | None = None
    account_idx: int = 0
    day: date = _today_utc()
    sent_today: int = 0


class OutreachService:
    """Холодная отписка только что заинвайченным — отдельный пул аккаунтов."""

    def __init__(self, db_factory: async_sessionmaker[AsyncSession]):
        self._db_factory = db_factory
        self._pool = LocalSessionPool()
        self._pool.bind_db(db_factory)
        self._task: asyncio.Task | None = None
        self._stop_evt = asyncio.Event()
        self.state = OutreachRuntimeState()
        self._lock = asyncio.Lock()
        self._dead_sessions: set[str] = set()
        # peer_flood / спам-блок на сегодня — пробуем другой outreach-аккаунт
        self._flood_blocked: set[str] = set()

    async def start(self) -> None:
        async with self._lock:
            if self._task and not self._task.done():
                return
            self._stop_evt.clear()
            self.state.running = True
            self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        async with self._lock:
            self.state.running = False
            self._stop_evt.set()
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None
        await self._pool.disconnect_all()

    async def _count_sent_today(self, db: AsyncSession) -> int:
        start, end = _day_bounds(self.state.day)
        res = await db.execute(
            select(func.count(InviteLog.id)).where(
                InviteLog.status == "outreach_ok",
                InviteLog.created_at >= start,
                InviteLog.created_at <= end,
            )
        )
        return int(res.scalar() or 0)

    async def _count_sent_today_for_account(self, db: AsyncSession, account_name: str) -> int:
        start, end = _day_bounds(self.state.day)
        res = await db.execute(
            select(func.count(InviteLog.id)).where(
                InviteLog.status == "outreach_ok",
                InviteLog.inviter_session == account_name,
                InviteLog.created_at >= start,
                InviteLog.created_at <= end,
            )
        )
        return int(res.scalar() or 0)

    async def _get_next_target(self, db: AsyncSession) -> InviteTarget | None:
        res = await db.execute(
            select(InviteTarget)
            .where(
                InviteTarget.is_invited.is_(True),
                InviteTarget.is_messaged.is_(False),
                InviteTarget.is_skipped.is_(False),
            )
            .order_by(InviteTarget.invited_at.asc(), InviteTarget.id.asc())
            .limit(1)
        )
        return res.scalar_one_or_none()

    async def _authorized_names(self, db: AsyncSession, names: list[str]) -> list[str]:
        if not names:
            return []
        res = await db.execute(
            select(Account.name).where(
                Account.name.in_(names),
                Account.role == "outreach",
                Account.is_authorized.is_(True),
                Account.is_active.is_(True),
                Account.session_string.is_not(None),
            )
        )
        ok = {r[0] for r in res.all()}
        return [n for n in names if n in ok and n not in self._dead_sessions]

    async def _pick_outreach_account(
        self,
        db: AsyncSession,
        configured: list[str],
        per_account_limit: int,
    ) -> str | None:
        live = await self._authorized_names(db, configured)
        if not live:
            return None

        for _ in range(len(live)):
            name = live[self.state.account_idx % len(live)]
            self.state.account_idx = (self.state.account_idx + 1) % len(live)
            if name in self._flood_blocked:
                continue
            if per_account_limit > 0:
                sent = await self._count_sent_today_for_account(db, name)
                if sent >= per_account_limit:
                    continue
            return name
        return None

    async def _run_loop(self) -> None:
        while not self._stop_evt.is_set():
            try:
                async with self._db_factory() as db:
                    settings = await get_runtime_settings(db)
                    await self._tick(db, settings)
                    await db.commit()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("outreach_loop_error", error=str(exc))
            await asyncio.sleep(1)

    async def _tick(self, db: AsyncSession, settings: RuntimeSettings) -> None:
        self.state.last_tick_at = datetime.utcnow()

        today = _today_utc()
        if today != self.state.day:
            self.state.day = today
            self.state.sent_today = 0
            self._flood_blocked.clear()

        self.state.sent_today = await self._count_sent_today(db)

        if not settings.outreach_enabled:
            return
        msg = (settings.outreach_message or "").strip()
        if not msg:
            return

        per_account_limit = settings.outreach_daily_limit
        configured = [s.strip() for s in settings.outreach_sessions if s.strip()]
        if not configured:
            return

        target = await self._get_next_target(db)
        if not target:
            return

        if not normalize_username(target.username):
            target.is_skipped = True
            target.outreach_error = "skipped_no_username: нужен username"
            return

        live_count = len(await self._authorized_names(db, configured))
        max_attempts = max(1, live_count)
        sent = False
        last_err: str | None = None

        for _ in range(max_attempts):
            account = await self._pick_outreach_account(db, configured, per_account_limit)
            if not account:
                last_err = last_err or "no_outreach_capacity: все outreach-аккаунты в лимите или в спам-блоке"
                break
            ok = await self._message_one(db, account, target, msg)
            if ok:
                sent = True
                break
            last_err = target.outreach_error

        if not sent and last_err:
            target.outreach_error = last_err

        await asyncio.sleep(settings.outreach_delay_seconds)

    async def _message_one(
        self,
        db: AsyncSession,
        account_name: str,
        target: InviteTarget,
        message: str,
    ) -> bool:
        label = _target_label(target)
        log_row = InviteLog(
            inviter_session=account_name,
            target_label=label,
            status="outreach_err",
            error_text=None,
        )
        db.add(log_row)

        try:
            client = await self._pool.get_client(account_name)
            entity = await resolve_target_user(client, target)
            peer_id = int(getattr(entity, "id", 0) or 0)
            if not peer_id:
                raise ValueError(f"cannot resolve telegram user id for {label}")

            sent = await LocalSessionPool.with_flood_wait_retry(
                lambda: client.send_message(entity, message),
                max_retries=2,
            )

            username = getattr(entity, "username", None) or normalize_username(target.username)
            first_name = getattr(entity, "first_name", None)
            sent_at = datetime.utcnow().isoformat() + "Z"

            target.is_messaged = True
            target.messaged_at = datetime.utcnow()
            target.outreach_error = None
            target.user_id = peer_id
            log_row.status = "outreach_ok"
            log_row.error_text = None
            self.state.sent_today += 1

            await sync_outreach_to_inbox(
                session_name=account_name,
                peer_telegram_user_id=peer_id,
                username=username,
                first_name=first_name,
                body=message,
                telegram_message_id=getattr(sent, "id", f"outreach-{peer_id}-{int(datetime.utcnow().timestamp())}"),
                sent_at=sent_at,
            )
            return True
        except AuthKeyDuplicatedError:
            self._dead_sessions.add(account_name)
            await self._pool.drop_client(account_name)
            err = f"session_dead({account_name}): auth key duplicated — войдите заново по коду"
            target.outreach_error = err
            log_row.error_text = err
            acc = (
                await db.execute(select(Account).where(Account.name == account_name))
            ).scalar_one_or_none()
            if acc:
                acc.is_authorized = False
                acc.last_error = err
                acc.session_string = None
            logger.error("outreach_session_dead", session=account_name)
            return False
        except (UsernameNotOccupiedError, UsernameInvalidError, UserIdInvalidError) as exc:
            err = f"invalid_user: {exc.__class__.__name__}"
            target.outreach_error = err
            target.is_messaged = True
            target.messaged_at = datetime.utcnow()
            log_row.status = "skipped"
            log_row.error_text = err
            return False
        except ValueError as exc:
            msg = str(exc)
            if "as username" in msg.lower() or "cannot find any entity" in msg.lower() or "no_username" in msg.lower():
                err = f"skipped_invalid_user: {msg}"
                target.outreach_error = err
                target.is_messaged = True
                target.messaged_at = datetime.utcnow()
                log_row.status = "skipped"
                log_row.error_text = err
            else:
                target.outreach_error = msg
                log_row.error_text = msg
            return False
        except UserPrivacyRestrictedError:
            err = "privacy_restricted"
            target.outreach_error = err
            target.is_messaged = True
            target.messaged_at = datetime.utcnow()
            log_row.error_text = err
            return False
        except PeerFloodError as exc:
            err = f"peer_flood: {exc}"
            target.outreach_error = err
            log_row.error_text = err
            self._flood_blocked.add(account_name)
            acc = (
                await db.execute(select(Account).where(Account.name == account_name))
            ).scalar_one_or_none()
            if acc:
                acc.last_error = f"peer_flood: переключаемся на другой outreach-аккаунт"
            logger.warning("outreach_peer_flood", session=account_name, target=label)
            return False
        except FloodWaitError as exc:
            err = f"flood_wait: {exc.seconds}s"
            target.outreach_error = err
            log_row.error_text = err
            self._flood_blocked.add(account_name)
            return False
        except Exception as exc:
            msg = str(exc)
            if "authorization key" in msg.lower() and "two different ip" in msg.lower():
                self._dead_sessions.add(account_name)
                await self._pool.drop_client(account_name)
                err = f"session_dead({account_name}): войдите заново по коду"
                acc = (
                    await db.execute(select(Account).where(Account.name == account_name))
                ).scalar_one_or_none()
                if acc:
                    acc.is_authorized = False
                    acc.last_error = err
                    acc.session_string = None
            elif "peer_flood" in msg.lower() or "too many requests" in msg.lower():
                self._flood_blocked.add(account_name)
                err = f"peer_flood: {msg}"
                log_row.error_text = err
                target.outreach_error = err
                logger.warning("outreach_peer_flood", session=account_name, target=label)
                return False
            elif "as username" in msg.lower() or "cannot find any entity" in msg.lower():
                err = f"skipped_invalid_user: {msg}"
                target.is_messaged = True
                target.messaged_at = datetime.utcnow()
                log_row.status = "skipped"
            else:
                err = msg
            target.outreach_error = err
            log_row.error_text = err
            return False
