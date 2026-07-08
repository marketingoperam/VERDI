from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from telethon.errors import (
    AuthKeyDuplicatedError,
    ChatAdminRequiredError,
    ChatWriteForbiddenError,
    FloodWaitError,
    PeerFloodError,
    UserAlreadyParticipantError,
    UserIdInvalidError,
    UserNotMutualContactError,
    UserPrivacyRestrictedError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.functions.channels import InviteToChannelRequest, JoinChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest, ImportChatInviteRequest
from telethon.tl.types import Channel, Chat

from app.models import Account, InviteLog, InviteTarget
from app.schemas import RuntimeSettings
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


def _invite_hash_from_link(link: str) -> str | None:
    s = link.strip()
    s = s.replace("https://", "").replace("http://", "")
    if s.startswith("t.me/+"):
        return s.split("t.me/+")[1].split("?")[0].split("/")[0]
    if "joinchat/" in s:
        return s.split("joinchat/")[1].split("?")[0].split("/")[0]
    return None


async def _ensure_joined(client, chat_link: str) -> Any:
    inv_hash = _invite_hash_from_link(chat_link)
    if inv_hash:
        return await client(ImportChatInviteRequest(inv_hash))
    # public link: t.me/username or @username
    s = chat_link.strip()
    if "t.me/" in s:
        username = s.split("t.me/")[1].split("?")[0].split("/")[0]
        return await client(JoinChannelRequest(username))
    if s.startswith("@"):
        return await client(JoinChannelRequest(s[1:]))
    return await client(JoinChannelRequest(s))


def _is_invite_flood_message(msg: str) -> bool:
    m = msg.lower()
    return (
        "too many requests" in m
        or "peer_flood" in m
        or "flood_wait" in m
        or "flood wait" in m
    )


@dataclass
class InviteRuntimeState:
    running: bool = False
    last_tick_at: datetime | None = None
    inviter_idx: int = 0
    day: date = _today_utc()
    invited_today: int = 0


class InviteService:
    def __init__(self, db_factory: async_sessionmaker[AsyncSession]):
        self._db_factory = db_factory
        self._pool = LocalSessionPool()
        self._pool.bind_db(db_factory)
        self._task: asyncio.Task | None = None
        self._stop_evt = asyncio.Event()
        self.state = InviteRuntimeState()
        self._lock = asyncio.Lock()
        self._dead_sessions: set[str] = set()
        self._flood_blocked: set[str] = set()

    async def _authorized_inviters(self, db: AsyncSession, names: list[str]) -> list[str]:
        if not names:
            return []
        res = await db.execute(
            select(Account.name).where(
                Account.name.in_(names),
                Account.role == "inviter",
                Account.is_authorized.is_(True),
                Account.is_active.is_(True),
                Account.session_string.is_not(None),
            )
        )
        ok = {r[0] for r in res.all()}
        return [n for n in names if n in ok and n not in self._dead_sessions]

    async def _pick_inviter(self, db: AsyncSession, names: list[str]) -> str | None:
        live = await self._authorized_inviters(db, names)
        if not live:
            return None
        for _ in range(len(live)):
            name = live[self.state.inviter_idx % len(live)]
            self.state.inviter_idx = (self.state.inviter_idx + 1) % len(live)
            if name in self._flood_blocked:
                continue
            return name
        return None

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

    async def _count_invited_today(self, db: AsyncSession) -> int:
        start = datetime.combine(self.state.day, datetime.min.time(), tzinfo=timezone.utc)
        end = datetime.combine(self.state.day, datetime.max.time(), tzinfo=timezone.utc)
        res = await db.execute(
            select(func.count(InviteLog.id)).where(
                InviteLog.status == "success",
                InviteLog.created_at >= start.replace(tzinfo=None),
                InviteLog.created_at <= end.replace(tzinfo=None),
            )
        )
        return int(res.scalar() or 0)

    async def _get_next_target(self, db: AsyncSession) -> InviteTarget | None:
        res = await db.execute(
            select(InviteTarget)
            .where(
                InviteTarget.is_invited.is_(False),
                InviteTarget.is_skipped.is_(False),
            )
            .order_by(InviteTarget.created_at.asc(), InviteTarget.id.asc())
            .limit(1)
        )
        return res.scalar_one_or_none()

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
                logger.warning("invite_loop_error", error=str(exc))
            await asyncio.sleep(1)

    async def _tick(self, db: AsyncSession, settings: RuntimeSettings) -> None:
        self.state.last_tick_at = datetime.utcnow()

        # daily reset
        today = _today_utc()
        if today != self.state.day:
            self.state.day = today
            self.state.invited_today = 0
            self._flood_blocked.clear()

        self.state.invited_today = await self._count_invited_today(db)

        inviter_sessions = [s.strip() for s in settings.inviter_sessions if s.strip()]
        live_sessions = await self._authorized_inviters(db, inviter_sessions)
        if not inviter_sessions:
            return
        if not live_sessions:
            logger.warning("all_inviter_sessions_dead_or_unauthorized")
            return
        if not settings.chat_link.strip():
            return
        if settings.daily_limit <= 0:
            return
        if self.state.invited_today >= settings.daily_limit:
            return

        target = await self._get_next_target(db)
        if not target:
            return

        if not normalize_username(target.username):
            target.is_skipped = True
            target.last_error = "skipped_no_username: в базе нужен username"
            return

        live_count = len(await self._authorized_inviters(db, inviter_sessions))
        invited = False
        for _ in range(max(1, live_count)):
            sess = await self._pick_inviter(db, inviter_sessions)
            if not sess:
                if not target.last_error:
                    target.last_error = "no_inviter_capacity: все инвайтеры в спам-блоке или недоступны"
                break
            done = await self._invite_one(db, settings, sess, target)
            if done or target.is_invited or target.is_skipped:
                invited = target.is_invited
                break

        if invited:
            await asyncio.sleep(settings.min_delay_seconds)

    async def _invite_one(
        self,
        db: AsyncSession,
        settings: RuntimeSettings,
        inviter_session: str,
        target: InviteTarget,
    ) -> bool:
        target.attempts += 1
        label = _target_label(target)
        log_row = InviteLog(
            inviter_session=inviter_session,
            target_label=label,
            status="error",
            error_text=None,
        )
        db.add(log_row)

        try:
            client = await self._pool.get_client(inviter_session)
            # ensure inviter is in chat by link
            try:
                await LocalSessionPool.with_flood_wait_retry(
                    lambda: _ensure_joined(client, settings.chat_link),
                    max_retries=2,
                )
            except UserAlreadyParticipantError:
                pass
            except Exception:
                # join can fail for public channel if already in; ignore unknown join errors only if invite later works
                pass

            # resolve chat entity for inviting (public link best-effort)
            chat_entity: Any
            inv_hash = _invite_hash_from_link(settings.chat_link)
            if inv_hash:
                # after import/join, get_dialogs can find it by last join; we fallback to get_entity on link
                chat_entity = await client.get_entity(settings.chat_link)
            else:
                chat_entity = await client.get_entity(settings.chat_link)

            user_entity: Any
            username = normalize_username(target.username)
            if not username:
                target.is_skipped = True
                target.last_error = "skipped_no_username: в базе нужен username"
                log_row.status = "skipped"
                log_row.error_text = target.last_error
                return True

            user_entity = await resolve_target_user(client, target)
            if getattr(user_entity, "id", None):
                target.user_id = int(user_entity.id)

            async def _do_invite():
                if isinstance(chat_entity, Channel):
                    return await client(InviteToChannelRequest(chat_entity, [user_entity]))
                if isinstance(chat_entity, Chat):
                    return await client(
                        AddChatUserRequest(
                            chat_id=chat_entity.id,
                            user_id=user_entity,
                            fwd_limit=50,
                        )
                    )
                # fallback: megagroup/channel-style invite
                return await client(InviteToChannelRequest(chat_entity, [user_entity]))

            await _do_invite()

            target.is_invited = True
            target.invited_at = datetime.utcnow()
            target.last_error = None

            log_row.status = "success"
            log_row.error_text = None
            return True
        except AuthKeyDuplicatedError:
            self._dead_sessions.add(inviter_session)
            try:
                await self._pool.drop_client(inviter_session)
            except Exception:
                pass
            target.last_error = (
                f"session_dead({inviter_session}): auth key used from 2 places. "
                "Войдите заново по телефону+коду во вкладке «Аккаунты»."
            )
            log_row.error_text = target.last_error
            # mark account unauthorized in DB
            acc = (
                await db.execute(select(Account).where(Account.name == inviter_session))
            ).scalar_one_or_none()
            if acc:
                acc.is_authorized = False
                acc.last_error = target.last_error
                acc.session_string = None
            logger.error("inviter_session_dead", session=inviter_session)
            return False
        except (UsernameNotOccupiedError, UsernameInvalidError, UserIdInvalidError) as exc:
            target.is_skipped = True
            target.last_error = f"skipped_invalid_user: {exc.__class__.__name__}"
            log_row.status = "skipped"
            log_row.error_text = target.last_error
            return True
        except (UserNotMutualContactError, UserPrivacyRestrictedError) as exc:
            target.is_skipped = True
            target.last_error = (
                f"skipped_privacy: {exc.__class__.__name__} — пользователь не в контактах "
                "или запретил приглашения"
            )
            log_row.status = "skipped"
            log_row.error_text = target.last_error
            return True
        except ValueError as exc:
            msg = str(exc)
            if "as username" in msg.lower() or "cannot find any entity" in msg.lower():
                target.is_skipped = True
                target.last_error = f"skipped_invalid_user: {msg}"
                log_row.status = "skipped"
                log_row.error_text = target.last_error
                return True
            target.last_error = msg
            log_row.error_text = target.last_error
            return False
        except (ChatAdminRequiredError, ChatWriteForbiddenError):
            target.last_error = (
                "no_invite_rights: инвайтер не может добавлять людей в этот чат. "
                "Сделайте аккаунты-инвайтеры админами с правом «Invite users»"
            )
            log_row.error_text = target.last_error
            return False
        except FloodWaitError as exc:
            err = f"flood_wait: {exc.seconds}s"
            target.last_error = err
            log_row.error_text = err
            self._flood_blocked.add(inviter_session)
            logger.warning("inviter_flood", session=inviter_session, target=label, kind="flood_wait")
            return False
        except PeerFloodError as exc:
            err = f"peer_flood: {exc}"
            target.last_error = err
            log_row.error_text = err
            self._flood_blocked.add(inviter_session)
            logger.warning("inviter_flood", session=inviter_session, target=label, kind="peer_flood")
            return False
        except Exception as exc:
            msg = str(exc)
            if "authorization key" in msg.lower() and "two different ip" in msg.lower():
                self._dead_sessions.add(inviter_session)
                try:
                    await self._pool.drop_client(inviter_session)
                except Exception:
                    pass
                target.last_error = (
                    f"session_dead({inviter_session}): auth key used from 2 places. "
                    "Войдите заново по телефону+коду во вкладке «Аккаунты»."
                )
                acc = (
                    await db.execute(select(Account).where(Account.name == inviter_session))
                ).scalar_one_or_none()
                if acc:
                    acc.is_authorized = False
                    acc.last_error = target.last_error
                    acc.session_string = None
            elif _is_invite_flood_message(msg):
                err = f"invite_flood: {msg}"
                target.last_error = err
                log_row.error_text = err
                self._flood_blocked.add(inviter_session)
                acc = (
                    await db.execute(select(Account).where(Account.name == inviter_session))
                ).scalar_one_or_none()
                if acc:
                    acc.last_error = "invite_flood: переключаемся на другой инвайтер"
                logger.warning("inviter_flood", session=inviter_session, target=label, kind="too_many_requests")
                return False
            elif "mutual contact" in msg.lower():
                target.is_skipped = True
                target.last_error = (
                    "skipped_privacy: пользователь не взаимный контакт — "
                    "нельзя пригласить в канал без контакта"
                )
                log_row.status = "skipped"
                log_row.error_text = target.last_error
                return True
            elif "as username" in msg.lower() or "cannot find any entity" in msg.lower():
                target.is_skipped = True
                target.last_error = f"skipped_invalid_user: {msg}"
                log_row.status = "skipped"
                log_row.error_text = target.last_error
                return True
            elif "can't write in this chat" in msg.lower() or "chat_write_forbidden" in msg.lower():
                target.last_error = (
                    "no_invite_rights: инвайтер не может добавлять людей в этот чат. "
                    "Дайте право Invite users всем inviter_* в целевом чате"
                )
                log_row.error_text = target.last_error
                return False
            else:
                target.last_error = msg
            log_row.error_text = target.last_error
            return False
