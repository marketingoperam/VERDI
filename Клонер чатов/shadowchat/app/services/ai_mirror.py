"""Интеграция с ai_mirror: конфиг, маршруты и привязки sender → tech."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import PROJECT_ROOT, get_settings, update_runtime_settings
from app.models import MirrorChat, MirrorMode, SessionPool, SourceChat

logger = structlog.get_logger()

AI_MIRROR_ROOT = PROJECT_ROOT.parent / "ai_mirror"
DEFAULT_CONFIG = AI_MIRROR_ROOT / "multi_config.verdi_all.json"

TEST_SESSION_RE = re.compile(r"^tech_\d{1,2}$")


@dataclass
class AiMirrorRoute:
    name: str
    route_type: str
    source_chat_id: int
    source_title: str
    mirror_chat_id: int
    mirror_username: str | None
    sync_profile: bool
    sync_name: bool
    sync_avatar: bool
    tech_sessions: tuple[str, ...] = ()


@dataclass
class AiMirrorStore:
    pool: str = "verdi_all"
    config_path: Path = field(default_factory=lambda: DEFAULT_CONFIG)
    tech_sessions: list[str] = field(default_factory=list)
    routes: list[AiMirrorRoute] = field(default_factory=list)
    bindings: dict[str, str] = field(default_factory=dict)
    route_tech: dict[str, list[str]] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    defaults: dict = field(default_factory=dict)

    @property
    def bindings_path(self) -> Path:
        safe = self.pool.replace("/", "_")
        return AI_MIRROR_ROOT / f"sender_bindings_{safe}.json"

    def load(self) -> None:
        if not self.config_path.exists():
            raise FileNotFoundError(f"ai_mirror config not found: {self.config_path}")

        config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.pool = str(config.get("pool", "verdi_all"))
        self.defaults = {
            k: config[k]
            for k in ("use_ai", "ignore_bots", "ignore_service_messages", "sync_profile")
            if k in config
        }
        self.tech_sessions = [str(x) for x in config.get("tech_sessions", [])]
        self.route_tech = {}
        self.routes = []

        for item in config.get("routes", []):
            sync_profile = bool(item.get("sync_profile", self.defaults.get("sync_profile", False)))
            tech = item.get("tech_sessions")
            tech_sessions = tuple(str(x) for x in tech) if tech else ()
            route = AiMirrorRoute(
                name=str(item["name"]),
                route_type=str(item.get("type", "generic")),
                source_chat_id=int(item["source_chat_id"]),
                source_title=str(item.get("source_title", item["name"])),
                mirror_chat_id=int(item["mirror_chat_id"]),
                mirror_username=item.get("mirror_username"),
                sync_profile=sync_profile,
                sync_name=bool(item.get("sync_name", sync_profile)),
                sync_avatar=bool(item.get("sync_avatar", sync_profile)),
                tech_sessions=tech_sessions,
            )
            self.routes.append(route)
            if tech:
                self.route_tech[route.name] = [str(x) for x in tech]

        self.bindings = {}
        if self.bindings_path.exists():
            self.bindings = json.loads(self.bindings_path.read_text(encoding="utf-8"))

        self.usage = defaultdict(int)
        for session_name in self.bindings.values():
            self.usage[session_name] += 1

        logger.info(
            "ai_mirror_loaded",
            pool=self.pool,
            routes=len(self.routes),
            bindings=len(self.bindings),
            tech_sessions=len(self.tech_sessions),
        )

    def save_bindings(self) -> None:
        self.bindings_path.write_text(
            json.dumps(self.bindings, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def tech_pool_for(self, route_name: str) -> list[str]:
        if route_name in self.route_tech:
            return self.route_tech[route_name]
        return self.tech_sessions

    def route_for_source(self, telegram_chat_id: int) -> AiMirrorRoute | None:
        for route in self.routes:
            if route.source_chat_id == telegram_chat_id:
                return route
        bare = str(telegram_chat_id)
        for route in self.routes:
            rid = str(route.source_chat_id)
            if rid == bare or rid.endswith(bare.lstrip("-")) or bare.endswith(rid.lstrip("-")):
                return route
        return None

    def assign_session(self, route_name: str, sender_id: int) -> str:
        """Та же логика, что в ai_mirror/run_pool.py."""
        key = f"{route_name}:{sender_id}"
        pool = self.tech_pool_for(route_name)
        if key in self.bindings:
            bound = self.bindings[key]
            if bound in pool:
                return bound
        if not pool:
            raise RuntimeError(f"Пул tech_sessions пуст для маршрута {route_name}")

        session_name = min(pool, key=lambda s: self.usage[s])
        self.bindings[key] = session_name
        self.usage[session_name] += 1
        self.save_bindings()
        logger.info("ai_mirror_binding_assigned", route=route_name, sender_id=sender_id, session=session_name)
        return session_name

    def apply_runtime_settings(self) -> None:
        updates: dict = {}
        if self.defaults.get("ignore_bots") is not None:
            updates["ignore_bots"] = bool(self.defaults["ignore_bots"])
        if self.defaults.get("ignore_service_messages") is not None:
            updates["ignore_service_messages"] = bool(self.defaults["ignore_service_messages"])
        if self.defaults.get("sync_profile"):
            updates["profile_sync_enabled"] = True
        updates["delete_mode"] = "hard_delete"
        if updates:
            update_runtime_settings(updates)

    def mirror_mode_for_route(self, route: AiMirrorRoute) -> str:
        if route.sync_profile or route.sync_name or route.sync_avatar:
            return MirrorMode.PROFILE_SYNC.value
        return MirrorMode.SAFE.value


_store: AiMirrorStore | None = None


def get_ai_mirror_store(*, reload: bool = False) -> AiMirrorStore:
    global _store
    if _store is None or reload:
        _store = AiMirrorStore()
        _store.load()
    return _store


async def sync_routes_to_db(db: AsyncSession, store: AiMirrorStore | None = None) -> int:
    store = store or get_ai_mirror_store()
    updated = 0

    for route in store.routes:
        mirror_result = await db.execute(
            select(MirrorChat).where(MirrorChat.telegram_chat_id == route.mirror_chat_id)
        )
        mirror = mirror_result.scalar_one_or_none()
        mode = store.mirror_mode_for_route(route)
        if mirror:
            mirror.title = route.source_title + " (зеркало)"
            mirror.mirror_username = route.mirror_username
            mirror.mode = mode
            mirror.is_active = True
        else:
            mirror = MirrorChat(
                telegram_chat_id=route.mirror_chat_id,
                title=route.source_title + " (зеркало)",
                mirror_username=route.mirror_username,
                mode=mode,
                is_active=True,
            )
            db.add(mirror)
            await db.flush()

        source_result = await db.execute(
            select(SourceChat).where(SourceChat.telegram_chat_id == route.source_chat_id)
        )
        source = source_result.scalar_one_or_none()
        if source:
            source.title = route.source_title
            source.mirror_chat_id = mirror.id
            source.is_active = True
            source.route_name = route.name
        else:
            source = SourceChat(
                telegram_chat_id=route.source_chat_id,
                title=route.source_title,
                mirror_chat_id=mirror.id,
                is_active=True,
                route_name=route.name,
            )
            db.add(source)
        updated += 1

    active_source_ids = {route.source_chat_id for route in store.routes}
    all_sources = await db.execute(select(SourceChat))
    for source in all_sources.scalars():
        if source.telegram_chat_id not in active_source_ids and source.is_active:
            source.is_active = False
            logger.info("source_chat_deactivated", title=source.title)

    await db.flush()
    return updated


async def restrict_tech_pool(db: AsyncSession, store: AiMirrorStore | None = None) -> dict[str, int]:
    store = store or get_ai_mirror_store()
    allowed = set(store.tech_sessions)
    stats = {"activated": 0, "deactivated": 0, "cleared_assignments": 0}

    result = await db.execute(select(SessionPool))
    settings = get_settings()
    for session in result.scalars():
        if session.session_name == settings.listener_session:
            continue
        if TEST_SESSION_RE.match(session.session_name):
            if session.is_active:
                session.is_active = False
                stats["deactivated"] += 1
            if session.assigned_employee_id:
                session.assigned_employee_id = None
                stats["cleared_assignments"] += 1
            continue

        in_pool = session.session_name in allowed
        if in_pool and not session.is_active:
            session.is_active = True
            stats["activated"] += 1
        elif not in_pool and session.is_active:
            session.is_active = False
            stats["deactivated"] += 1

        if session.assigned_employee_id:
            session.assigned_employee_id = None
            stats["cleared_assignments"] += 1

    await db.flush()
    return stats
