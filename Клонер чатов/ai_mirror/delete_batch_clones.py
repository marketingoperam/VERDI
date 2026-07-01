"""Удалить все копии из batch, оставить первую (forum_clone_state.json)."""

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
from telethon.tl.functions.channels import DeleteChannelRequest

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
    dst = LOCAL_SESSIONS / "delete_batch.session"
    if src.exists():
        shutil.copy2(src, dst)
    return str(LOCAL_SESSIONS / "delete_batch")


async def run(dry_run: bool) -> None:
    if not BATCH_FILE.exists():
        print("Нет forum_clones_batch.json")
        return

    keep_id = None
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        keep_id = int(state["mirror_chat_id"])
        print(f"Оставляем: {state.get('mirror_title')} (id={keep_id})")

    batch = json.loads(BATCH_FILE.read_text(encoding="utf-8"))
    to_delete = []
    for c in sorted(batch.get("clones", []), key=lambda x: x["index"]):
        cid = int(c["mirror_chat_id"])
        if keep_id and cid == keep_id:
            print(f"  пропуск (первая копия): [{c['index']}] {c.get('mirror_title')}")
            continue
        to_delete.append(c)

    print(f"Удалить: {len(to_delete)} групп")
    if dry_run:
        for c in to_delete:
            print(f"  [{c['index']}] {c.get('mirror_title')} id={c['mirror_chat_id']}")
        return

    client = TelegramClient(
        isolated_session(),
        int(os.environ["LISTENER_API_ID"]),
        os.environ["LISTENER_API_HASH"],
    )
    await client.connect()
    if not await client.is_user_authorized():
        print("listener_main не авторизован")
        return

    deleted = []
    for c in to_delete:
        i, title, cid = c["index"], c.get("mirror_title", ""), int(c["mirror_chat_id"])
        print(f"\n[{i}] удаляю: {title}")
        mirror = await client.get_entity(cid)
        try:
            await client(DeleteChannelRequest(channel=mirror))
            deleted.append(i)
            print("  ✓ удалено")
            await asyncio.sleep(10)
        except FloodWaitError as exc:
            print(f"  пауза {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 2)
            await client(DeleteChannelRequest(channel=mirror))
            deleted.append(i)
            print("  ✓ удалено")
            await asyncio.sleep(10)
        except Exception as exc:
            print(f"  ✗ {exc}")

    remaining = [c for c in batch["clones"] if c["index"] not in deleted]
    batch["clones"] = remaining
    batch["deleted_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    BATCH_FILE.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")

    await client.disconnect()
    print(f"\nГотово. Удалено: {len(deleted)}. Осталась первая копия.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    asyncio.run(run(args.dry_run))


if __name__ == "__main__":
    main()
