"""Полное копирование форума VERDI COMMUNITY в новую группу-зеркало."""

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
from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError
from telethon.tl.functions.channels import CreateChannelRequest, ToggleForumRequest
from telethon.tl.functions.messages import CreateForumTopicRequest, GetForumTopicsRequest
from telethon.tl.types import MessageService

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
sys.path.insert(0, str(SHADOWCHAT))

load_dotenv(SHADOWCHAT / ".env")

SOURCE_FORUM_ID = -1004290058836
DEFAULT_MIRROR_TITLE = "VERDI COMMUNITY | Копия"
STATE_FILE = ROOT / "verdi_clone_state.json"
DELAY = 0.35


def session_path() -> str:
    return str(SHADOWCHAT / "sessions" / "listener_main")


async def get_topics(client: TelegramClient, peer) -> dict[str, int]:
    result = await client(
        GetForumTopicsRequest(
            peer=peer,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100,
        )
    )
    out: dict[str, int] = {}
    for topic in result.topics:
        title = getattr(topic, "title", None)
        tid = getattr(topic, "id", None)
        if title and tid:
            out[title] = tid
    return out


async def ensure_mirror_forum(client: TelegramClient, title: str, state: dict) -> tuple:
    if state.get("mirror_chat_id"):
        mirror = await client.get_entity(int(state["mirror_chat_id"]))
        print(f"Зеркало уже есть: {getattr(mirror, 'title', mirror.id)} ({mirror.id})")
        return mirror, state.get("topic_map", {})

    print(f"Создаю форум: {title}")
    created = await client(
        CreateChannelRequest(
            title=title,
            about="Автокопия VERDI COMMUNITY",
            megagroup=True,
        )
    )
    mirror = created.chats[0]
    await client(ToggleForumRequest(channel=mirror, enabled=True, tabs=False))
    await asyncio.sleep(2)
    mirror = await client.get_entity(mirror.id)
    print(f"Создан форум id={mirror.id}")
    return mirror, {}


async def ensure_mirror_topics(
    client: TelegramClient, mirror, source_topics: dict[str, int], existing_map: dict
) -> dict[str, int]:
    mirror_topics = await get_topics(client, mirror)
    topic_map: dict[str, int] = {}

    for title, src_id in source_topics.items():
        if title in mirror_topics:
            topic_map[str(src_id)] = mirror_topics[title]
            continue
        if title == "General":
            topic_map[str(src_id)] = mirror_topics.get("General", 1)
            continue
        print(f"  Создаю тему: {title}")
        await client(CreateForumTopicRequest(peer=mirror, title=title, icon_color=0x6FB9F0))
        await asyncio.sleep(1.5)
        mirror_topics = await get_topics(client, mirror)
        topic_map[str(src_id)] = mirror_topics[title]

    return topic_map


async def copy_topic_messages(
    client: TelegramClient,
    source,
    mirror,
    src_topic_id: int,
    dst_topic_id: int,
    state: dict,
    *,
    limit: int | None = None,
) -> int:
    key = f"{source.id}:{src_topic_id}"
    last_id = int(state.get("last_msg", {}).get(key, 0))
    copied = 0

    async for msg in client.iter_messages(source, reverse=True, limit=limit):
        if isinstance(msg, MessageService):
            continue
        if src_topic_id == 1:
            if msg.reply_to and getattr(msg.reply_to, "reply_to_top_id", None):
                continue
        else:
            top = getattr(msg.reply_to, "reply_to_top_id", None) if msg.reply_to else None
            if top != src_topic_id:
                continue
        if msg.id <= last_id:
            continue

        text = msg.message or ""
        try:
            if msg.media:
                path = await client.download_media(msg, file=str(ROOT / "cache" / f"bf_{msg.id}"))
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
            state.setdefault("last_msg", {})[key] = msg.id
            if copied % 25 == 0:
                print(f"    ... {copied} сообщений")
            await asyncio.sleep(DELAY)
        except FloodWaitError as exc:
            print(f"    flood wait {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 1)
        except Exception as exc:
            print(f"    пропуск msg {msg.id}: {exc}")

    return copied


async def run(mirror_title: str, live: bool) -> None:
    api_id = int(os.environ["LISTENER_API_ID"])
    api_hash = os.environ["LISTENER_API_HASH"]
    client = TelegramClient(session_path(), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        print("listener_main не авторизован")
        return

    me = await client.get_me()
    print(f"Аккаунт: {me.first_name} (@{me.username})")

    state = {}
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    source = await client.get_entity(SOURCE_FORUM_ID)
    print(f"Источник: {getattr(source, 'title', source.id)}")

    source_topics = await get_topics(client, source)
    print("Темы источника:")
    for t, i in source_topics.items():
        print(f"  {i}: {t}")

    mirror, _ = await ensure_mirror_forum(client, mirror_title, state)
    state["mirror_chat_id"] = utils.get_peer_id(mirror)

    topic_map = await ensure_mirror_topics(client, mirror, source_topics, state.get("topic_map", {}))
    state["topic_map"] = {str(k): v for k, v in topic_map.items()}
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    total = 0
    for title, src_tid in source_topics.items():
        dst_tid = topic_map.get(str(src_tid))
        if not dst_tid:
            print(f"Пропуск темы {title} — нет зеркала")
            continue
        print(f"\nКопирую тему «{title}» ({src_tid} → {dst_tid})...")
        n = await copy_topic_messages(client, source, mirror, src_tid, dst_tid, state)
        total += n
        print(f"  Готово: {n} сообщений")
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nВсего скопировано: {total}")
    print(f"Зеркало: {getattr(mirror, 'title', mirror.id)} id={state['mirror_chat_id']}")
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    if live:
        print("\nЗапустите live-клонер с multi_config.verdi.json")

    await client.disconnect()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default=DEFAULT_MIRROR_TITLE)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    asyncio.run(run(args.title, args.live))


if __name__ == "__main__":
    main()
