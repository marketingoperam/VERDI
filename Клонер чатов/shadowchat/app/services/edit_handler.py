import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import MessageIdInvalidError, MessageNotModifiedError

from app.config import get_settings
from app.models import MirrorChat, MirrorMode
from app.services.message_mapper import MessageMapper
from app.telegram.mirror_sender import MirrorSender
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()


class EditHandler:
    def __init__(
        self,
        db: AsyncSession,
        session_pool: SessionPoolManager,
        mirror_sender: MirrorSender,
    ):
        self.db = db
        self.session_pool = session_pool
        self.mapper = MessageMapper(db)
        self.mirror_sender = mirror_sender
        self.settings = get_settings()

    async def handle_edit(
        self,
        source_chat_db_id: int,
        source_message_id: int,
        new_text: str,
        mirror_chat: MirrorChat,
    ) -> bool:
        mapping = await self.mapper.get_mapping(source_chat_db_id, source_message_id)
        if not mapping:
            logger.warning(
                "edit_mapping_not_found",
                source_chat_db_id=source_chat_db_id,
                source_message_id=source_message_id,
            )
            return False

        client: TelegramClient | None = None
        if mapping.session_pool_id:
            client = await self.session_pool.get_client_by_id(mapping.session_pool_id)

        if not client:
            client = await self.session_pool.get_listener_client()

        mirror_entity = await client.get_entity(mirror_chat.telegram_chat_id)

        edit_text = new_text

        try:
            await client.edit_message(
                mirror_entity,
                mapping.mirror_message_id,
                edit_text,
            )
            logger.info(
                "message_edited",
                source_message_id=source_message_id,
                mirror_message_id=mapping.mirror_message_id,
            )
            return True
        except MessageNotModifiedError:
            return True
        except (MessageIdInvalidError, Exception) as exc:
            logger.warning(
                "edit_failed_sending_notice",
                error=str(exc),
                source_message_id=source_message_id,
            )
            await client.send_message(
                mirror_entity,
                f"⚠️ Сообщение было изменено.\n\n{edit_text}",
                reply_to=mapping.mirror_message_id,
            )
            return False
