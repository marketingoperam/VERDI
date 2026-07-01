"""ИИ-оператор: только копирование профиля и сообщений."""

from __future__ import annotations

import json
import re

from gonka import GonkaClient

SYSTEM = """Ты оператор зеркалирования Telegram-чатов.

Разрешены ТОЛЬКО два действия:
1. copy_profile — сменить имя и аватар техаккаунта под отправителя
2. copy_message — отправить текст/медиа в зеркальный чат

Любые другие действия запрещены.

На каждое входящее сообщение отвечай ТОЛЬКО JSON без markdown:
{"copy_profile": true|false, "copy_message": true|false, "reason": "кратко"}

По умолчанию для обычных сообщений людей: copy_profile=true, copy_message=true.
Для ботов и пустых сервисных сообщений: оба false."""


class MirrorBrain:
    def __init__(self, client: GonkaClient | None = None):
        self.client = client or GonkaClient()

    async def decide(
        self,
        *,
        sender_name: str,
        sender_is_bot: bool,
        has_text: bool,
        has_media: bool,
        is_service: bool,
    ) -> dict:
        if not self.client.configured:
            return {"copy_profile": True, "copy_message": True, "reason": "ai_off"}

        user = (
            f"Отправитель: {sender_name}\n"
            f"Бот: {sender_is_bot}\n"
            f"Текст: {has_text}\n"
            f"Медиа: {has_media}\n"
            f"Сервисное: {is_service}"
        )
        raw = await self.client.chat(
            [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ]
        )
        return self._parse_json(raw)

    @staticmethod
    def _parse_json(raw: str) -> dict:
        raw = raw.strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return {"copy_profile": True, "copy_message": True, "reason": "parse_fallback"}
        try:
            data = json.loads(match.group())
            return {
                "copy_profile": bool(data.get("copy_profile", True)),
                "copy_message": bool(data.get("copy_message", True)),
                "reason": str(data.get("reason", "")),
            }
        except json.JSONDecodeError:
            return {"copy_profile": True, "copy_message": True, "reason": "parse_fallback"}

    async def ping(self) -> str:
        return await self.client.chat(
            [
                {"role": "system", "content": "Ответь одним словом: ok"},
                {"role": "user", "content": "ping"},
            ],
            max_tokens=8,
        )
