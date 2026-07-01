"""Authorize a Telethon session by scanning a QR code in Telegram."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import webbrowser
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

from app.config import get_settings


def _write_qr_page(qr_url: str, session_name: str) -> Path:
    settings = get_settings()
    html_path = settings.resolved_sessions_dir.parent / "data" / f"qr_{session_name}.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    qr_img = (
        "https://api.qrserver.com/v1/create-qr-code/?size=420x420&data="
        + quote(qr_url, safe="")
    )
    html_path.write_text(
        f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="25">
  <title>QR — {session_name}</title>
  <style>
    body {{ font-family: Segoe UI, sans-serif; text-align: center; padding: 32px;
            background: #0f1117; color: #e8eaed; }}
    img {{ border: 14px solid #fff; border-radius: 12px; margin: 16px 0; }}
    .hint {{ color: #9aa0a6; max-width: 420px; margin: 0 auto; line-height: 1.5; }}
  </style>
</head>
<body>
  <h1>Вход: {session_name}</h1>
  <p class="hint">Telegram → Настройки → Устройства → Подключить устройство → сканируйте QR</p>
  <img src="{qr_img}" alt="QR code" width="420" height="420">
  <p class="hint">Страница обновится через 25 сек, если QR истечёт</p>
</body>
</html>""",
        encoding="utf-8",
    )
    return html_path


async def auth_qr(session_name: str, password: str | None = None) -> None:
    settings = get_settings()
    session_path = settings.resolved_sessions_dir / session_name
    client = TelegramClient(
        str(session_path),
        settings.listener_api_id,
        settings.listener_api_hash,
    )
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Already authorized: {me.first_name} (id={me.id})")
        await client.disconnect()
        return

    qr = await client.qr_login()
    html_path = _write_qr_page(qr.url, session_name)
    print(f"QR page: {html_path}")
    webbrowser.open(html_path.as_uri())

    needs_password = False
    while True:
        try:
            await asyncio.wait_for(qr.wait(), timeout=90)
            break
        except asyncio.TimeoutError:
            print("QR expired, refreshing...")
            await qr.recreate()
            html_path = _write_qr_page(qr.url, session_name)
            print(f"New QR page: {html_path}")
        except SessionPasswordNeededError:
            needs_password = True
            break

    if needs_password and not password:
        print("NEED_2FA: run with --password YOUR_2FA_PASSWORD (scan QR again)")
        await client.disconnect()
        return

    if needs_password and password:
        await client.sign_in(password=password)
    elif password and not await client.is_user_authorized():
        await client.sign_in(password=password)

    me = await client.get_me()
    print(f"Authorized: {me.first_name} (@{me.username}) id={me.id} phone={me.phone}")
    await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(description="QR login for Telethon session")
    parser.add_argument("--session", default="listener_main")
    parser.add_argument("--password", default=None, help="2FA password if enabled")
    args = parser.parse_args()
    asyncio.run(auth_qr(args.session, args.password))


if __name__ == "__main__":
    main()
