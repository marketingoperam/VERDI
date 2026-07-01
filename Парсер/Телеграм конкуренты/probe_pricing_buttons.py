#!/usr/bin/env python3
"""Клик по кнопкам VIP и рекламы в mpickles_bot."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from tg_client import create_telegram_client, proxy_from_env

ROOT = Path(__file__).resolve().parent
SESSION = str(ROOT / "sessions" / "tg_project")
OUT = ROOT / "output" / "pricing_full.json"

PRIMARY = [
    "Условия и цены 💎 VIP 💎",
    "Реклама 📣",
    "Разблокировка ✅",
]


async def latest_bot_reply(client, bot):
    await asyncio.sleep(3)
    for message in await client.get_messages(bot, limit=6):
        if not message.out:
            return message
    return None


async def main() -> None:
    load_dotenv(ROOT / ".env")
    client = create_telegram_client(
        SESSION,
        os.getenv("TG_API_ID", ""),
        os.getenv("TG_API_HASH", ""),
        proxy=proxy_from_env(),
    )
    await client.connect()
    bot = await client.get_entity("mpickles_bot")
    await client.send_message(bot, "/start")
    await asyncio.sleep(3)

    report: dict = {"sections": []}
    for button in PRIMARY:
        await client.send_message(bot, button)
        message = await latest_bot_reply(client, bot)
        section = {
            "button": button,
            "text": message.text if message else "",
            "buttons": (
                [[b.text for b in row] for row in message.buttons]
                if message and message.buttons
                else []
            ),
            "subclicks": [],
        }
        if message and message.buttons:
            for row in message.buttons:
                for sub in row:
                    await client.send_message(bot, sub.text)
                    sub_msg = await latest_bot_reply(client, bot)
                    section["subclicks"].append(
                        {
                            "button": sub.text,
                            "text": sub_msg.text if sub_msg else "",
                            "buttons": (
                                [[b.text for b in r] for r in sub_msg.buttons]
                                if sub_msg and sub_msg.buttons
                                else []
                            ),
                        }
                    )
        report["sections"].append(section)

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {OUT}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
