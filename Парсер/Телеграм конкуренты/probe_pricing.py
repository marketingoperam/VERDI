#!/usr/bin/env python3
"""Опрос ботов конкурента actinsta для сбора цен VIP и рекламы."""

from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.tl.custom.message import Message

from parser_telegram_project import extract_inline_buttons, serialize_message
from tg_client import create_telegram_client, proxy_from_env

ROOT = Path(__file__).resolve().parent
SESSION = str(ROOT / "sessions" / "tg_project")
OUT = ROOT / "output" / "pricing_probe.json"

CHAT_IDS = [
    "-1001349684717",  # instachat6
    "-1001191738953",
]

PRICE_HINTS = re.compile(
    r"vip|руб|₽|цена|тариф|оплат|стоим|реклам|stars|звезд|usdt|карт|юmoney|qiwi|бесплат",
    re.I,
)

KEYWORD_BUTTONS = (
    "VIP",
    "💎",
    "реклам",
    "тариф",
    "цена",
    "оплат",
    "прайс",
    "подписк",
    "Stars",
)


def button_texts(message: Message) -> list[str]:
    texts: list[str] = []
    if not message.buttons:
        return texts
    for row in message.buttons:
        for button in row:
            if button.text:
                texts.append(button.text.strip())
    return texts


def is_price_related(text: str) -> bool:
    return bool(PRICE_HINTS.search(text or ""))


async def collect_response(conv, wait: float = 6.0) -> Message | None:
    try:
        return await conv.get_response(timeout=wait)
    except asyncio.TimeoutError:
        return None


async def probe_bot(client: TelegramClient, username: str, triggers: list[str]) -> dict:
    result: dict = {"bot": username, "steps": [], "errors": []}
    entity = await client.get_entity(username)
    try:
        async with client.conversation(entity, timeout=90) as conv:
            for trigger in triggers:
                step = {"trigger": trigger, "responses": []}
                await conv.send_message(trigger)
                await asyncio.sleep(1.5)
                for _ in range(3):
                    response = await collect_response(conv)
                    if not response:
                        break
                    payload = serialize_message(response, max_text_len=8000)
                    payload["keyboard_buttons"] = button_texts(response)
                    step["responses"].append(payload)
                    if not response.buttons:
                        break
                result["steps"].append(step)

            # Кликаем по кнопкам меню, связанным с ценами
            visited: set[str] = set()
            for step in list(result["steps"]):
                for resp in step["responses"]:
                    for btn in resp.get("keyboard_buttons", []):
                        if btn in visited:
                            continue
                        if not any(k.lower() in btn.lower() for k in KEYWORD_BUTTONS):
                            continue
                        visited.add(btn)
                        click_step = {"trigger": f"[button] {btn}", "responses": []}
                        await conv.send_message(btn)
                        await asyncio.sleep(2.0)
                        for _ in range(4):
                            response = await collect_response()
                            if not response:
                                break
                            payload = serialize_message(response, max_text_len=8000)
                            payload["keyboard_buttons"] = button_texts(response)
                            click_step["responses"].append(payload)
                            # один уровень вложенности по дочерним кнопкам
                            for child in payload.get("keyboard_buttons", []):
                                if child in visited:
                                    continue
                                if is_price_related(child) or any(
                                    k.lower() in child.lower() for k in KEYWORD_BUTTONS
                                ):
                                    visited.add(child)
                                    await conv.send_message(child)
                                    await asyncio.sleep(2.0)
                                    sub = await collect_response()
                                    if sub:
                                        sub_payload = serialize_message(sub, max_text_len=8000)
                                        sub_payload["keyboard_buttons"] = button_texts(sub)
                                        click_step["responses"].append(
                                            {"from_child_button": child, **sub_payload}
                                        )
                            break
                        result["steps"].append(click_step)
    except Exception as exc:
        result["errors"].append(f"{type(exc).__name__}: {exc}")
    return result


async def main() -> None:
    load_dotenv(ROOT / ".env")
    api_id = os.getenv("TG_API_ID", "")
    api_hash = os.getenv("TG_API_HASH", "")
    if not api_id or not api_hash:
        raise SystemExit("Нужны TG_API_ID и TG_API_HASH в .env")

    proxy = proxy_from_env()
    client = create_telegram_client(SESSION, api_id, api_hash, proxy=proxy)
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Сессия не авторизована. Сначала войдите через ВХОД_ПО_QR.bat")

    mpickles_triggers = ["/start"]
    actdino_triggers = ["/start"]
    for chat_id in CHAT_IDS:
        actdino_triggers.extend(
            [
                f"/start {chat_id}_rules",
                f"/start {chat_id}_list",
                f"/start {chat_id}_vip",
                f"/start {chat_id}_ads",
                f"/start {chat_id}_price",
            ]
        )

    report = {
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "bots": [
            await probe_bot(client, "mpickles_bot", mpickles_triggers),
            await probe_bot(client, "actdino_bot", actdino_triggers),
        ],
    }

    # Сводка текстов, где есть цены
    price_snippets: list[dict] = []
    for bot in report["bots"]:
        for step in bot["steps"]:
            for resp in step["responses"]:
                text = resp.get("text", "")
                if is_price_related(text):
                    price_snippets.append(
                        {
                            "bot": bot["bot"],
                            "trigger": step["trigger"],
                            "text": text,
                        }
                    )
    report["price_snippets"] = price_snippets

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Сохранено: {OUT}")
    print(f"Фрагментов с ценами: {len(price_snippets)}")
    for item in price_snippets[:20]:
        print("\n---", item["bot"], item["trigger"], "---")
        print(item["text"][:1500])

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
