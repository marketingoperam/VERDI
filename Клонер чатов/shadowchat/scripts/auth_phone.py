"""Вход по номеру телефона: запрос кода или подтверждение."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from app.config import get_settings

CODE_FILE = ROOT / "data" / "pending_auth.json"


def normalize_phone(raw: str) -> str:
    digits = "".join(c for c in raw.strip() if c.isdigit())
    if raw.strip().startswith("+"):
        return "+" + digits
    if len(digits) == 11 and digits.startswith("7"):
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return "+" + digits


async def request_code(session_name: str, phone: str) -> None:
    settings = get_settings()
    client = TelegramClient(
        str(settings.resolved_sessions_dir / session_name),
        settings.listener_api_id,
        settings.listener_api_hash,
    )
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"ALREADY_OK:{me.first_name}:@{me.username or ''}:{me.id}:{me.phone}")
        await client.disconnect()
        return

    sent = await client.send_code_request(phone)
    import json

    CODE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CODE_FILE.write_text(
        json.dumps(
            {
                "session_name": session_name,
                "phone": phone,
                "phone_code_hash": sent.phone_code_hash,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"CODE_SENT:{phone}:{session_name}")
    await client.disconnect()


async def confirm_code(session_name: str, code: str, password: str | None) -> None:
    import json

    if not CODE_FILE.exists():
        print("ERROR:no pending code — run request first")
        return
    pending = json.loads(CODE_FILE.read_text(encoding="utf-8"))
    if pending["session_name"] != session_name:
        print(f"ERROR:pending session is {pending['session_name']}, not {session_name}")
        return

    settings = get_settings()
    client = TelegramClient(
        str(settings.resolved_sessions_dir / session_name),
        settings.listener_api_id,
        settings.listener_api_hash,
    )
    await client.connect()
    try:
        await client.sign_in(
            phone=pending["phone"],
            code=code.strip().replace(" ", "").replace("-", ""),
            phone_code_hash=pending["phone_code_hash"],
        )
    except SessionPasswordNeededError:
        if not password:
            print("NEED_2FA: run with --password")
            await client.disconnect()
            return
        await client.sign_in(password=password)

    me = await client.get_me()
    CODE_FILE.unlink(missing_ok=True)
    print(f"OK:{me.first_name}:@{me.username or ''}:{me.id}:{me.phone}")
    await client.disconnect()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--session", default="tech_1")
    p.add_argument("--phone", default=None)
    p.add_argument("--code", default=None)
    p.add_argument("--password", default=None)
    args = p.parse_args()

    if args.code:
        asyncio.run(confirm_code(args.session, args.code, args.password))
    elif args.phone:
        asyncio.run(request_code(args.session, normalize_phone(args.phone)))
    else:
        print("Укажите --phone или --code")


if __name__ == "__main__":
    main()
