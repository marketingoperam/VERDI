#!/usr/bin/env python3
"""Только запросить код входа (отдельно от парсера)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from tg_auth import describe_sent_code, normalize_phone, print_code_help, send_login_code
from tg_client import create_telegram_client, proxy_from_env, proxy_label


async def main_async() -> None:
    load_dotenv()
    api_id = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    phone = normalize_phone(os.getenv("TG_PHONE", ""))
    force_sms = os.getenv("TG_FORCE_SMS", "").strip().lower() in {"1", "true", "yes"}

    if not api_id or not api_hash or not phone:
        raise SystemExit("Заполните TG_API_ID, TG_API_HASH, TG_PHONE в .env")

    session = "sessions/tg_project"
    Path(session).parent.mkdir(parents=True, exist_ok=True)

    proxy = proxy_from_env()
    print(f"Подключение: {proxy_label(proxy)}")
    client = create_telegram_client(session, api_id, api_hash, proxy=proxy)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Вы уже вошли как {me.first_name}. Парсер можно запускать.")
        await client.disconnect()
        return

    phone, sent = await send_login_code(client, phone, force_sms=force_sms)
    print_code_help(phone, describe_sent_code(sent, phone))
    await client.disconnect()

    print("Когда код придёт, запустите:")
    print("  python tg_login.py --code ВАШ_КОД")
    print("или снова ЗАПУСТИТЬ_ПАРСЕР.bat")


def main() -> None:
    asyncio.run(main_async())
    input("\nНажмите Enter...")


if __name__ == "__main__":
    main()
