"""Authorize a Telethon session interactively."""

import argparse
import asyncio
from pathlib import Path

from telethon import TelegramClient

from app.config import get_settings


async def auth(session_name: str) -> None:
    settings = get_settings()
    sessions_dir = settings.resolved_sessions_dir
    sessions_dir.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(
        str(sessions_dir / session_name),
        settings.listener_api_id,
        settings.listener_api_hash,
    )
    await client.start()
    me = await client.get_me()
    print(f"Authorized: {me.first_name} (@{me.username}) id={me.id}")
    await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="Authorize Telethon session")
    parser.add_argument("--session", default="listener_main", help="Session file name")
    args = parser.parse_args()
    asyncio.run(auth(args.session))


if __name__ == "__main__":
    main()
