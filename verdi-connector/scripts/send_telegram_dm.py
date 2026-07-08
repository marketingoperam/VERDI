"""Отправка DM через Telethon (сессии ShadowChat). Печатает JSON в stdout."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import timezone
from pathlib import Path

from telethon import TelegramClient

ROOT = Path(__file__).resolve().parents[1]
SHADOWCHAT = ROOT.parent / "shadowchat"
sys.path.insert(0, str(SHADOWCHAT))
os.chdir(SHADOWCHAT)

from app.config import get_settings  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="tech_13309563469")
    parser.add_argument("--peer-id", required=True, help="Telegram user/chat id")
    parser.add_argument("--text", default="")
    args = parser.parse_args()

    text = args.text
    if not text and not sys.stdin.isatty():
        text = sys.stdin.buffer.read().decode('utf-8')
    text = text.strip()
    if not text:
        print(json.dumps({"error": "empty text"}), file=sys.stderr)
        sys.exit(2)

    settings = get_settings()
    client = TelegramClient(
        str(settings.resolved_sessions_dir / args.session),
        settings.listener_api_id,
        settings.listener_api_hash,
    )
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(f"Сессия {args.session} не авторизована")

    entity = await client.get_entity(int(args.peer_id))
    msg = await client.send_message(entity, text)
    sent_at = msg.date
    if sent_at.tzinfo is None:
        sent_at = sent_at.replace(tzinfo=timezone.utc)

    print(
        json.dumps(
            {
                "telegramMessageId": str(msg.id),
                "sentAt": sent_at.isoformat(),
            },
            ensure_ascii=False,
        )
    )
    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        sys.exit(1)
