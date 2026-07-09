from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from telethon import TelegramClient
from telethon.errors import UserAlreadyParticipantError
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.types import User

from app.models import Employee, MessageMap, MirrorChat, MirrorMode, SessionPool, SourceChat
from app.services.message_mapper import MessageMapper
from app.telegram.media_handler import MediaHandler
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()


class MirrorSender:
    def __init__(
        self,
        session_pool: SessionPoolManager,
        media_handler: MediaHandler | None = None,
    ):
        self.session_pool = session_pool
        self.media_handler = media_handler or MediaHandler()

    def format_safe_message(
        self,
        text: str,
        employee: Employee,
        source_chat: SourceChat,
        message_date: datetime | None = None,
    ) -> str:
        name_parts = [employee.first_name or ""]
        if employee.last_name:
            name_parts.append(employee.last_name)
        author = " ".join(name_parts).strip() or "Unknown"
        chat_title = source_chat.title or "Чат"
        time_str = ""
        if message_date:
            time_str = message_date.strftime("%H:%M")

        header = f"[{chat_title} / {author}]"
        if time_str:
            return f"{header}\n{time_str}\n{text}" if text else f"{header}\n{time_str}"
        return f"{header}\n{text}" if text else header

    async def format_safe_edit(self, new_text: str, mapping: MessageMap) -> str:
        return new_text

    async def _resolve_mirror_entity(self, client: TelegramClient, mirror_chat: MirrorChat):
        try:
            return await client.get_entity(mirror_chat.telegram_chat_id)
        except (ValueError, TypeError):
            username = (mirror_chat.mirror_username or "").strip().lstrip("@")
            if not username:
                raise
            channel = await client.get_entity(username)
            try:
                await client(JoinChannelRequest(channel=channel))
            except UserAlreadyParticipantError:
                pass
            return channel

    async def send_mirror_message(
        self,
        db: AsyncSession,
        client: TelegramClient,
        message,
        employee: Employee,
        source_chat: SourceChat,
        mirror_chat: MirrorChat,
        session: SessionPool,
        reply_to_mirror_id: int | None = None,
        used_fallback: bool = False,
    ) -> int | None:
        mirror_entity = await self._resolve_mirror_entity(client, mirror_chat)
        mapper = MessageMapper(db)

        text = message.message or message.text or ""

        media_path = None
        try:
            if message.media:
                media_path, media_type = await self.media_handler.download_media(message)
                if media_path:
                    sent = await self.session_pool.with_flood_wait_retry(
                        lambda: client.send_file(
                            mirror_entity,
                            media_path,
                            caption=text or None,
                            reply_to=reply_to_mirror_id,
                            voice=media_type == "voice",
                            video_note=media_type == "video_note",
                        )
                    )
                else:
                    fallback_text = text or f"[{media_type}]"
                    sent = await self.session_pool.with_flood_wait_retry(
                        lambda: client.send_message(
                            mirror_entity,
                            fallback_text,
                            reply_to=reply_to_mirror_id,
                        )
                    )
            else:
                if not text:
                    return None
                sent = await self.session_pool.with_flood_wait_retry(
                    lambda: client.send_message(
                        mirror_entity,
                        text,
                        reply_to=reply_to_mirror_id,
                    )
                )

            mirror_message_id = sent.id
            await mapper.save_mapping(
                source_chat_db_id=source_chat.id,
                source_message_id=message.id,
                mirror_chat_db_id=mirror_chat.id,
                mirror_message_id=mirror_message_id,
                source_sender_id=employee.telegram_user_id,
                session_pool_id=session.id,
            )

            logger.info(
                "message_mirrored",
                source_message_id=message.id,
                mirror_message_id=mirror_message_id,
                employee_id=employee.id,
                session_name=session.session_name,
                used_fallback=used_fallback,
            )
            return mirror_message_id
        finally:
            self.media_handler.cleanup(media_path)

    async def fetch_sender_info(self, client: TelegramClient, sender_id: int) -> tuple[str, str | None, str | None]:
        try:
            entity = await client.get_entity(sender_id)
            if isinstance(entity, User):
                return entity.first_name or "", entity.last_name, entity.username
        except Exception as exc:
            logger.warning("fetch_sender_failed", sender_id=sender_id, error=str(exc))
        return "", None, None
