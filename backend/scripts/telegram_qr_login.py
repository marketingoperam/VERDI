#!/usr/bin/env python3
"""Вход в Telegram по QR-коду (без SMS)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon.errors import SessionPasswordNeededError

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

from collectors.tg_proxy import create_telegram_client, proxy_from_env, proxy_label


def _env(*names: str) -> str:
    for name in names:
        val = os.getenv(name, "").strip()
        if val:
            return val
    return ""


def save_qr_png(url: str, path: Path) -> None:
    import qrcode

    path.parent.mkdir(parents=True, exist_ok=True)
    qrcode.make(url).save(path)


def open_qr_image(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        print(f"Откройте файл: {path}")


async def main() -> None:
    api_id = _env("TELEGRAM_API_ID", "TG_API_ID")
    api_hash = _env("TELEGRAM_API_HASH", "TG_API_HASH")
    session = _env("TELEGRAM_SESSION_PATH", "TG_SESSION") or "sessions/telegram"
    password = _env("TG_PASSWORD", "TELEGRAM_PASSWORD")
    qr_path = Path("sessions/telegram_qr.png")

    if not api_id or not api_hash:
        print("Заполните TELEGRAM_API_ID и TELEGRAM_API_HASH в .env")
        sys.exit(1)

    Path(session).parent.mkdir(parents=True, exist_ok=True)
    proxy = proxy_from_env()
    print(f"Вход по QR через {proxy_label(proxy)}")

    client = create_telegram_client(session, api_id, api_hash, proxy=proxy)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Уже авторизован: {me.first_name}")
        await client.disconnect()
        return

    qr_login = await client.qr_login()
    for attempt in range(1, 11):
        save_qr_png(qr_login.url, qr_path)
        print("\n" + "=" * 55)
        print("ОТКРОЙТЕ КАРТИНКУ С QR-КОДОМ")
        print(f"Файл: {qr_path.resolve()}")
        print()
        print("На телефоне: Telegram → Настройки → Устройства → Подключить устройство")
        print("Жду сканирование до 90 секунд...")
        print("=" * 55 + "\n")
        open_qr_image(qr_path)

        try:
            await qr_login.wait(timeout=90)
            break
        except SessionPasswordNeededError:
            pwd = password or input("Пароль 2FA: ").strip()
            await client.sign_in(password=pwd)
            break
        except (asyncio.TimeoutError, TimeoutError):
            print("QR устарел — обновляю...")
            await qr_login.recreate()
        except Exception as exc:
            print(f"Ошибка: {exc}")
            await qr_login.recreate()
    else:
        print("Не удалось войти по QR.")
        sys.exit(1)

    me = await client.get_me()
    print(f"\nВход выполнен: {me.first_name} (@{me.username or '—'})")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
