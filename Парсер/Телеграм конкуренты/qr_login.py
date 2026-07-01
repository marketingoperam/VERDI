#!/usr/bin/env python3
"""Вход по QR-коду — без SMS и без кода."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv

from test_telegram_connection import try_connect
from tg_client import candidate_proxies, proxy_from_env, proxy_label, save_working_proxy
from tg_qr_login import login_via_qr


async def main_async() -> None:
    load_dotenv()
    api_id = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    password = os.getenv("TG_PASSWORD", "").strip()
    session = "sessions/tg_project"

    if not api_id or not api_hash:
        raise SystemExit("Заполните TG_API_ID и TG_API_HASH в .env")

    print("=== Проверка прокси ===")
    for proxy in candidate_proxies():
        print(f"Пробую: {proxy_label(proxy)}")
        if await try_connect(int(api_id), api_hash, proxy):
            if proxy:
                save_working_proxy(proxy)
            break
    else:
        raise SystemExit("Нет подключения к Telegram.")

    print("\n=== Вход по QR ===")
    await login_via_qr(api_id, api_hash, session, password)
    print("\nГотово! Теперь запустите ЗАПУСТИТЬ_ПАРСЕР.bat")


def main() -> None:
    asyncio.run(main_async())
    input("\nНажмите Enter...")


if __name__ == "__main__":
    main()
