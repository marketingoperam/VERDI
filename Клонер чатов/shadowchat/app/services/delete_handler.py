import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import MessageIdInvalidError

from app.models import MirrorChat
from app.services.message_mapper import MessageMapper
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()


class DeleteHandler:
    def __init__(self, db: AsyncSession, session_pool: SessionPoolManager):
        self.db = db
        self.session_pool = session_pool
        self.mapper = MessageMapper(db)

    async def _get_client_for_mapping(self, session_pool_id: int | None) -> TelegramClient:
        if session_pool_id:
            client = await self.session_pool.get_client_by_id(session_pool_id)
            if client:
                return client
        return await self.session_pool.get_listener_client()

    async def handle_delete(
        self,
        source_chat_db_id: int,
        source_message_id: int,
        mirror_chat: MirrorChat,
    ) -> bool:
        mapping = await self.mapper.get_mapping(source_chat_db_id, source_message_id)
        if not mapping:
            logger.warning(
                "delete_mapping_not_found",
                source_chat_db_id=source_chat_db_id,
                source_message_id=source_message_id,
            )
            return False

        client = await self._get_client_for_mapping(mapping.session_pool_id)
        mirror_entity = await client.get_entity(mirror_chat.telegram_chat_id)

        try:
            await client.delete_messages(mirror_entity, mapping.mirror_message_id)
            logger.info(
                "message_deleted_in_mirror",
                source_message_id=source_message_id,
                mirror_message_id=mapping.mirror_message_id,
            )
            return True
        except MessageIdInvalidError as exc:
            logger.error(
                "delete_failed",
                error=str(exc),
                source_message_id=source_message_id,
            )
            return False
