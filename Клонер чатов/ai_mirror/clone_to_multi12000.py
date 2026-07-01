"""Копирование legacy-групп VERDI в темы форума @multi12000."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
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
from telethon.tl.functions.messages import GetForumTopicsRequest
from telethon.tl.types import MessageService

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)

load_dotenv(SHADOWCHAT / ".env")

MIRROR = "multi12000"
STATE_FILE = ROOT / "verdi_multi12000_state.json"
DELAY = 0.3

# (источник, название темы в форуме)
ROUTES: list[tuple[int, str]] = [
    (-1001121968503, "Задания"),
    (-1001160095982, "Задания 2"),
    (-1001351711376, "Задания 3"),
    (-1001308213116, "Отчеты 1"),
    (-1001466065357, "Отчеты 2"),
    (-1001150352978, "Отчеты 3"),
]


def session_path() -> str:
    return str(SHADOWCHAT / "sessions" / "listener_main")


async def topic_ids_by_title(client: TelegramClient, forum) -> dict[str, int]:
    result = await client(
        GetForumTopicsRequest(
            peer=forum,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100,
        )
    )
    return {getattr(t, "title", ""): getattr(t, "id", 0) for t in result.topics}


async def copy_chat_to_topic(
    client: TelegramClient,
    source,
    mirror,
    dst_topic_id: int,
    state: dict,
    route_key: str,
) -> int:
    last_id = int(state.get("last_msg", {}).get(route_key, 0))
    copied = 0

    async for msg in client.iter_messages(source, reverse=True):
        if isinstance(msg, MessageService):
            continue
        if msg.id <= last_id:
            continue
        text = msg.message or ""
        try:
            if msg.media:
                path = await client.download_media(msg, file=str(CACHE / f"m_{msg.id}"))
                if path:
                    await client.send_file(
                        mirror,
                        path,
                        caption=text or None,
                        reply_to=dst_topic_id,
                    )
                    Path(path).unlink(missing_ok=True)
            elif text:
                await client.send_message(mirror, text, reply_to=dst_topic_id)
            else:
                continue
            copied += 1
            state.setdefault("last_msg", {})[route_key] = msg.id
            if copied % 50 == 0:
                print(f"    ... {copied}")
            await asyncio.sleep(DELAY)
        except FloodWaitError as exc:
            print(f"    flood wait {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 1)
        except Exception as exc:
            print(f"    пропуск #{msg.id}: {exc}")

    return copied


async def run(reset: bool) -> None:
    api_id = int(os.environ["LISTENER_API_ID"])
    api_hash = os.environ["LISTENER_API_HASH"]
    client = TelegramClient(session_path(), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("listener_main не авторизован")
        return

    me = await client.get_me()
    print(f"Аккаунт: {me.first_name} (@{me.username})")

    state: dict = {}
    if STATE_FILE.exists() and not reset:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    elif reset:
        STATE_FILE.unlink(missing_ok=True)

    mirror = await client.get_entity(MIRROR)
    topics = await topic_ids_by_title(client, mirror)
    print(f"Зеркало: {mirror.title} (@{mirror.username}) id={utils.get_peer_id(mirror)}")
    print("Темы:", ", ".join(f"{k}={v}" for k, v in topics.items()))

    total = 0
    for src_id, topic_title in ROUTES:
        dst_tid = topics.get(topic_title)
        if not dst_tid:
            print(f"\n✗ Нет темы «{topic_title}» в форуме — пропуск")
            continue
        source = await client.get_entity(src_id)
        key = f"{src_id}->{dst_tid}"
        print(f"\n→ {getattr(source, 'title', src_id)} → «{topic_title}» (topic {dst_tid})")
        n = await copy_chat_to_topic(client, source, mirror, dst_tid, state, key)
        total += n
        print(f"  скопировано: {n}")
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    state["mirror_chat_id"] = utils.get_peer_id(mirror)
    state["mirror_username"] = MIRROR
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nГотово. Всего сообщений: {total}")
    print(f"Форум: https://t.me/{MIRROR}")
    await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="Начать копирование с нуля")
    args = parser.parse_args()
    asyncio.run(run(args.reset))


if __name__ == "__main__":
    main()
