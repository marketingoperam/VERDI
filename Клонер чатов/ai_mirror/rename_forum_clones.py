"""Переименовать копии: «VERDI COMMUNITY | … Инстаграм 1» вместо «· копия 01»."""

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
from telethon.tl.functions.channels import EditTitleRequest

from clone_forum import session_path

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
LOCAL_SESSIONS = ROOT / "sessions"
LOCAL_SESSIONS.mkdir(exist_ok=True)
BATCH_FILE = ROOT / "forum_clones_batch.json"
TITLE_BASE = "VERDI COMMUNITY | Взаимная активность Инстаграм"

load_dotenv(SHADOWCHAT / ".env")


def isolated_session() -> str:
    src = Path(session_path() + ".session")
    dst = LOCAL_SESSIONS / "rename_batch.session"
    if src.exists():
        shutil.copy2(src, dst)
    return str(LOCAL_SESSIONS / "rename_batch")


def mirror_title(index: int) -> str:
    return f"{TITLE_BASE} {index}"


def load_batch() -> dict:
    return json.loads(BATCH_FILE.read_text(encoding="utf-8"))


def save_batch(data: dict) -> None:
    BATCH_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def run(start: int, end: int) -> None:
    batch = load_batch()
    by_index = {c["index"]: c for c in batch["clones"]}

    client = TelegramClient(
        isolated_session(),
        int(os.environ["LISTENER_API_ID"]),
        os.environ["LISTENER_API_HASH"],
    )
    await client.connect()
    if not await client.is_user_authorized():
        print("listener_main не авторизован")
        return

    print(f"Переименование групп {start}–{end}")

    for i in range(start, end + 1):
        clone = by_index.get(i)
        if not clone:
            print(f"[{i}] нет в batch — пропуск")
            continue
        new_title = mirror_title(i)
        if clone.get("mirror_title") == new_title:
            print(f"[{i}] уже «{new_title}»")
            continue
        mirror = await client.get_entity(int(clone["mirror_chat_id"]))
        print(f"[{i}] {clone.get('mirror_title')} → {new_title}")
        try:
            await client(EditTitleRequest(channel=mirror, title=new_title))
            clone["mirror_title"] = new_title
            save_batch(batch)
            await asyncio.sleep(8)
        except FloodWaitError as exc:
            print(f"  пауза {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 2)
            await client(EditTitleRequest(channel=mirror, title=new_title))
            clone["mirror_title"] = new_title
            save_batch(batch)
        except Exception as exc:
            err = str(exc)
            if "wasn't modified" in err or "NOT_MODIFIED" in err:
                clone["mirror_title"] = new_title
                save_batch(batch)
                print(f"  · уже «{new_title}»")
            else:
                print(f"  ✗ {exc}")

    await client.disconnect()
    print("Готово.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="start", type=int, default=1)
    p.add_argument("--to", dest="end", type=int, default=20)
    args = p.parse_args()
    asyncio.run(run(args.start, args.end))


if __name__ == "__main__":
    main()
