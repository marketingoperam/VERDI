#!/usr/bin/env python3
"""Авторизация Telethon (отдельный шаг перед парсингом)."""

from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telethon.errors import SessionPasswordNeededError

from tg_auth import describe_sent_code, normalize_phone, print_code_help, send_login_code
from tg_client import create_telegram_client, proxy_from_env, proxy_label


async def login(args: argparse.Namespace) -> None:
    load_dotenv(args.env_file)
    api_id = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    phone = normalize_phone(args.phone or os.getenv("TG_PHONE", ""))
    code = (args.code or os.getenv("TG_CODE", "")).strip()
    password = (args.password or os.getenv("TG_PASSWORD", "")).strip()

    if not api_id or not api_hash:
        raise SystemExit("Заполните TG_API_ID и TG_API_HASH в .env")
    if not phone:
        raise SystemExit("Укажите TG_PHONE в .env или --phone")

    session_path = str(Path(args.session).expanduser())
    Path(session_path).parent.mkdir(parents=True, exist_ok=True)

    proxy = proxy_from_env()
    print(f"Подключение: {proxy_label(proxy)}")
    client = create_telegram_client(session_path, api_id, api_hash, proxy=proxy)
    try:
        await client.connect()
    except OSError as exc:
        raise SystemExit(
            f"Не удалось подключиться к Telegram ({exc}).\n"
            "Запустите: python test_telegram_connection.py\n"
            "И добавьте рабочий TG_PROXY в .env"
        ) from exc

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Уже авторизован: {me.first_name} (@{me.username or '—'})")
        await client.disconnect()
        return

    if not code:
        phone, sent = await send_login_code(client, phone, force_sms=args.sms)
        print_code_help(phone, describe_sent_code(sent, phone))
        await client.disconnect()
        return

    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        if not password:
            raise SystemExit("Включена 2FA — добавьте TG_PASSWORD в .env или --password")
        await client.sign_in(password=password)

    me = await client.get_me()
    print(f"Вход выполнен: {me.first_name} (@{me.username or '—'})")
    await client.disconnect()


def main() -> None:
    p = argparse.ArgumentParser(description="Вход в Telegram для парсера.")
    p.add_argument("--env-file", default=".env")
    p.add_argument("--session", default="sessions/tg_project")
    p.add_argument("--phone")
    p.add_argument("--code")
    p.add_argument("--sms", action="store_true", help="Отправить код SMS, не в приложение")
    p.add_argument("--password")
    args = p.parse_args()
    asyncio.run(login(args))


if __name__ == "__main__":
    main()
