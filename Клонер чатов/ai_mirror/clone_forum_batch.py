"""Создать несколько копий форума @multi12000 (темы + сообщения)."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
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
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import ExportChatInviteRequest

from clone_forum import (
    SOURCE,
    copy_topic,
    create_forum_copy,
    ensure_topics,
    get_topic_tops,
    get_topics,
    session_path,
    sync_topic_flags,
)

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
BATCH_FILE = ROOT / "forum_clones_batch.json"

load_dotenv(SHADOWCHAT / ".env")

GROUP_PAUSE = 15.0


async def wait_flood(exc: FloodWaitError) -> None:
    print(f"  пауза Telegram: {exc.seconds}s")
    await asyncio.sleep(exc.seconds + 2)


def load_batch() -> dict:
    if BATCH_FILE.exists():
        return json.loads(BATCH_FILE.read_text(encoding="utf-8"))
    return {"source": SOURCE, "clones": [], "target_count": 20}


def save_batch(data: dict) -> None:
    BATCH_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def invite_link(client: TelegramClient, mirror) -> str | None:
    try:
        r = await client(ExportChatInviteRequest(peer=mirror))
        return getattr(r, "link", None)
    except Exception:
        return None


async def clone_one(
    client: TelegramClient,
    source,
    source_topics,
    topic_tops: dict[int, int],
    src_title: str,
    index: int,
) -> dict:
    title = f"{src_title} {index}"
    print(f"\n{'=' * 50}")
    print(f"Группа {index}: {title}")
    print("=" * 50)

    mirror = await create_forum_copy(client, title)
    topic_map = await ensure_topics(client, mirror, source_topics)
    await sync_topic_flags(client, mirror, source_topics, topic_map)

    state: dict = {
        "index": index,
        "source": SOURCE,
        "mirror_chat_id": utils.get_peer_id(mirror),
        "mirror_title": getattr(mirror, "title", title),
        "topic_map": {str(k): v for k, v in topic_map.items()},
        "last_msg": {},
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "messages_copied": 0,
    }

    total = 0
    for info in source_topics:
        dst_tid = topic_map.get(info.id)
        if not dst_tid:
            continue
        n = await copy_topic(client, source, mirror, info.id, dst_tid, state, topic_tops)
        total += n
        if n:
            print(f"  «{info.title}»: {n} сообщ.")

    state["messages_copied"] = total
    state["invite_link"] = await invite_link(client, mirror)
    print(f"  id={state['mirror_chat_id']}  сообщений={total}")
    if state["invite_link"]:
        print(f"  ссылка: {state['invite_link']}")
    return state


async def run(count: int, resume: bool) -> None:
    client = TelegramClient(
        session_path(),
        int(os.environ["LISTENER_API_ID"]),
        os.environ["LISTENER_API_HASH"],
    )
    await client.connect()
    if not await client.is_user_authorized():
        print("listener_main не авторизован")
        return

    me = await client.get_me()
    print(f"Аккаунт: {me.first_name} (@{me.username})")

    batch = load_batch()
    batch["target_count"] = count
    done = {c["index"] for c in batch["clones"]} if resume else set()

    if not resume:
        batch["clones"] = []
        done = set()

    source = await client.get_entity(SOURCE)
    src_title = getattr(source, "title", SOURCE)
    source_topics = await get_topics(client, source)
    topic_tops = await get_topic_tops(client, source)

    print(f"Источник: {src_title} — тем: {len(source_topics)}")
    print(f"Цель: {count} копий, уже готово: {len(done)}")

    for i in range(1, count + 1):
        if i in done:
            print(f"\n[{i}/{count}] уже есть — пропуск")
            continue
        try:
            state = await clone_one(client, source, source_topics, topic_tops, src_title, i)
            batch["clones"].append(state)
            save_batch(batch)
            if i < count:
                await asyncio.sleep(GROUP_PAUSE)
        except FloodWaitError as exc:
            await wait_flood(exc)
            state = await clone_one(client, source, source_topics, topic_tops, src_title, i)
            batch["clones"].append(state)
            save_batch(batch)
            if i < count:
                await asyncio.sleep(GROUP_PAUSE)
        except Exception as exc:
            print(f"✗ Ошибка на группе {i}: {exc}")
            save_batch(batch)
            raise

    print(f"\nГотово: {len(batch['clones'])}/{count} групп")
    print(f"Список: {BATCH_FILE}")
    for c in sorted(batch["clones"], key=lambda x: x["index"]):
        link = c.get("invite_link") or "—"
        print(f"  {c['index']:02d}. {c['mirror_title']}  {link}")

    await client.disconnect()


def main() -> None:
    p = argparse.ArgumentParser(description="Пакетное клонирование форума")
    p.add_argument("--count", type=int, default=20, help="Сколько групп создать")
    p.add_argument("--resume", action="store_true", help="Продолжить с места остановки")
    args = p.parse_args()
    asyncio.run(run(args.count, args.resume))


if __name__ == "__main__":
    main()
