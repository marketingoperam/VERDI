"""Вход в Telegram по QR-коду (без SMS)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from telethon.errors import SessionPasswordNeededError

from tg_client import create_telegram_client, proxy_from_env, proxy_label


def save_qr_png(url: str, path: Path) -> None:
    import qrcode

    path.parent.mkdir(parents=True, exist_ok=True)
    img = qrcode.make(url)
    img.save(path)


def open_qr_image(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        print(f"Откройте файл: {path}")


async def login_via_qr(
    api_id: str,
    api_hash: str,
    session: str,
    password: str = "",
    qr_path: Path | None = None,
) -> None:
    qr_path = qr_path or Path("sessions/telegram_qr.png")
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
    attempt = 0

    while True:
        attempt += 1
        save_qr_png(qr_login.url, qr_path)
        print("\n" + "=" * 55)
        print("ОТКРОЙТЕ КАРТИНКУ С QR-КОДОМ (должна открыться сама)")
        print(f"Файл: {qr_path.resolve()}")
        print()
        print("На телефоне:")
        print("  Telegram → Настройки → Устройства")
        print("  → Подключить устройство → сканируйте QR")
        print()
        print("Жду сканирование до 90 секунд...")
        print("=" * 55 + "\n")
        open_qr_image(qr_path)

        try:
            await qr_login.wait(timeout=90)
            break
        except SessionPasswordNeededError:
            pwd = password.strip() or input("Введите пароль 2FA: ").strip()
            await client.sign_in(password=pwd)
            break
        except (asyncio.TimeoutError, TimeoutError):
            print("QR устарел — обновляю картинку...")
            await qr_login.recreate()
            if attempt >= 10:
                raise SystemExit("Не удалось войти по QR. Попробуйте снова.")
        except Exception as exc:
            print(f"Ошибка: {exc}. Обновляю QR...")
            await qr_login.recreate()
            if attempt >= 10:
                raise

    me = await client.get_me()
    print(f"\nВход выполнен: {me.first_name} (@{me.username or '—'})")
    await client.disconnect()
