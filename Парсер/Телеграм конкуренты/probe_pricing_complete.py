#!/usr/bin/env python3
"""Полный прайс VIP: все тарифы и разовые заказы."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from tg_client import create_telegram_client, proxy_from_env

ROOT = Path(__file__).resolve().parent
SESSION = str(ROOT / "sessions" / "tg_project")
OUT = ROOT / "output" / "pricing_complete.json"

VIP_TARIFFS = [
    "🔴 ЛС (лайк/сохранение)",
    "🟢 ЛПС (лайк/подписка/сохранение)",
    "🔵 ЛКС (лайк/коммент/сохранение)",
    "🟣 ЛКСП (лайк/коммент/сохранение/подписка)",
    "🟠 Индивидуальные условия",
]


async def reply_text(client, bot) -> str:
    await asyncio.sleep(3)
    parts: list[str] = []
    seen: set[int] = set()
    for message in await client.get_messages(bot, limit=8):
        if message.out or message.id in seen:
            continue
        seen.add(message.id)
        if message.text:
            parts.append(message.text)
    return "\n\n".join(parts)


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
    await asyncio.sleep(2)
    await client.send_message(bot, "Условия и цены 💎 VIP 💎")
    vip_overview = await reply_text(client, bot)

    await client.send_message(bot, "Купить 💎 VIP 💎")
    await asyncio.sleep(2)

    tariffs: list[dict] = []
    for tariff in VIP_TARIFFS:
        await client.send_message(bot, tariff)
        text = await reply_text(client, bot)
        tariffs.append({"tariff": tariff, "text": text})
        await client.send_message(bot, "🔙 Назад")
        await asyncio.sleep(2)

    report = {
        "vip_overview": vip_overview,
        "tariffs": tariffs,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {OUT}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
