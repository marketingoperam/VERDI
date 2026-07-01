import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from telethon.tl.types import MessageService, User

from app.config import get_settings
from app.db import async_session_factory
from app.models import MirrorChat, SourceChat, SyncLog
from app.services.delete_handler import DeleteHandler
from app.services.edit_handler import EditHandler
from app.services.employee_binding import EmployeeBindingService
from app.services.message_mapper import MessageMapper
from app.telegram.mirror_sender import MirrorSender
from app.telegram.profile_sync import ProfileSyncService
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()


class MessageDispatcher:
    def __init__(
        self,
        db: AsyncSession,
        session_pool: SessionPoolManager,
        mirror_sender: MirrorSender,
    ):
        self.db = db
        self.session_pool = session_pool
        self.mirror_sender = mirror_sender
        self.binding = EmployeeBindingService(db)
        self.mapper = MessageMapper(db)
        self.profile_sync = ProfileSyncService(db, session_pool)
        self.edit_handler = EditHandler(db, session_pool, mirror_sender)
        self.delete_handler = DeleteHandler(db, session_pool)
        self.settings = get_settings()

    async def _log_event(
        self,
        event_type: str,
        status: str,
        source_chat_id: int | None = None,
        source_message_id: int | None = None,
        mirror_message_id: int | None = None,
        error_text: str | None = None,
    ) -> None:
        log = SyncLog(
            event_type=event_type,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            mirror_message_id=mirror_message_id,
            status=status,
            error_text=error_text,
        )
        self.db.add(log)
        await self.db.flush()

    async def _resolve_chats(
        self, telegram_chat_id: int
    ) -> tuple[SourceChat | None, MirrorChat | None]:
        result = await self.db.execute(
            select(SourceChat).where(
                SourceChat.telegram_chat_id == telegram_chat_id,
                SourceChat.is_active.is_(True),
            )
        )
        source_chat = result.scalar_one_or_none()
        if not source_chat or not source_chat.mirror_chat_id:
            return source_chat, None

        mirror_result = await self.db.execute(
            select(MirrorChat).where(
                MirrorChat.id == source_chat.mirror_chat_id,
                MirrorChat.is_active.is_(True),
            )
        )
        mirror_chat = mirror_result.scalar_one_or_none()
        return source_chat, mirror_chat

    def _should_filter(self, message, sender) -> str | None:
        if self.settings.ignore_service_messages and isinstance(message, MessageService):
            return "service_message"

        if self.settings.ignore_bots and isinstance(sender, User) and sender.bot:
            return "bot_message"

        text = message.message or message.text or ""
        if self.settings.message_filter_mode == "text_only" and not text and not message.media:
            return "no_text"

        if self.settings.message_filter_mode == "min_length":
            if len(text) < self.settings.min_message_length and not message.media:
                return "too_short"

        return None

    async def handle_new_message(self, message, chat_id: int) -> None:
        source_chat, mirror_chat = await self._resolve_chats(chat_id)
        if not source_chat or not mirror_chat:
            return

        if await self.mapper.exists(source_chat.id, message.id):
            logger.debug("duplicate_message_skipped", message_id=message.id)
            return

        sender = await message.get_sender()
        if not sender or not hasattr(sender, "id"):
            return

        filter_reason = self._should_filter(message, sender)
        if filter_reason:
            logger.debug("message_filtered", reason=filter_reason, message_id=message.id)
            return

        listener_client = await self.session_pool.get_listener_client()
        first_name, last_name, username = await self.mirror_sender.fetch_sender_info(
            listener_client, sender.id
        )
        employee = await self.binding.get_or_create_employee(
            sender.id, first_name, last_name, username
        )

        if employee.is_muted or not employee.is_active:
            return

        session, used_fallback = await self.binding.resolve_session(employee, mirror_chat.mode)
        if not session:
            await self._log_event(
                "new_message",
                "error",
                source_chat_id=source_chat.id,
                source_message_id=message.id,
                error_text="No session available for employee",
            )
            return

        try:
            client = await self.session_pool.get_client_for_session(session)
            await self.profile_sync.sync_if_needed(employee, session, client, mirror_chat.mode)

            reply_to_mirror_id = None
            if message.reply_to and message.reply_to.reply_to_msg_id:
                reply_to_mirror_id = await self.mapper.get_mirror_message_id(
                    source_chat.id, message.reply_to.reply_to_msg_id
                )

            mirror_msg_id = await self.mirror_sender.send_mirror_message(
                self.db,
                client,
                message,
                employee,
                source_chat,
                mirror_chat,
                session,
                reply_to_mirror_id=reply_to_mirror_id,
                used_fallback=used_fallback,
            )

            await self._log_event(
                "new_message",
                "success" if mirror_msg_id else "skipped",
                source_chat_id=source_chat.id,
                source_message_id=message.id,
                mirror_message_id=mirror_msg_id,
            )
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            logger.error(
                "mirror_failed",
                message_id=message.id,
                error=str(exc).encode("ascii", "backslashreplace").decode(),
            )
            async with async_session_factory() as err_db:
                dispatcher = MessageDispatcher(err_db, self.session_pool, self.mirror_sender)
                await dispatcher._log_event(
                    "new_message",
                    "error",
                    source_chat_id=source_chat.id,
                    source_message_id=message.id,
                    error_text=str(exc),
                )
                await err_db.commit()

    async def handle_edit(self, message, chat_id: int) -> None:
        source_chat, mirror_chat = await self._resolve_chats(chat_id)
        if not source_chat or not mirror_chat:
            return

        try:
            success = await self.edit_handler.handle_edit(
                source_chat.id,
                message.id,
                message.message or message.text or "",
                mirror_chat,
            )
            await self._log_event(
                "edit",
                "success" if success else "partial",
                source_chat_id=source_chat.id,
                source_message_id=message.id,
            )
            await self.db.commit()
        except Exception as exc:
            await self.db.rollback()
            logger.error("edit_handler_failed", error=str(exc))
            async with self.db.begin():
                await self._log_event(
                    "edit",
                    "error",
                    source_chat_id=source_chat.id,
                    source_message_id=message.id,
                    error_text=str(exc),
                )

    async def handle_delete(self, chat_id: int, message_ids: list[int]) -> None:
        source_chat, mirror_chat = await self._resolve_chats(chat_id)
        if not source_chat or not mirror_chat:
            return

        for msg_id in message_ids:
            try:
                success = await self.delete_handler.handle_delete(
                    source_chat.id, msg_id, mirror_chat
                )
                await self._log_event(
                    "delete",
                    "success" if success else "not_found",
                    source_chat_id=source_chat.id,
                    source_message_id=msg_id,
                )
            except Exception as exc:
                logger.error("delete_handler_failed", message_id=msg_id, error=str(exc))
                await self._log_event(
                    "delete",
                    "error",
                    source_chat_id=source_chat.id,
                    source_message_id=msg_id,
                    error_text=str(exc),
                )
        await self.db.commit()
