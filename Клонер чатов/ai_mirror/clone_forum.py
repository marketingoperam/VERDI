"""Создать новый форум-клон @multi12000: все темы + все сообщения."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
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
from telethon.tl.functions.channels import CreateChannelRequest, ToggleForumRequest
from telethon.tl.functions.messages import (
    CreateForumTopicRequest,
    EditForumTopicRequest,
    GetForumTopicsRequest,
    UpdatePinnedForumTopicRequest,
)
from telethon.tl.types import MessageService

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)

load_dotenv(SHADOWCHAT / ".env")

SOURCE = "multi12000"
STATE_FILE = ROOT / "forum_clone_state.json"
DELAY = 0.3


def session_path() -> str:
    return str(SHADOWCHAT / "sessions" / "listener_main")


@dataclass
class TopicInfo:
    id: int
    title: str
    icon_color: int = 0x6FB9F0
    icon_emoji_id: int | None = None
    pinned: bool = False
    closed: bool = False


async def get_topics(client: TelegramClient, peer) -> list[TopicInfo]:
    result = await client(
        GetForumTopicsRequest(
            peer=peer,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100,
        )
    )
    items: list[TopicInfo] = []
    for topic in result.topics:
        title = getattr(topic, "title", None)
        tid = getattr(topic, "id", None)
        if title and tid:
            items.append(
                TopicInfo(
                    id=tid,
                    title=title,
                    icon_color=getattr(topic, "icon_color", 0x6FB9F0) or 0x6FB9F0,
                    icon_emoji_id=getattr(topic, "icon_emoji_id", None) or None,
                    pinned=bool(getattr(topic, "pinned", False)),
                    closed=bool(getattr(topic, "closed", False)),
                )
            )
    return items


async def create_topic(client, mirror, info: TopicInfo) -> None:
    kwargs: dict = {"peer": mirror, "title": info.title, "icon_color": info.icon_color}
    if info.icon_emoji_id:
        kwargs["icon_emoji_id"] = info.icon_emoji_id
    await client(CreateForumTopicRequest(**kwargs))


async def update_topic(client, mirror, topic_id: int, info: TopicInfo, title: bool, icon: bool) -> None:
    kwargs: dict = {"peer": mirror, "topic_id": topic_id}
    if title:
        kwargs["title"] = info.title
    if icon and info.icon_emoji_id:
        kwargs["icon_emoji_id"] = info.icon_emoji_id
    if len(kwargs) > 2:
        await client(EditForumTopicRequest(**kwargs))


async def ensure_topics(
    client,
    mirror,
    source_topics: list[TopicInfo],
    existing_map: dict[int, int] | None = None,
) -> dict[int, int]:
    mirror_topics = await get_topics(client, mirror)
    mirror_by_id = {t.id: t for t in mirror_topics}
    mirror_by_title = {t.title: t.id for t in mirror_topics}
    topic_map: dict[int, int] = {}
    existing_map = existing_map or {}

    for info in source_topics:
        if info.title == "General":
            topic_map[info.id] = mirror_by_title.get("General", 1)
            continue

        dst_id = existing_map.get(info.id)
        if dst_id and dst_id in mirror_by_id:
            topic_map[info.id] = dst_id
            continue

        if info.title in mirror_by_title:
            topic_map[info.id] = mirror_by_title[info.title]
            continue

        icon = f" emoji={info.icon_emoji_id}" if info.icon_emoji_id else ""
        print(f"  + тема: {info.title} (цвет {info.icon_color}{icon})")
        await create_topic(client, mirror, info)
        await asyncio.sleep(1.5)
        mirror_topics = await get_topics(client, mirror)
        mirror_by_id = {t.id: t for t in mirror_topics}
        mirror_by_title = {t.title: t.id for t in mirror_topics}
        topic_map[info.id] = mirror_by_title[info.title]

    return topic_map


async def recreate_topic(
    client,
    mirror,
    old_dst_id: int,
    src_id: int,
    info: TopicInfo,
    state: dict,
) -> int:
    await client(
        EditForumTopicRequest(
            peer=mirror,
            topic_id=old_dst_id,
            title=f".archive {info.title}",
            hidden=True,
        )
    )
    await asyncio.sleep(1)
    await create_topic(client, mirror, info)
    await asyncio.sleep(1.5)
    new_id = next(t.id for t in await get_topics(client, mirror) if t.title == info.title)
    state.get("last_msg", {}).pop(f"{src_id}->{old_dst_id}", None)
    return new_id


async def sync_topics(
    client,
    mirror,
    source_topics: list[TopicInfo],
    topic_map: dict[int, int],
    state: dict | None = None,
) -> dict[int, int]:
    mirror_by_id = {t.id: t for t in await get_topics(client, mirror)}
    updated = dict(topic_map)
    print("\nСинхронизация тем...")
    for info in source_topics:
        dst = updated.get(info.id)
        if not dst or dst == 1:
            continue
        cur = mirror_by_id.get(dst)
        if not cur:
            continue
        need_title = cur.title != info.title
        need_icon = bool(info.icon_emoji_id) and cur.icon_emoji_id != info.icon_emoji_id
        need_color = cur.icon_color != info.icon_color
        if need_color and state is not None:
            print(f"  ↻ {info.title}: пересоздаю (цвет {cur.icon_color} → {info.icon_color})")
            try:
                new_id = await recreate_topic(client, mirror, dst, info.id, info, state)
                updated[info.id] = new_id
                mirror_by_id[new_id] = info
                await asyncio.sleep(0.8)
            except Exception as exc:
                print(f"  ✗ {info.title}: {exc}")
            continue
        if not need_title and not need_icon:
            print(f"  · {info.title} — без изменений")
            continue
        try:
            await update_topic(client, mirror, dst, info, need_title, need_icon)
            parts = []
            if need_title:
                parts.append(f"«{cur.title}» → «{info.title}»")
            if need_icon:
                parts.append("иконка")
            print(f"  ✓ {info.title}: {', '.join(parts)}")
            await asyncio.sleep(0.8)
        except Exception as exc:
            err = str(exc)
            if "TOPIC_NOT_MODIFIED" in err:
                print(f"  · {info.title} — уже актуально")
            else:
                print(f"  ✗ {info.title}: {exc}")
    return updated


async def sync_topic_flags(
    client,
    mirror,
    source_topics: list[TopicInfo],
    topic_map: dict[int, int],
) -> None:
    mirror_by_id = {t.id: t for t in await get_topics(client, mirror)}
    print("\nСинхронизация закрепов и статусов...")
    for info in source_topics:
        dst = topic_map.get(info.id)
        if not dst:
            continue
        cur = mirror_by_id.get(dst)
        if not cur:
            continue
        try:
            if cur.pinned != info.pinned:
                await client(
                    UpdatePinnedForumTopicRequest(peer=mirror, topic_id=dst, pinned=info.pinned)
                )
                print(f"  ✓ {info.title}: закреп={'да' if info.pinned else 'нет'}")
                await asyncio.sleep(0.5)
            if cur.closed != info.closed:
                await client(
                    EditForumTopicRequest(peer=mirror, topic_id=dst, closed=info.closed)
                )
                print(f"  ✓ {info.title}: закрыта={'да' if info.closed else 'нет'}")
                await asyncio.sleep(0.5)
        except Exception as exc:
            err = str(exc)
            if "TOPIC_NOT_MODIFIED" not in err:
                print(f"  ✗ {info.title}: {exc}")


async def create_forum_copy(client: TelegramClient, title: str):
    print(f"Создаю группу-форум: {title}")
    created = await client(
        CreateChannelRequest(
            title=title,
            about="Копия VERDI COMMUNITY",
            megagroup=True,
        )
    )
    mirror = created.chats[0]
    try:
        await client(ToggleForumRequest(channel=mirror, enabled=True, tabs=False))
    except FloodWaitError as exc:
        print(f"  пауза Telegram: {exc.seconds}s")
        await asyncio.sleep(exc.seconds + 2)
        await client(ToggleForumRequest(channel=mirror, enabled=True, tabs=False))
    await asyncio.sleep(2)
    return await client.get_entity(mirror.id)


async def get_topic_tops(client: TelegramClient, peer) -> dict[int, int]:
    result = await client(
        GetForumTopicsRequest(
            peer=peer,
            offset_date=None,
            offset_id=0,
            offset_topic=0,
            limit=100,
        )
    )
    return {
        t.id: t.top_message
        for t in result.topics
        if hasattr(t, "title") and hasattr(t, "top_message")
    }


def message_topic_id(msg, topic_tops: dict[int, int]) -> int:
    if not msg.reply_to:
        return 1
    reply = msg.reply_to
    top_id = getattr(reply, "reply_to_top_id", None)
    if top_id:
        return top_id
    if getattr(reply, "forum_topic", False):
        ref = getattr(reply, "reply_to_msg_id", None)
        if ref is None:
            return 1
        for topic_id, top_msg in topic_tops.items():
            if ref in (topic_id, top_msg):
                return topic_id
        return ref
    return 1


async def clear_mirror_messages(client: TelegramClient, mirror) -> int:
    deleted = 0
    async for msg in client.iter_messages(mirror):
        if isinstance(msg, MessageService):
            continue
        try:
            await client.delete_messages(mirror, msg.id)
            deleted += 1
            if deleted % 20 == 0:
                await asyncio.sleep(0.5)
            else:
                await asyncio.sleep(0.15)
        except FloodWaitError as exc:
            await asyncio.sleep(exc.seconds + 1)
        except Exception:
            pass
    return deleted


async def copy_topic(
    client: TelegramClient,
    source,
    mirror,
    src_topic_id: int,
    dst_topic_id: int,
    state: dict,
    topic_tops: dict[int, int],
) -> int:
    key = f"{src_topic_id}->{dst_topic_id}"
    last_id = int(state.get("last_msg", {}).get(key, 0))
    copied = 0

    async for msg in client.iter_messages(source, reverse=True):
        if isinstance(msg, MessageService):
            continue
        if message_topic_id(msg, topic_tops) != src_topic_id:
            continue
        if msg.id <= last_id:
            continue

        text = msg.message or ""
        try:
            if msg.media:
                path = await client.download_media(msg, file=str(CACHE / f"cp_{msg.id}"))
                if path:
                    await client.send_file(
                        mirror, path, caption=text or None, reply_to=dst_topic_id
                    )
                    Path(path).unlink(missing_ok=True)
            elif text:
                await client.send_message(mirror, text, reply_to=dst_topic_id)
            else:
                continue
            copied += 1
            state.setdefault("last_msg", {})[key] = msg.id
            if copied % 50 == 0:
                print(f"    ... {copied}")
            await asyncio.sleep(DELAY)
        except FloodWaitError as exc:
            print(f"    пауза {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 1)
        except Exception as exc:
            print(f"    пропуск #{msg.id}: {exc}")

    return copied


async def run(
    source_ref: str,
    mirror_title: str | None,
    resume: bool,
    icons_only: bool,
    fix_messages: bool,
) -> None:
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

    state: dict = {}
    if resume and STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))

    source = await client.get_entity(source_ref)
    src_title = getattr(source, "title", source_ref)
    print(f"Источник: {src_title} (@{getattr(source, 'username', '')})")

    source_topics = await get_topics(client, source)
    print("Темы:")
    for info in source_topics:
        icon = f"emoji={info.icon_emoji_id}" if info.icon_emoji_id else f"color={info.icon_color}"
        print(f"  {info.id}: {info.title} ({icon})")

    if icons_only:
        if not STATE_FILE.exists():
            print("Нет forum_clone_state.json — сначала создайте копию")
            return
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        mirror = await client.get_entity(int(state["mirror_chat_id"]))
        old_map = {int(k): v for k, v in state.get("topic_map", {}).items()}
        print("\nПроверка тем...")
        topic_map = await ensure_topics(client, mirror, source_topics, old_map)
        topic_map = await sync_topics(client, mirror, source_topics, topic_map, state)
        await sync_topic_flags(client, mirror, source_topics, topic_map)
        state["topic_map"] = {str(k): v for k, v in topic_map.items()}
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        await client.disconnect()
        return

    if state.get("mirror_chat_id") and resume:
        mirror = await client.get_entity(int(state["mirror_chat_id"]))
        print(f"Продолжаю в существующем зеркале: {mirror.title}")
        old_map = {int(k): v for k, v in state.get("topic_map", {}).items()}
        print("Проверка тем...")
        topic_map = await ensure_topics(client, mirror, source_topics, old_map)
        topic_map = await sync_topics(client, mirror, source_topics, topic_map, state)
        await sync_topic_flags(client, mirror, source_topics, topic_map)
        state["topic_map"] = {str(k): v for k, v in topic_map.items()}
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        title = mirror_title or f"{src_title} · копия"
        mirror = await create_forum_copy(client, title)
        topic_map = await ensure_topics(client, mirror, source_topics)
        topic_map = await sync_topics(client, mirror, source_topics, topic_map, state)
        await sync_topic_flags(client, mirror, source_topics, topic_map)
        state = {
            "source": source_ref,
            "mirror_chat_id": utils.get_peer_id(mirror),
            "mirror_title": getattr(mirror, "title", title),
            "topic_map": {str(k): v for k, v in topic_map.items()},
            "last_msg": {},
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Новый форум: id={state['mirror_chat_id']}")

    topic_tops = await get_topic_tops(client, source)

    if fix_messages and state.get("mirror_chat_id"):
        print("\nОчистка сообщений в копии...")
        n = await clear_mirror_messages(client, mirror)
        print(f"  удалено: {n}")
        state["last_msg"] = {}
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    total = 0
    for info in source_topics:
        dst_tid = topic_map.get(info.id)
        if not dst_tid:
            print(f"✗ нет темы «{info.title}»")
            continue
        print(f"\n→ «{info.title}» ({info.id} → {dst_tid})")
        n = await copy_topic(client, source, mirror, info.id, dst_tid, state, topic_tops)
        total += n
        print(f"  скопировано: {n}")
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nГотово. Всего сообщений: {total}")
    print(f"Новый мультичат: {state.get('mirror_title')} (id={state['mirror_chat_id']})")
    await client.disconnect()


def main() -> None:
    p = argparse.ArgumentParser(description="Клон форума multi12000 в новую группу")
    p.add_argument("--source", default=SOURCE)
    p.add_argument("--title", default=None, help="Название новой группы")
    p.add_argument("--resume", action="store_true", help="Синхронизировать темы и новые сообщения")
    p.add_argument(
        "--icons-only",
        action="store_true",
        help="Только обновить иконки тем в последней копии",
    )
    p.add_argument(
        "--fix-messages",
        action="store_true",
        help="Удалить сообщения в копии и скопировать заново по темам",
    )
    args = p.parse_args()
    asyncio.run(
        run(args.source, args.title, args.resume, args.icons_only, args.fix_messages)
    )


if __name__ == "__main__":
    main()
