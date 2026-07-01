"""Отключить режим форума (темы) — сделать обычными группами."""

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
from telethon.tl.functions.channels import ToggleForumRequest

from clone_forum import session_path

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
LOCAL_SESSIONS = ROOT / "sessions"
LOCAL_SESSIONS.mkdir(exist_ok=True)
BATCH_FILE = ROOT / "forum_clones_batch.json"
STATE_FILE = ROOT / "forum_clone_state.json"

load_dotenv(SHADOWCHAT / ".env")


def isolated_session() -> str:
    src = Path(session_path() + ".session")
    dst = LOCAL_SESSIONS / "disable_forum.session"
    if src.exists():
        shutil.copy2(src, dst)
    return str(LOCAL_SESSIONS / "disable_forum")


def collect_groups(include_original: bool) -> list[dict]:
    items: list[dict] = []
    if BATCH_FILE.exists():
        batch = json.loads(BATCH_FILE.read_text(encoding="utf-8"))
        for c in batch.get("clones", []):
            items.append(
                {
                    "index": c["index"],
                    "mirror_chat_id": c["mirror_chat_id"],
                    "mirror_title": c.get("mirror_title", ""),
                }
            )
    if include_original and STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if state.get("mirror_chat_id"):
            items.append(
                {
                    "index": 0,
                    "mirror_chat_id": state["mirror_chat_id"],
                    "mirror_title": state.get("mirror_title", "оригинальная копия"),
                }
            )
    return sorted(items, key=lambda x: x["index"])


async def disable_forum(client: TelegramClient, mirror) -> None:
    await client(ToggleForumRequest(channel=mirror, enabled=False, tabs=False))


async def run(start: int, end: int, include_original: bool) -> None:
    groups = [g for g in collect_groups(include_original) if start <= g["index"] <= end or g["index"] == 0]

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
    print(f"Групп: {len(groups)}")

    for g in groups:
        label = g["index"] if g["index"] else "orig"
        print(f"\n[{label}] {g['mirror_title']}")
        mirror = await client.get_entity(int(g["mirror_chat_id"]))
        if not getattr(mirror, "forum", False):
            print("  · уже обычная группа")
            continue
        try:
            await disable_forum(client, mirror)
            print("  ✓ темы отключены")
            await asyncio.sleep(8)
        except FloodWaitError as exc:
            print(f"  пауза {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 2)
            await disable_forum(client, mirror)
            print("  ✓ темы отключены")
            await asyncio.sleep(8)
        except Exception as exc:
            err = str(exc)
            if "NOT_MODIFIED" in err or "wasn't modified" in err:
                print("  · уже обычная группа")
            else:
                print(f"  ✗ {exc}")

    await client.disconnect()
    print("\nГотово.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", type=int, default=1)
    p.add_argument("--to", dest="end", type=int, default=20)
    p.add_argument("--include-original", action="store_true")
    args = p.parse_args()
    asyncio.run(run(args.start, args.end, args.include_original))


if __name__ == "__main__":
    main()
