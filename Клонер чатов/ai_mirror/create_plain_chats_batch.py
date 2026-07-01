"""Создать N обычных публичных чатов: аватар, правила, закреп."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import uuid
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

import functools

print = functools.partial(print, flush=True)

from dotenv import load_dotenv
from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.functions.channels import (
    CheckUsernameRequest,
    CreateChannelRequest,
    EditPhotoRequest,
    ToggleJoinRequestRequest,
    TogglePreHistoryHiddenRequest,
    UpdateUsernameRequest,
)

from telethon.tl.types import InputChatUploadedPhoto

from clone_forum import session_path
from setup_rules import DEFAULT_AVATAR, RULES, api_call

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
LOCAL_SESSIONS = ROOT / "sessions"
LOCAL_SESSIONS.mkdir(exist_ok=True)
BATCH_FILE = ROOT / "forum_clones_batch.json"
TITLE_BASE = "VERDI COMMUNITY | Взаимная активность Инстаграм"
USERNAME_PREFIX = "multiverdichat"
CREATE_DELAY = 12
OPEN_DELAY = 45

load_dotenv(SHADOWCHAT / ".env")


def isolated_session() -> str:
    src = Path(session_path() + ".session")
    dst = LOCAL_SESSIONS / f"plain_batch_{uuid.uuid4().hex[:8]}.session"
    if src.exists():
        shutil.copy2(src, dst)
    return str(dst.with_suffix(""))


def load_batch() -> dict:
    if BATCH_FILE.exists():
        return json.loads(BATCH_FILE.read_text(encoding="utf-8"))
    return {"clones": [], "target_count": 20}


def save_batch(data: dict) -> None:
    BATCH_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def mirror_title(index: int) -> str:
    return f"{TITLE_BASE} {index}"


async def set_avatar(client: TelegramClient, mirror, photo_path: Path) -> None:
    uploaded = await client.upload_file(str(photo_path))
    await api_call(
        client,
        EditPhotoRequest(channel=mirror, photo=InputChatUploadedPhoto(file=uploaded)),
        "аватар",
    )


async def post_and_pin(client: TelegramClient, mirror) -> int:
    msg = await client.send_message(mirror, RULES)
    await asyncio.sleep(2)
    try:
        await client.pin_message(mirror, msg, notify=False)
    except RPCError:
        from telethon.tl.functions.messages import UpdatePinnedMessageRequest

        await api_call(
            client,
            UpdatePinnedMessageRequest(peer=mirror, id=msg.id, silent=True),
            "закреп",
        )
    return msg.id


async def open_group(client: TelegramClient, mirror, username: str) -> str:
    for req, label in (
        (ToggleJoinRequestRequest(channel=mirror, enabled=False), "вход без заявок"),
        (TogglePreHistoryHiddenRequest(channel=mirror, enabled=False), "история видна"),
    ):
        try:
            await client(req)
            await asyncio.sleep(0.4)
        except Exception as exc:
            if "NOT_MODIFIED" not in str(exc):
                print(f"    · {label}: {exc}")

    available = await client(CheckUsernameRequest(channel=mirror, username=username))
    if not available:
        raise RuntimeError(f"username @{username} занят или недоступен")

    await api_call(client, UpdateUsernameRequest(channel=mirror, username=username), "username")
    return f"https://t.me/{username}"


async def find_chat_by_title(client: TelegramClient, title: str):
    async for dialog in client.iter_dialogs():
        if dialog.title == title:
            return await client.get_entity(dialog.id)
    return None


async def complete_public(client: TelegramClient, mirror, index: int) -> dict:
    username = f"{USERNAME_PREFIX}{index}"
    title = mirror_title(index)
    print(f"\n[{index}] доделываю {title}")
    link = await open_group(client, mirror, username)
    print(f"    ✓ @{username}  {link}")
    return {
        "index": index,
        "mirror_chat_id": utils.get_peer_id(mirror),
        "mirror_title": title,
        "username": username,
        "public_link": link,
        "rules_msg_id": 3,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


async def create_one(client: TelegramClient, index: int, avatar: Path) -> dict:
    title = mirror_title(index)
    username = f"{USERNAME_PREFIX}{index}"
    print(f"\n[{index}] {title}")

    result = await api_call(
        client,
        CreateChannelRequest(title=title, megagroup=True, about=""),
        "создание",
    )
    mirror = await client.get_entity(result.chats[0])
    chat_id = utils.get_peer_id(mirror)

    await set_avatar(client, mirror, avatar)
    print("    ✓ аватар")
    mid = await post_and_pin(client, mirror)
    print(f"    ✓ правила закреплены (#{mid})")
    link = await open_group(client, mirror, username)
    print(f"    ✓ @{username}  {link}")

    return {
        "index": index,
        "mirror_chat_id": chat_id,
        "mirror_title": title,
        "username": username,
        "public_link": link,
        "rules_msg_id": mid,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


async def run(start: int, end: int, resume: bool) -> None:
    if not DEFAULT_AVATAR.exists():
        print(f"Нет аватарки: {DEFAULT_AVATAR}")
        return

    batch = load_batch()
    by_index = {c["index"]: c for c in batch.get("clones", [])}

    client = TelegramClient(
        isolated_session(),
        int(os.environ["LISTENER_API_ID"]),
        os.environ["LISTENER_API_HASH"],
    )
    await client.connect()
    if not await client.is_user_authorized():
        print("listener_main не авторизован")
        return

    me = await client.get_me()
    print(f"Аккаунт: {me.first_name} (@{me.username})")
    print(f"Создать чатов: {end - start + 1} ({start}…{end})")

    for i in range(start, end + 1):
        if resume and by_index.get(i, {}).get("public_link"):
            print(f"\n[{i}] уже есть — {by_index[i]['public_link']}")
            continue

        title = mirror_title(i)
        partial = await find_chat_by_title(client, title)
        if partial and not getattr(partial, "username", None):
            try:
                entry = await complete_public(client, partial, i)
                by_index[i] = entry
                batch["clones"] = [by_index[k] for k in sorted(by_index)]
                batch["target_count"] = end
                batch["plain_chats"] = True
                batch["updated_at"] = datetime.now().isoformat(timespec="seconds")
                save_batch(batch)
                await asyncio.sleep(OPEN_DELAY)
                continue
            except FloodWaitError as exc:
                print(f"    пауза {exc.seconds}s")
                await asyncio.sleep(exc.seconds + 2)
                entry = await complete_public(client, partial, i)
                by_index[i] = entry
                batch["clones"] = [by_index[k] for k in sorted(by_index)]
                batch["target_count"] = end
                batch["plain_chats"] = True
                save_batch(batch)
                await asyncio.sleep(OPEN_DELAY)
                continue
            except Exception as exc:
                print(f"    ✗ доделка: {exc}")

        if partial and getattr(partial, "username", None):
            link = f"https://t.me/{partial.username}"
            print(f"\n[{i}] найден @{partial.username}")
            by_index[i] = {
                "index": i,
                "mirror_chat_id": utils.get_peer_id(partial),
                "mirror_title": title,
                "username": partial.username,
                "public_link": link,
                "rules_msg_id": 3,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            batch["clones"] = [by_index[k] for k in sorted(by_index)]
            batch["target_count"] = end
            save_batch(batch)
            continue

        try:
            entry = await create_one(client, i, DEFAULT_AVATAR)
            by_index[i] = entry
            batch["clones"] = [by_index[k] for k in sorted(by_index)]
            batch["target_count"] = end
            batch["plain_chats"] = True
            batch["updated_at"] = datetime.now().isoformat(timespec="seconds")
            save_batch(batch)
            await asyncio.sleep(OPEN_DELAY)
        except FloodWaitError as exc:
            print(f"    пауза {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 2)
            entry = await create_one(client, i, DEFAULT_AVATAR)
            by_index[i] = entry
            batch["clones"] = [by_index[k] for k in sorted(by_index)]
            batch["target_count"] = end
            batch["plain_chats"] = True
            save_batch(batch)
            await asyncio.sleep(OPEN_DELAY)
        except Exception as exc:
            print(f"    ✗ {exc}")
            await asyncio.sleep(CREATE_DELAY)

    await client.disconnect()
    print("\nГотово. Ссылки:")
    for c in sorted(batch.get("clones", []), key=lambda x: x["index"]):
        if start <= c["index"] <= end:
            print(f"  {c['index']:02d}. {c.get('public_link', '—')}")


def main() -> None:
    p = argparse.ArgumentParser(description="Публичные чаты VERDI")
    p.add_argument("--from", dest="start", type=int, default=1)
    p.add_argument("--to", dest="end", type=int, default=10)
    p.add_argument("--resume", action="store_true")
    args = p.parse_args()
    asyncio.run(run(args.start, args.end, args.resume))


if __name__ == "__main__":
    main()
