"""Клонер мультичата: несколько маршрутов источник → зеркало в одном процессе."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

import functools

print = functools.partial(print, flush=True)

from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from telethon.tl.types import MessageService, User

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / "shadowchat" / ".env")

from run import (  # noqa: E402
    api_credentials,
    ensure_local_session,
    same_chat,
    send_to_mirror,
)

from brain import MirrorBrain  # noqa: E402


@dataclass
class Route:
    name: str
    route_type: str
    session_name: str
    source_chat_id: int
    mirror_chat_id: int
    source_topic_id: int | None = None
    mirror_topic_id: int | None = None
    clone_user_id: int | None = None
    allowed_sender_ids: frozenset[int] = frozenset()
    sync_profile: bool = False
    sync_name: bool = False
    sync_avatar: bool = False
    use_ai: bool = False
    source_entity=None
    mirror_entity=None

    @classmethod
    def from_dict(cls, data: dict, defaults: dict) -> Route:
        sync_profile = bool(data.get("sync_profile", defaults.get("sync_profile", False)))
        return cls(
            name=str(data["name"]),
            route_type=str(data.get("type", "generic")),
            session_name=str(data["session_name"]),
            source_chat_id=int(data["source_chat_id"]),
            mirror_chat_id=int(data["mirror_chat_id"]),
            source_topic_id=_opt_int(data.get("source_topic_id")),
            mirror_topic_id=_opt_int(data.get("mirror_topic_id")),
            clone_user_id=_opt_int(data.get("clone_user_id")),
            allowed_sender_ids=frozenset(int(x) for x in data.get("allowed_sender_ids", [])),
            sync_profile=sync_profile,
            sync_name=bool(data.get("sync_name", sync_profile)),
            sync_avatar=bool(data.get("sync_avatar", sync_profile)),
            use_ai=bool(data.get("use_ai", defaults.get("use_ai", False))),
        )


def _opt_int(value) -> int | None:
    if value is None:
        return None
    return int(value)


def message_matches_topic(message, topic_id: int | None) -> bool:
    """Фильтр темы форума. topic_id=null — весь чат."""
    if topic_id is None:
        return True
    reply = message.reply_to
    if not reply:
        return topic_id == 1
    top = getattr(reply, "reply_to_top_id", None) or getattr(reply, "reply_to_msg_id", None)
    return top == topic_id


def sender_allowed(sender, route: Route) -> bool:
    if not isinstance(sender, User):
        return False
    if route.allowed_sender_ids and sender.id not in route.allowed_sender_ids:
        return False
    if route.clone_user_id and sender.id != route.clone_user_id:
        return False
    return True


async def run_session(session_name: str, routes: list[Route], defaults: dict) -> None:
    api_id, api_hash = api_credentials()
    client = TelegramClient(
        ensure_local_session(session_name),
        api_id,
        api_hash,
        sequential_updates=True,
    )
    await client.connect()
    if not await client.is_user_authorized():
        print(f"[{session_name}] не авторизован — пропуск")
        return

    me = await client.get_me()
    print(f"\n── Аккаунт {me.first_name} ({me.phone}) — маршрутов: {len(routes)}")

    for route in routes:
        route.source_entity = await client.get_entity(route.source_chat_id)
        route.mirror_entity = await client.get_entity(route.mirror_chat_id)
        src = getattr(route.source_entity, "title", route.source_chat_id)
        mir = getattr(route.mirror_entity, "title", route.mirror_chat_id)
        topic = f", тема {route.source_topic_id}" if route.source_topic_id else ""
        print(f"  • [{route.route_type}] {route.name}: {src}{topic} → {mir}")

    await client.get_dialogs(limit=80)

    ignore_bots = bool(defaults.get("ignore_bots", True))
    ignore_service = bool(defaults.get("ignore_service_messages", True))
    brains: dict[bool, MirrorBrain | None] = {}

    @client.on(events.NewMessage())
    async def on_message(event):
        for route in routes:
            if not same_chat(event.chat_id, route.source_entity):
                continue
            if not message_matches_topic(event.message, route.source_topic_id):
                continue
            if ignore_service and isinstance(event.message, MessageService):
                continue
            sender = await event.message.get_sender()
            if ignore_bots and isinstance(sender, User) and sender.bot:
                continue
            if not sender_allowed(sender, route):
                continue

            use_ai = route.use_ai
            if use_ai and use_ai not in brains:
                brains[use_ai] = MirrorBrain()
            brain = brains.get(use_ai) if use_ai else None

            try:
                print(f"→ [{route.name}] #{event.message.id}")
                await send_to_mirror(
                    client,
                    event.message,
                    route.mirror_entity,
                    sync_name=route.sync_name,
                    sync_avatar=route.sync_avatar,
                    mirror_topic_id=route.mirror_topic_id,
                    brain=brain,
                    use_ai=use_ai,
                )
                print(f"  ✓ в зеркало [{route.name}]")
            except Exception as exc:
                print(f"  ✗ [{route.name}] {exc}")
            return

    print(f"[{session_name}] слушаю...\n")
    await client.run_until_disconnected()


async def run_multi(config: dict) -> None:
    defaults = {
        k: config[k]
        for k in ("use_ai", "ignore_bots", "ignore_service_messages", "sync_profile")
        if k in config
    }
    routes = [Route.from_dict(item, defaults) for item in config["routes"]]
    by_session: dict[str, list[Route]] = defaultdict(list)
    for route in routes:
        by_session[route.session_name].append(route)

    print("=" * 48)
    print("  AI Mirror — мультичат")
    print("=" * 48)
    print(f"Маршрутов: {len(routes)} | аккаунтов: {len(by_session)}")

    await asyncio.gather(
        *[run_session(name, rs, defaults) for name, rs in by_session.items()]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Клонер мультичата")
    parser.add_argument("--config", default=str(ROOT / "multi_config.json"))
    args = parser.parse_args()
    path = Path(args.config)
    if not path.exists():
        print(f"Нет файла {path}")
        print("Скопируйте multi_config.example.json → multi_config.json и заполните.")
        sys.exit(1)
    config = json.loads(path.read_text(encoding="utf-8"))
    asyncio.run(run_multi(config))


if __name__ == "__main__":
    main()
