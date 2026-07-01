from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MessageMap


class MessageMapper:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_mirror_message_id(
        self, source_chat_db_id: int, source_message_id: int
    ) -> int | None:
        result = await self.db.execute(
            select(MessageMap.mirror_message_id).where(
                MessageMap.source_chat_id == source_chat_db_id,
                MessageMap.source_message_id == source_message_id,
            )
        )
        row = result.scalar_one_or_none()
        return row

    async def exists(self, source_chat_db_id: int, source_message_id: int) -> bool:
        result = await self.db.execute(
            select(MessageMap.id).where(
                MessageMap.source_chat_id == source_chat_db_id,
                MessageMap.source_message_id == source_message_id,
            )
        )
        return result.scalar_one_or_none() is not None

    async def save_mapping(
        self,
        source_chat_db_id: int,
        source_message_id: int,
        mirror_chat_db_id: int,
        mirror_message_id: int,
        source_sender_id: int,
        session_pool_id: int | None,
    ) -> MessageMap:
        mapping = MessageMap(
            source_chat_id=source_chat_db_id,
            source_message_id=source_message_id,
            mirror_chat_id=mirror_chat_db_id,
            mirror_message_id=mirror_message_id,
            source_sender_id=source_sender_id,
            session_pool_id=session_pool_id,
        )
        self.db.add(mapping)
        await self.db.flush()
        return mapping

    async def get_mapping(
        self, source_chat_db_id: int, source_message_id: int
    ) -> MessageMap | None:
        result = await self.db.execute(
            select(MessageMap).where(
                MessageMap.source_chat_id == source_chat_db_id,
                MessageMap.source_message_id == source_message_id,
            )
        )
        return result.scalar_one_or_none()
