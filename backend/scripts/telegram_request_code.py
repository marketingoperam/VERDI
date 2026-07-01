#!/usr/bin/env python3
"""Шаг 1: запросить код входа в Telegram."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from collectors.tg_auth import describe_sent_code, normalize_phone, print_code_help, send_login_code
from collectors.tg_proxy import create_telegram_client, proxy_from_env, proxy_label


def _env(*names: str) -> str:
    for name in names:
        val = os.getenv(name, "").strip()
        if val:
            return val
    return ""


async def main(force_sms: bool = False) -> None:
    api_id = _env("TELEGRAM_API_ID", "TG_API_ID")
    api_hash = _env("TELEGRAM_API_HASH", "TG_API_HASH")
    phone = normalize_phone(_env("TG_PHONE", "TELEGRAM_PHONE"))
    session = _env("TELEGRAM_SESSION_PATH", "TG_SESSION") or "sessions/telegram"

    if not api_id or not api_hash or not phone:
        print("Заполните TELEGRAM_API_ID, TELEGRAM_API_HASH, TG_PHONE в .env")
        sys.exit(1)

    Path(session).parent.mkdir(parents=True, exist_ok=True)
    proxy = proxy_from_env()
    print(f"Подключение: {proxy_label(proxy)}")

    client = create_telegram_client(session, api_id, api_hash, proxy=proxy)
    try:
        await client.connect()
    except OSError as exc:
        print(f"Не удалось подключиться к Telegram: {exc}")
        print("Проверьте TG_PROXY в .env или интернет/VPN.")
        sys.exit(1)

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Уже авторизован: {me.first_name} (@{me.username or '—'})")
        await client.disconnect()
        return

    phone, sent = await send_login_code(client, phone, force_sms=force_sms)
    print_code_help(phone, describe_sent_code(sent, phone))
    await client.disconnect()

    print("Когда код придёт, запустите ВОЙТИ_В_TELEGRAM.bat и введите код.")
    if not force_sms:
        print("Или ЗАПРОСИТЬ_SMS.bat — если код не пришёл в приложение.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sms", action="store_true", help="Отправить код по SMS")
    args = parser.parse_args()
    asyncio.run(main(force_sms=args.sms))
