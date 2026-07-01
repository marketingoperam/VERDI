#!/usr/bin/env python3
"""Проверка подключения к Telegram (с прокси и без)."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

from tg_client import (
    candidate_proxies,
    create_telegram_client,
    proxy_label,
    proxy_to_env_value,
    save_working_proxy,
)


async def try_connect(api_id: int, api_hash: str, proxy) -> bool:
    try:
        client = create_telegram_client(
            ":memory:", api_id, api_hash, proxy=proxy, connection_retries=2, timeout=15
        )
    except Exception as exc:
        print(f"  FAIL: {proxy_label(proxy)} -> {type(exc).__name__}: {exc}")
        return False
    try:
        await client.connect()
        ok = client.is_connected()
        if ok:
            print(f"  OK: {proxy_label(proxy)}")
        return ok
    except Exception as exc:
        print(f"  FAIL: {proxy_label(proxy)} -> {type(exc).__name__}: {exc}")
        return False
    finally:
        await client.disconnect()


async def main_async(args: argparse.Namespace) -> int:
    load_dotenv(args.env_file)
    api_id = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    if not api_id or not api_hash:
        raise SystemExit("Заполните TG_API_ID и TG_API_HASH в .env")

    print("Проверяю подключение к серверам Telegram...\n")

    for proxy in candidate_proxies(args.proxy):
        print(f"Пробую: {proxy_label(proxy)}")
        if await try_connect(int(api_id), api_hash, proxy):
            if proxy:
                save_working_proxy(proxy)
                print("\nРабочий прокси сохранён автоматически.")
                print(f"Тип: {proxy[0]}")
                print(f"Строка: {proxy_to_env_value(proxy)}")
            else:
                print("\nПрокси не нужен.")
            return 0

    print("\nНе удалось подключиться.")
    print("Проверьте, что прокси активен, и снова запустите скрипт.")
    return 1


def main() -> None:
    p = argparse.ArgumentParser(description="Тест подключения Telethon.")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--proxy")
    sys.exit(asyncio.run(main_async(p.parse_args())))


if __name__ == "__main__":
    main()
