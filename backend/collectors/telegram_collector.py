from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from telethon.tl.custom.message import Message

from collectors.base import BaseCollector
from collectors.tg_proxy import create_telegram_client, proxy_from_env

logger = logging.getLogger(__name__)


def _normalize_channel(username: str) -> str:
    username = username.strip()
    if username.startswith("https://t.me/"):
        username = username.split("/")[-1]
    return username.lstrip("@")


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    lower = text.lower()
    return any(kw.lower() in lower for kw in keywords if kw)


class TelegramCollector(BaseCollector):
    name = "telegram"

    async def _collect_channel(
        self,
        client: TelegramClient,
        channel: str,
        competitor_id: int,
        keywords: list[str],
        limit: int,
        app_settings,
        db,
        *,
        filter_keywords: bool = False,
    ) -> int:
        saved = 0
        username = _normalize_channel(channel)
        try:
            entity = await client.get_entity(username)
        except Exception as exc:
            logger.warning("Cannot resolve Telegram channel %s: %s", channel, exc)
            return 0

        async for message in client.iter_messages(entity, limit=limit):
            if not isinstance(message, Message) or not message.message:
                continue
            text = message.message
            if filter_keywords and not _matches_keywords(text, keywords):
                continue

            msg_id = message.id
            chan_username = getattr(entity, "username", None) or username
            url = f"https://t.me/{chan_username}/{msg_id}"
            published = message.date.replace(tzinfo=None) if message.date else None

            finding_data = {
                "competitor_id": competitor_id,
                "source": "telegram",
                "result_type": "post",
                "external_id": f"{chan_username}_{msg_id}",
                "title": text[:120],
                "raw_text": text,
                "url": url,
                "channel_name": chan_username,
                "views": message.views,
                "published_at": published,
                "raw_json": {"id": msg_id, "text": text},
            }
            if await self._save_and_analyze(db, finding_data, app_settings):
                saved += 1

        return saved

    async def collect(self) -> int:
        total_saved = 0
        async with self.session_factory() as db:
            app_settings = await self._get_runtime_settings(db)
            if not app_settings.telegram_enabled:
                logger.info("Telegram collector disabled")
                return 0

            api_id = app_settings.telegram_api_id or self.settings.telegram_api_id
            api_hash = app_settings.telegram_api_hash or self.settings.telegram_api_hash
            if not api_id or not api_hash:
                raise ValueError("Telegram API_ID and API_HASH are required")

            session_path = Path(self.settings.telegram_session_path)
            session_path.parent.mkdir(parents=True, exist_ok=True)

            competitors = await self._get_competitors(db)
            limit = self.settings.max_results_per_query

            client = create_telegram_client(str(session_path), api_id, api_hash, proxy=proxy_from_env())
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                raise ValueError(
                    "Telegram session not authorized. Run telethon login first."
                )

            try:
                for competitor in competitors:
                    channels = competitor.telegram_channels or []
                    keywords = (competitor.brand_keywords or []) + (
                        competitor.money_keywords or []
                    )
                    for channel in channels:
                        if not channel.strip():
                            continue
                        saved = await self._collect_channel(
                            client,
                            channel,
                            competitor.id,
                            keywords,
                            limit,
                            app_settings,
                            db,
                            filter_keywords=False,
                        )
                        total_saved += saved
                        await asyncio.sleep(1)
            finally:
                await client.disconnect()

        return total_saved
