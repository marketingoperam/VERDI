"""Приглашение пользователей в один конкретный чат (остальные чаты мультичата не затрагиваются)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

import functools

print = functools.partial(print, flush=True)

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import (
    ChatAdminRequiredError,
    FloodWaitError,
    UserAlreadyParticipantError,
    UserNotMutualContactError,
    UserPrivacyRestrictedError,
)
from telethon.tl.functions.channels import InviteToChannelRequest
from telethon.tl.functions.messages import AddChatUserRequest
from telethon.tl.types import Channel, Chat, User

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
sys.path.insert(0, str(SHADOWCHAT))

load_dotenv(ROOT / ".env")
load_dotenv(SHADOWCHAT / ".env")


def api_credentials() -> tuple[int, str]:
    return int(os.environ["LISTENER_API_ID"]), os.environ["LISTENER_API_HASH"]


def session_path(session_name: str) -> str:
    for base in (SHADOWCHAT / "sessions", ROOT / "sessions"):
        path = base / f"{session_name}.session"
        if path.exists():
            return str(base / session_name)
    return str(SHADOWCHAT / "sessions" / session_name)


def load_users(config: dict, users_file: str | None) -> list[str]:
    if users_file:
        lines = Path(users_file).read_text(encoding="utf-8").splitlines()
        return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]
    return [str(u).strip() for u in config.get("users", []) if str(u).strip()]


async def resolve_user(client: TelegramClient, ref: str) -> User:
    ref = ref.strip()
    if ref.startswith("+"):
        ref = ref if ref.startswith("+") else f"+{ref}"
    elif ref.isdigit():
        ref = int(ref)
    entity = await client.get_entity(ref)
    if not isinstance(entity, User):
        raise ValueError(f"{ref!r} — не пользователь")
    return entity


async def invite_one(client: TelegramClient, chat, user: User) -> str:
    if isinstance(chat, Channel):
        await client(InviteToChannelRequest(chat, [user]))
        return "приглашён"
    if isinstance(chat, Chat):
        await client(AddChatUserRequest(chat_id=chat.id, user_id=user, fwd_limit=0))
        return "добавлен"
    raise TypeError(f"Неподдерживаемый тип чата: {type(chat).__name__}")


async def run(config_path: Path, users_file: str | None, dry_run: bool) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    session_name = config["session_name"]
    target_ref = config.get("target_chat_id") or config.get("target_chat")
    if target_ref is None:
        raise ValueError("Укажите target_chat_id или target_chat в конфиге")

    users_raw = load_users(config, users_file)
    if not users_raw:
        raise ValueError("Список users пуст — добавьте в конфиг или передайте --users-file")

    delay = float(config.get("delay_seconds", 3))
    api_id, api_hash = api_credentials()

    client = TelegramClient(session_path(session_name), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("Аккаунт не авторизован.")
        return

    me = await client.get_me()
    chat = await client.get_entity(target_ref)
    title = getattr(chat, "title", target_ref)
    label = config.get("target_chat_title") or title

    print("=" * 48)
    print("  Инвайт в один чат")
    print("=" * 48)
    print(f"Аккаунт: {me.first_name} ({me.phone})")
    print(f"Целевой чат: {label} (id={getattr(chat, 'id', target_ref)})")
    print(f"Пользователей в очереди: {len(users_raw)}")
    if dry_run:
        print("\n[DRY RUN] Инвайты не отправляются.\n")
    print()

    ok = skip = fail = 0

    for ref in users_raw:
        name = ref
        try:
            user = await resolve_user(client, ref)
            name = " ".join(p for p in (user.first_name, user.last_name) if p) or ref
            if user.username:
                name += f" @{user.username}"

            if dry_run:
                print(f"  [dry] {name}")
                ok += 1
                continue

            status = await invite_one(client, chat, user)
            print(f"  ✓ {name} — {status}")
            ok += 1
        except UserAlreadyParticipantError:
            print(f"  — {name} — уже в чате")
            skip += 1
        except UserPrivacyRestrictedError:
            print(f"  ✗ {name} — закрыл инвайты в настройках")
            fail += 1
        except UserNotMutualContactError:
            print(f"  ✗ {name} — не в контактах (нужен взаимный контакт или ссылка)")
            fail += 1
        except ChatAdminRequiredError:
            print(f"  ✗ {name} — нет прав админа с «добавлять участников»")
            fail += 1
        except FloodWaitError as exc:
            print(f"  ⏳ flood wait {exc.seconds}s — пауза...")
            await asyncio.sleep(exc.seconds + 1)
            try:
                status = await invite_one(client, chat, await resolve_user(client, ref))
                print(f"  ✓ {name} — {status} (после паузы)")
                ok += 1
            except Exception as retry_exc:
                print(f"  ✗ {name} — {retry_exc}")
                fail += 1
        except Exception as exc:
            print(f"  ✗ {name} — {exc}")
            fail += 1

        if not dry_run and ref != users_raw[-1]:
            await asyncio.sleep(delay)

    print()
    print(f"Готово: успешно {ok}, пропущено {skip}, ошибок {fail}")
    await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Пригласить пользователей только в один чат из мультичата"
    )
    parser.add_argument(
        "--config",
        default=str(ROOT / "invite_config.json"),
        help="Путь к invite_config.json",
    )
    parser.add_argument(
        "--users-file",
        help="Файл со списком @username (по одному на строку)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Проверить список без отправки инвайтов",
    )
    args = parser.parse_args()
    asyncio.run(run(Path(args.config), args.users_file, args.dry_run))


if __name__ == "__main__":
    main()
