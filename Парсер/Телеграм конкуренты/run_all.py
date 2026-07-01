#!/usr/bin/env python3
"""Один скрипт: проверка прокси → вход → парсинг."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from parser_telegram_project import TelegramProjectParser
from tg_qr_login import login_via_qr
from tg_client import (
    candidate_proxies,
    create_telegram_client,
    proxy_from_env,
    proxy_label,
    save_working_proxy,
)
from tg_utils import save_entities_csv, save_json, save_summary_md, slugify_seed
from test_telegram_connection import try_connect


async def ensure_connection(api_id: str, api_hash: str) -> None:
    for proxy in candidate_proxies():
        print(f"Пробую: {proxy_label(proxy)}")
        if await try_connect(int(api_id), api_hash, proxy):
            if proxy:
                save_working_proxy(proxy)
                print("Рабочий прокси сохранён.\n")
            return
    raise SystemExit("Не удалось подключиться к Telegram. Проверьте прокси.")


async def login(api_id: str, api_hash: str, password: str, session: str) -> None:
    await login_via_qr(api_id, api_hash, session, password)


async def parse_project(api_id: str, api_hash: str, url: str, session: str, out_dir: str) -> None:
    proxy = proxy_from_env()
    client = create_telegram_client(session, api_id, api_hash, proxy=proxy)
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Сначала нужен вход в Telegram")

    parser = TelegramProjectParser(client, max_depth=2, max_messages=200, delay_seconds=1.5)
    try:
        report = await parser.crawl(url)
    finally:
        await client.disconnect()

    out = Path(out_dir)
    slug = slugify_seed(url)
    ts = time.strftime("%Y%m%d_%H%M%S")
    base = out / f"{slug}_{ts}"
    save_json(report, base.with_suffix(".json"))
    save_entities_csv(report, base.with_name(base.name + "_entities").with_suffix(".csv"))
    save_summary_md(report, base.with_name(base.name + "_summary").with_suffix(".md"))
    print(f"\nГотово. Сущностей: {report.total_entities}")
    print(f"JSON: {base.with_suffix('.json')}")
    print(f"CSV:  {base.with_name(base.name + '_entities').with_suffix('.csv')}")


async def main_async() -> None:
    load_dotenv()
    api_id = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    phone = os.getenv("TG_PHONE", "").strip()
    password = os.getenv("TG_PASSWORD", "").strip()
    url = os.getenv("TG_PARSE_URL", "https://t.me/instachat6")
    session = "sessions/tg_project"
    Path(session).parent.mkdir(parents=True, exist_ok=True)

    if not api_id or not api_hash:
        raise SystemExit("Заполните TG_API_ID и TG_API_HASH в .env")

    print("=== 1/3 Проверка прокси ===")
    await ensure_connection(api_id, api_hash)

    print("=== 2/3 Вход по QR (без кода) ===")
    await login(api_id, api_hash, password, session)

    print("=== 3/3 Парсинг instachat6 ===")
    await parse_project(api_id, api_hash, url, session, "output")
    input("\nНажмите Enter для выхода...")


def main() -> None:
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        sys.exit(1)


if __name__ == "__main__":
    main()
