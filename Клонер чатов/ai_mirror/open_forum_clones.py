"""Сделать копии форума публичными: username multiverdichatN + открытый вход."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

import functools

print = functools.partial(print, flush=True)

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import (
    CheckUsernameRequest,
    ToggleJoinRequestRequest,
    TogglePreHistoryHiddenRequest,
    UpdateUsernameRequest,
)

from clone_forum import session_path

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
LOCAL_SESSIONS = ROOT / "sessions"
LOCAL_SESSIONS.mkdir(exist_ok=True)
BATCH_FILE = ROOT / "forum_clones_batch.json"
USERNAME_PREFIX = "multiverdichat"

load_dotenv(SHADOWCHAT / ".env")


def isolated_session() -> str:
    src = Path(session_path() + ".session")
    dst = LOCAL_SESSIONS / "open_batch.session"
    if src.exists():
        shutil.copy2(src, dst)
    return str(LOCAL_SESSIONS / "open_batch")


def load_batch() -> dict:
    return json.loads(BATCH_FILE.read_text(encoding="utf-8"))


def save_batch(data: dict) -> None:
    BATCH_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def open_group(client: TelegramClient, mirror, username: str) -> str:
    for req, label in (
        (ToggleJoinRequestRequest(channel=mirror, enabled=False), "вход без заявок"),
        (TogglePreHistoryHiddenRequest(channel=mirror, enabled=False), "история видна"),
    ):
        try:
            await client(req)
            print(f"    ✓ {label}")
            await asyncio.sleep(0.4)
        except Exception as exc:
            err = str(exc)
            if "NOT_MODIFIED" not in err:
                print(f"    · {label}: {exc}")

    available = await client(CheckUsernameRequest(channel=mirror, username=username))
    if not available:
        raise RuntimeError(f"username @{username} занят или недоступен")

    await client(UpdateUsernameRequest(channel=mirror, username=username))
    return f"https://t.me/{username}"


async def run(start: int, end: int, resume: bool) -> None:
    if not BATCH_FILE.exists():
        print("Нет forum_clones_batch.json")
        return

    batch = load_batch()
    clones = sorted(batch["clones"], key=lambda c: c["index"])
    targets = [c for c in clones if start <= c["index"] <= end]

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
    print(f"Групп: {len(targets)} ({USERNAME_PREFIX}{start} … {USERNAME_PREFIX}{end})")

    by_index = {c["index"]: c for c in batch["clones"]}

    for clone in targets:
        i = clone["index"]
        if resume and clone.get("username"):
            print(f"\n[{i}] @{clone['username']} — уже есть")
            continue
        username = f"{USERNAME_PREFIX}{i}"
        title = clone.get("mirror_title", f"копия {i:02d}")
        print(f"\n[{i}] {title}")
        mirror = await client.get_entity(int(clone["mirror_chat_id"]))
        try:
            link = await open_group(client, mirror, username)
            by_index[i]["username"] = username
            by_index[i]["public_link"] = link
            print(f"    ✓ @{username}  {link}")
            batch["clones"] = [by_index[c["index"]] for c in sorted(by_index.values(), key=lambda x: x["index"])]
            save_batch(batch)
            await asyncio.sleep(45)
        except FloodWaitError as exc:
            print(f"    пауза {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 2)
            link = await open_group(client, mirror, username)
            by_index[i]["username"] = username
            by_index[i]["public_link"] = link
            print(f"    ✓ @{username}  {link}")
            batch["clones"] = [by_index[c["index"]] for c in sorted(by_index.values(), key=lambda x: x["index"])]
            save_batch(batch)
        except Exception as exc:
            print(f"    ✗ {exc}")

    print("\nГотово. Ссылки:")
    for c in sorted(batch["clones"], key=lambda x: x["index"]):
        if start <= c["index"] <= end:
            u = c.get("public_link") or c.get("username", "—")
            print(f"  {c['index']:02d}. {u}")

    await client.disconnect()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", type=int, default=1)
    p.add_argument("--to", dest="end", type=int, default=20)
    p.add_argument("--resume", action="store_true", help="Пропустить уже настроенные")
    args = p.parse_args()
    asyncio.run(run(args.start, args.end, args.resume))


if __name__ == "__main__":
    main()
