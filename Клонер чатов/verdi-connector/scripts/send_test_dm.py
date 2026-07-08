"""Отправка тестового DM от тех-аккаунта (использует сессии ShadowChat)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from telethon import TelegramClient

ROOT = Path(__file__).resolve().parents[2]
SHADOWCHAT = ROOT.parent / "shadowchat"
sys.path.insert(0, str(SHADOWCHAT))

from app.config import get_settings  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="tech_13309563469")
    parser.add_argument("--to", default="kmuseinov")
    parser.add_argument("--text", default="Тест VERDI Connector — сообщение от тех-аккаунта.")
    args = parser.parse_args()

    settings = get_settings()
    session_path = settings.resolved_sessions_dir / args.session
    if not session_path.with_suffix(".session").exists() and not Path(str(session_path) + ".session").exists():
        # Telethon adds .session automatically
        pass

    client = TelegramClient(
        str(settings.resolved_sessions_dir / args.session),
        settings.listener_api_id,
        settings.listener_api_hash,
    )
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(f"Сессия {args.session} не авторизована")

    me = await client.get_me()
    entity = await client.get_entity(args.to)
    msg = await client.send_message(entity, args.text)
    print(f"OK from @{me.username or me.id} -> @{args.to} message_id={msg.id}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
