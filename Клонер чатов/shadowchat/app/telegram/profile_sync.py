import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.photos import DeletePhotosRequest, UploadProfilePhotoRequest

from app.config import get_settings
from app.models import Employee, MirrorMode, SessionPool
from app.telegram.media_handler import MediaHandler
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()


class ProfileSyncService:
    def __init__(self, db: AsyncSession, session_pool: SessionPoolManager):
        self.db = db
        self.session_pool = session_pool
        self.settings = get_settings()
        self.media_handler = MediaHandler()
        self._paused_until: dict[int, datetime] = {}

    def is_enabled_for_mirror(self, mirror_mode: str) -> bool:
        return self.settings.profile_sync_enabled and mirror_mode == MirrorMode.PROFILE_SYNC.value

    def _is_paused(self, session_id: int) -> bool:
        until = self._paused_until.get(session_id)
        if until and until > datetime.now(timezone.utc):
            return True
        return False

    def _pause(self, session_id: int, seconds: int) -> None:
        self._paused_until[session_id] = datetime.now(timezone.utc) + timedelta(seconds=seconds)
        logger.warning("profile_sync_paused", session_id=session_id, seconds=seconds)

    async def sync_if_needed(
        self,
        employee: Employee,
        session: SessionPool,
        client: TelegramClient,
        mirror_mode: str,
        *,
        avatar_client: TelegramClient | None = None,
    ) -> None:
        if not self.is_enabled_for_mirror(mirror_mode):
            return
        if self._is_paused(session.id):
            return

        interval = timedelta(hours=self.settings.profile_sync_interval_hours)
        now = datetime.now(timezone.utc)
        last_sync = session.last_profile_sync_at
        if last_sync and last_sync.tzinfo is None:
            # SQLite may return naive datetimes even when column is timezone-aware.
            last_sync = last_sync.replace(tzinfo=timezone.utc)
            session.last_profile_sync_at = last_sync
            await self.db.flush()

        if last_sync and (now - last_sync) < interval:
            await self._sync_name_if_changed(employee, session, client)
            return

        try:
            await self._sync_name_if_changed(employee, session, client)
            await self._sync_avatar_if_needed(
                employee, session, client, avatar_client=avatar_client
            )
            session.last_profile_sync_at = now
            await self.db.flush()
            logger.info(
                "profile_synced",
                employee_id=employee.id,
                session_name=session.session_name,
            )
        except FloodWaitError as exc:
            self._pause(session.id, exc.seconds)
        except Exception as exc:
            logger.error(
                "profile_sync_failed",
                employee_id=employee.id,
                session_name=session.session_name,
                error=str(exc),
            )

    async def _sync_name_if_changed(
        self, employee: Employee, session: SessionPool, client: TelegramClient
    ) -> None:
        me = await client.get_me()
        current_first = me.first_name or ""
        current_last = me.last_name or ""
        target_first = employee.first_name or ""
        target_last = employee.last_name or ""

        if current_first == target_first and current_last == (target_last or ""):
            return

        await self.session_pool.with_flood_wait_retry(
            lambda: client(
                UpdateProfileRequest(
                    first_name=target_first[:64],
                    last_name=(target_last or "")[:64],
                )
            )
        )
        logger.info("profile_name_updated", session_name=session.session_name)

    async def _sync_avatar_if_needed(
        self,
        employee: Employee,
        session: SessionPool,
        client: TelegramClient,
        *,
        avatar_client: TelegramClient | None = None,
    ) -> None:
        avatar_path = self.media_handler.cache_dir / f"avatar_{employee.id}.jpg"
        try:
            source = avatar_client or client
            photos = await source.get_profile_photos(employee.telegram_user_id, limit=1)
            if not photos:
                return

            path = await source.download_media(
                photos[0],
                file=str(avatar_path),
            )
            if not path:
                return

            avatar_path = Path(path)
            with avatar_path.open("rb") as f:
                data = f.read()
            new_hash = self.media_handler.avatar_hash(data)

            if employee.avatar_hash == new_hash:
                return

            uploaded = await self.session_pool.with_flood_wait_retry(
                lambda: client.upload_file(path)
            )
            me = await client.get_me()
            if me.photo:
                await client(DeletePhotosRequest(id=[me.photo]))

            await self.session_pool.with_flood_wait_retry(
                lambda: client(UploadProfilePhotoRequest(file=uploaded))
            )
            employee.avatar_hash = new_hash
            await self.db.flush()
            logger.info("profile_avatar_updated", session_name=session.session_name)
        finally:
            self.media_handler.cleanup(avatar_path if avatar_path.exists() else None)


async def run_profile_sync_worker(db_factory, session_pool: SessionPoolManager) -> None:
    """Background worker for periodic profile sync across all bound sessions."""
    settings = get_settings()
    if not settings.profile_sync_enabled:
        return

    while True:
        try:
            async with db_factory() as db:
                result = await db.execute(
                    select(SessionPool).where(
                        SessionPool.is_active.is_(True),
                        SessionPool.assigned_employee_id.isnot(None),
                        SessionPool.binding_mode == "permanent",
                    )
                )
                sessions = result.scalars().all()
                sync_service = ProfileSyncService(db, session_pool)

                for session in sessions:
                    emp_result = await db.execute(
                        select(Employee).where(Employee.id == session.assigned_employee_id)
                    )
                    employee = emp_result.scalar_one_or_none()
                    if not employee:
                        continue
                    try:
                        client = await session_pool.get_client_for_session(session)
                        await sync_service.sync_if_needed(
                            employee, session, client, MirrorMode.PROFILE_SYNC.value
                        )
                    except Exception as exc:
                        logger.error(
                            "periodic_profile_sync_failed",
                            session_name=session.session_name,
                            error=str(exc),
                        )
                await db.commit()
        except Exception as exc:
            logger.error("profile_sync_worker_error", error=str(exc))

        await asyncio.sleep(settings.profile_sync_interval_hours * 3600)
