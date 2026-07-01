#!/usr/bin/env python3
"""Шаг 2: ввести код и завершить вход в Telegram."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon.errors import (
    PhoneCodeExpiredError,
    PhoneCodeInvalidError,
    SessionPasswordNeededError,
)

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from collectors.tg_auth import normalize_phone, parse_code_input, print_code_help, send_login_code
from collectors.tg_proxy import create_telegram_client, proxy_from_env, proxy_label


def _env(*names: str) -> str:
    for name in names:
        val = os.getenv(name, "").strip()
        if val:
            return val
    return ""


async def main(code: str = "", password: str = "", force_sms: bool = False) -> None:
    api_id = _env("TELEGRAM_API_ID", "TG_API_ID")
    api_hash = _env("TELEGRAM_API_HASH", "TG_API_HASH")
    phone = normalize_phone(_env("TG_PHONE", "TELEGRAM_PHONE"))
    session = _env("TELEGRAM_SESSION_PATH", "TG_SESSION") or "sessions/telegram"
    password = password or _env("TG_PASSWORD", "TELEGRAM_PASSWORD")

    if not api_id or not api_hash or not phone:
        print("Заполните TELEGRAM_API_ID, TELEGRAM_API_HASH, TG_PHONE в .env")
        sys.exit(1)

    Path(session).parent.mkdir(parents=True, exist_ok=True)
    proxy = proxy_from_env()
    print(f"Подключение: {proxy_label(proxy)}")

    client = create_telegram_client(session, api_id, api_hash, proxy=proxy)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Уже авторизован: {me.first_name} (@{me.username or '—'})")
        await client.disconnect()
        return

    if not code:
        print("Сначала запросите код: ЗАПРОСИТЬ_КОД.bat")
        print("Или введите код сейчас (s + Enter — повторить запрос по SMS):")
        raw = input("Код: ").strip()
        code, want_sms = parse_code_input(raw)
        if want_sms:
            phone, sent = await send_login_code(client, phone, force_sms=True)
            from collectors.tg_auth import describe_sent_code

            print_code_help(phone, describe_sent_code(sent, phone))
            code = input("Код из SMS: ").strip()
            code, _ = parse_code_input(code)

    if not code:
        print("Код не введён.")
        sys.exit(1)

    try:
        await client.sign_in(phone=phone, code=code)
    except PhoneCodeInvalidError:
        print("Неверный код. Запустите ЗАПРОСИТЬ_КОД.bat и попробуйте снова.")
        sys.exit(1)
    except PhoneCodeExpiredError:
        print("Код устарел. Запустите ЗАПРОСИТЬ_КОД.bat заново.")
        sys.exit(1)
    except SessionPasswordNeededError:
        if not password:
            password = input("Пароль 2FA: ").strip()
        await client.sign_in(password=password)

    me = await client.get_me()
    print(f"\nВход выполнен: {me.first_name} (@{me.username or '—'})")
    await client.disconnect()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--code")
    p.add_argument("--password")
    p.add_argument("--sms", action="store_true")
    args = p.parse_args()
    asyncio.run(main(code=args.code or "", password=args.password or "", force_sms=args.sms))
