"""Запрос кода входа в Telegram."""

from __future__ import annotations

import re

from telethon.errors import FloodWaitError


def normalize_phone(phone: str) -> str:
    phone = phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if phone.startswith("8") and len(phone) == 11:
        phone = "+7" + phone[1:]
    if not phone.startswith("+"):
        phone = "+" + phone.lstrip("+")
    return phone


def describe_sent_code(sent, phone: str = "") -> str:
    type_name = type(sent.type).__name__.lower()
    if "app" in type_name:
        return (
            "Код отправлен В ПРИЛОЖЕНИЕ Telegram.\n"
            f"Откройте Telegram на телефоне {normalize_phone(phone)} → чат «Telegram».\n"
            "Это НЕ SMS! Смотрите уведомление внутри приложения."
        )
    if "sms" in type_name:
        return "Код отправлен SMS на ваш номер."
    if "call" in type_name:
        return "Код продиктуют голосовым звонком."
    if "email" in type_name:
        return "Код отправлен на привязанную почту."
    return f"Код запрошен (тип: {sent.type})."


async def send_login_code(client, phone: str, *, force_sms: bool = False):
    phone = normalize_phone(phone)
    try:
        sent = await client.send_code_request(phone, force_sms=force_sms)
    except FloodWaitError as exc:
        minutes = max(1, exc.seconds // 60)
        raise SystemExit(
            f"Telegram просит подождать {exc.seconds} сек (~{minutes} мин).\n"
            "Слишком много попыток входа. Подождите и запустите снова."
        ) from exc
    return phone, sent


def print_code_help(phone: str, sent_text: str) -> None:
    print("\n" + "=" * 50)
    print(sent_text)
    print("=" * 50)
    print(f"Номер: {normalize_phone(phone)}")
    print("  • Проверьте Telegram на ТОМ ЖЕ телефоне")
    print("  • Загляните в «Telegram» / «Избранное» / уведомления")
    print("  • При запросе введите s и Enter — пришлю SMS")
    print("=" * 50 + "\n")


def parse_code_input(raw: str) -> tuple[str, bool]:
    value = raw.strip().lower()
    if value in {"s", "sms", "с", "смс"}:
        return "", True
    digits = re.sub(r"\D", "", raw)
    return digits, False
