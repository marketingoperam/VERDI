"""Клонер с пулом техаккаунтов: listener слушает, tech постит с профилем."""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import sys
import uuid
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

import functools

print = functools.partial(print, flush=True)

from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.tl.types import MessageService, User

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / "shadowchat" / ".env")

from run import (
    api_credentials,
    same_chat,
    send_to_mirror_pooled,
)
from run_multi import Route, message_matches_topic, sender_allowed

POOL_LISTENER = "listener_main"
POOL_SESSIONS = ROOT / "sessions" / f"pool_{uuid.uuid4().hex[:8]}"
POOL_SESSIONS.mkdir(parents=True, exist_ok=True)


def pool_session(session_name: str) -> str:
    """Копия .session на время запуска — без блокировки SQLite."""
    src = SHADOWCHAT / "sessions" / f"{session_name}.session"
    dst = POOL_SESSIONS / f"{session_name}.session"
    if src.exists():
        shutil.copy2(src, dst)
        journal = src.with_name(f"{session_name}.session-journal")
        if journal.exists():
            shutil.copy2(journal, dst.with_name(f"{session_name}.session-journal"))
    return str(POOL_SESSIONS / session_name)


def bindings_path(pool: str) -> Path:
    safe = pool.replace("/", "_")
    return ROOT / f"sender_bindings_{safe}.json"


def load_bindings(path: Path) -> dict[str, str]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def backfill_state_path(pool: str) -> Path:
    safe = pool.replace("/", "_")
    return ROOT / f"backfill_state_{safe}.json"


def load_backfill_state(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text(encoding="utf-8"))
    return set(data.get("done", []))


def save_backfill_state(path: Path, done: set[str]) -> None:
    path.write_text(
        json.dumps({"done": sorted(done)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def backfill_delay_seconds(min_min: float, max_min: float) -> int:
    lo = int(min_min * 60)
    hi = int(max_min * 60)
    return random.randint(lo, hi)


class PoolRunner:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.pool = str(config.get("pool", "default"))
        self.bindings_file = bindings_path(self.pool)
        self.bindings = load_bindings(self.bindings_file)
        self.tech_sessions: list[str] = list(config.get("tech_sessions", []))
        self.usage: dict[str, int] = defaultdict(int)
        for sid in self.bindings.values():
            self.usage[sid] += 1

        defaults = {
            k: config[k]
            for k in ("use_ai", "ignore_bots", "ignore_service_messages", "sync_profile")
            if k in config
        }
        self.defaults = defaults
        self.routes = [Route.from_dict(item, defaults) for item in config["routes"]]
        self.route_meta = {
            r["name"]: r for r in config["routes"]
        }
        self.listener: TelegramClient | None = None
        self.tech_clients: dict[str, TelegramClient] = {}

    def assign_session(self, sender_id: int) -> str:
        key = str(sender_id)
        if key in self.bindings:
            return self.bindings[key]
        if not self.tech_sessions:
            raise RuntimeError("Пул tech_sessions пуст")

        session_name = min(self.tech_sessions, key=lambda s: self.usage[s])
        self.bindings[key] = session_name
        self.usage[session_name] += 1
        from run import _profile_states

        _profile_states.pop(session_name, None)
        save_bindings(self.bindings_file, self.bindings)
        print(f"  закреплён sender {sender_id} → {session_name}")
        return session_name

    async def connect_all(self) -> None:
        api_id, api_hash = api_credentials()
        self.listener = TelegramClient(
            pool_session(POOL_LISTENER),
            api_id,
            api_hash,
            sequential_updates=True,
        )
        await self.listener.connect()
        if not await self.listener.is_user_authorized():
            raise RuntimeError("listener_main не авторизован")

        for name in self.tech_sessions:
            client = TelegramClient(
                pool_session(name),
                api_id,
                api_hash,
                sequential_updates=True,
            )
            await client.connect()
            if not await client.is_user_authorized():
                print(f"  [{name}] не авторизован — исключён из пула")
                await client.disconnect()
                continue
            self.tech_clients[name] = client
            await client.get_dialogs(limit=80)

        if not self.tech_clients:
            raise RuntimeError("Нет авторизованных техаккаунтов в пуле")

        for route in self.routes:
            route.source_entity = await self.listener.get_entity(route.source_chat_id)
            route.mirror_entity = await self.listener.get_entity(route.mirror_chat_id)

        me = await self.listener.get_me()
        print("=" * 52)
        print(f"  Клонер пула: {self.pool}")
        print("=" * 52)
        print(f"Слушатель: {me.first_name} (@{me.username})")
        print(f"Маршрутов: {len(self.routes)} | техаккаунтов: {len(self.tech_clients)}")
        for route in self.routes:
            src = getattr(route.source_entity, "title", route.source_chat_id)
            mir = getattr(route.mirror_entity, "title", route.mirror_chat_id)
            print(f"  • [{route.name}] {src} → {mir}")
        print()

    async def run(self) -> None:
        await self.connect_all()
        assert self.listener is not None
        await self.listener.get_dialogs(limit=80)

        ignore_bots = bool(self.defaults.get("ignore_bots", True))
        ignore_service = bool(self.defaults.get("ignore_service_messages", True))

        @self.listener.on(events.NewMessage())
        async def on_message(event):
            for route in self.routes:
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
                if not isinstance(sender, User):
                    continue

                session_name = self.assign_session(sender.id)
                tech = self.tech_clients.get(session_name)
                if not tech:
                    print(f"  ✗ нет клиента {session_name}")
                    return

                try:
                    who = " ".join(p for p in (sender.first_name, sender.last_name) if p)
                    print(f"→ [{route.name}] #{event.message.id} от {who} via {session_name}")
                    meta = self.route_meta.get(route.name, {})
                    await send_to_mirror_pooled(
                        self.listener,
                        tech,
                        event.message,
                        route.mirror_chat_id,
                        sync_name=route.sync_name,
                        sync_avatar=route.sync_avatar,
                        mirror_topic_id=route.mirror_topic_id,
                        mirror_username=meta.get("mirror_username"),
                        tech_session_name=session_name,
                    )
                    print(f"  ✓ в зеркало")
                except Exception as exc:
                    err = str(exc)
                    if "banned" in err.lower():
                        print(f"  ✗ {session_name} заблокирован в зеркале")
                    else:
                        print(f"  ✗ {exc}")
                return

        print(f"[{self.pool}] слушаю источники… Ctrl+C для остановки\n")
        await self.listener.run_until_disconnected()

    async def disconnect_all(self) -> None:
        if self.listener:
            await self.listener.disconnect()
            self.listener = None
        for client in self.tech_clients.values():
            await client.disconnect()
        self.tech_clients.clear()

    async def backfill(
        self,
        limit: int = 10,
        *,
        min_delay_min: float = 3.0,
        max_delay_min: float = 10.0,
    ) -> None:
        """Разовое копирование последних N сообщений по каждому маршруту (хронологический порядок)."""
        await self.connect_all()
        assert self.listener is not None

        ignore_bots = bool(self.defaults.get("ignore_bots", True))
        ignore_service = bool(self.defaults.get("ignore_service_messages", True))
        state_file = backfill_state_path(self.pool)
        done = load_backfill_state(state_file)

        print(
            f"Бэкфилл: до {limit} сообщений на маршрут, "
            f"пауза {min_delay_min:g}–{max_delay_min:g} мин между копиями\n"
        )

        pending: list[tuple[Route, object]] = []

        for route in self.routes:
            collected: list = []
            async for msg in self.listener.iter_messages(route.source_entity, limit=200):
                if ignore_service and isinstance(msg, MessageService):
                    continue
                if not message_matches_topic(msg, route.source_topic_id):
                    continue
                sender = await msg.get_sender()
                if ignore_bots and isinstance(sender, User) and sender.bot:
                    continue
                if not sender_allowed(sender, route):
                    continue
                if not isinstance(sender, User):
                    continue
                collected.append(msg)
                if len(collected) >= limit:
                    break

            collected.reverse()
            src = getattr(route.source_entity, "title", route.source_chat_id)
            print(f"── [{route.name}] {src}: {len(collected)} сообщений в очереди")
            for msg in collected:
                key = f"{route.name}:{msg.id}"
                if key in done:
                    print(f"  пропуск #{msg.id} (уже скопировано)")
                    continue
                pending.append((route, msg))

        print(f"\nК копированию: {len(pending)} сообщений\n")

        for idx, (route, msg) in enumerate(pending):
            sender = await msg.get_sender()
            session_name = self.assign_session(sender.id)
            tech = self.tech_clients.get(session_name)
            if not tech:
                print(f"  ✗ нет клиента {session_name}")
                continue

            try:
                who = " ".join(p for p in (sender.first_name, sender.last_name) if p)
                print(f"→ [{route.name}] #{msg.id} от {who} via {session_name}")
                meta = self.route_meta.get(route.name, {})
                await send_to_mirror_pooled(
                    self.listener,
                    tech,
                    msg,
                    route.mirror_chat_id,
                    sync_name=route.sync_name,
                    sync_avatar=route.sync_avatar,
                    mirror_topic_id=route.mirror_topic_id,
                    mirror_username=meta.get("mirror_username"),
                    tech_session_name=session_name,
                )
                key = f"{route.name}:{msg.id}"
                done.add(key)
                save_backfill_state(state_file, done)
                print("  ✓")
            except Exception as exc:
                print(f"  ✗ {exc}")

            if idx < len(pending) - 1:
                wait = backfill_delay_seconds(min_delay_min, max_delay_min)
                mins, secs = divmod(wait, 60)
                print(f"  пауза {mins} мин {secs} с до следующего…\n")
                await asyncio.sleep(wait)

        print("\nБэкфилл завершён.")
        await self.disconnect_all()


def main() -> None:
    p = argparse.ArgumentParser(description="Клонер с пулом техаккаунтов")
    p.add_argument("--config", default=str(ROOT / "multi_config.verdi7.json"))
    args = p.parse_args()
    path = Path(args.config)
    config = json.loads(path.read_text(encoding="utf-8"))
    asyncio.run(PoolRunner(config).run())


if __name__ == "__main__":
    main()
