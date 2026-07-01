"""Поставить одну аватарку во все копии форума."""

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
from telethon.tl.functions.channels import EditPhotoRequest
from telethon.tl.types import InputChatUploadedPhoto

from clone_forum import session_path

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
LOCAL_SESSIONS = ROOT / "sessions"
LOCAL_SESSIONS.mkdir(exist_ok=True)
BATCH_FILE = ROOT / "forum_clones_batch.json"
DEFAULT_AVATAR = ROOT / "verdi_avatar.png"

load_dotenv(SHADOWCHAT / ".env")


def isolated_session() -> str:
    src = Path(session_path() + ".session")
    dst = LOCAL_SESSIONS / "avatar_batch.session"
    if src.exists():
        shutil.copy2(src, dst)
    return str(LOCAL_SESSIONS / "avatar_batch")


async def set_avatar(client: TelegramClient, mirror, photo_path: Path) -> None:
    uploaded = await client.upload_file(str(photo_path))
    await client(
        EditPhotoRequest(
            channel=mirror,
            photo=InputChatUploadedPhoto(file=uploaded),
        )
    )


async def run(photo_path: Path, start: int, end: int) -> None:
    batch = json.loads(BATCH_FILE.read_text(encoding="utf-8"))
    targets = [c for c in batch["clones"] if start <= c["index"] <= end]

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
    print(f"Аватар: {photo_path}")
    print(f"Групп: {len(targets)}")

    for clone in sorted(targets, key=lambda c: c["index"]):
        i = clone["index"]
        title = clone.get("mirror_title", f"#{i}")
        print(f"\n[{i}] {title}")
        mirror = await client.get_entity(int(clone["mirror_chat_id"]))
        try:
            await set_avatar(client, mirror, photo_path)
            print("  ✓ аватар установлен")
            await asyncio.sleep(5)
        except FloodWaitError as exc:
            print(f"  пауза {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 2)
            await set_avatar(client, mirror, photo_path)
            print("  ✓ аватар установлен")
            await asyncio.sleep(5)
        except Exception as exc:
            print(f"  ✗ {exc}")

    await client.disconnect()
    print("\nГотово.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--photo", default=str(DEFAULT_AVATAR))
    p.add_argument("--from", dest="start", type=int, default=1)
    p.add_argument("--to", dest="end", type=int, default=20)
    args = p.parse_args()
    photo = Path(args.photo)
    if not photo.exists():
        print(f"Файл не найден: {photo}")
        sys.exit(1)
    asyncio.run(run(photo, args.start, args.end))


if __name__ == "__main__":
    main()
