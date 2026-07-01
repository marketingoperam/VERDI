"""Создание Telethon-клиента с поддержкой прокси."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

from telethon import TelegramClient
from telethon.sessions import StringSession

COMMON_SOCKS_PORTS = (10808, 7890, 7891, 1080, 9050, 2080)

_ROOT = Path(__file__).resolve().parents[2]
WORKING_PROXY_FILE = _ROOT / "backend" / "sessions" / "working_proxy.json"
_PARSER_PROXY_FILE = _ROOT / "Парсер" / "Телеграм конкуренты" / "sessions" / "working_proxy.json"


def parse_proxy(raw: str, proxy_type: str | None = None) -> tuple[Any, ...] | None:
    raw = (raw or "").strip()
    if not raw:
        return None

    if raw.startswith("socks5://") or raw.startswith("http://"):
        parsed = urlparse(raw)
        scheme = parsed.scheme.lower()
        ptype = "socks5" if scheme == "socks5" else "http"
        if not parsed.hostname or not parsed.port:
            raise ValueError(f"Некорректный прокси: {raw}")
        if parsed.username:
            return (
                ptype,
                parsed.hostname,
                parsed.port,
                True,
                parsed.username,
                parsed.password or "",
            )
        return (ptype, parsed.hostname, parsed.port)

    match = re.match(r"^(?P<host>[^:]+):(?P<port>\d+)$", raw)
    if match:
        ptype = (proxy_type or os.getenv("TG_PROXY_TYPE", "http")).strip().lower()
        if ptype not in {"socks5", "http"}:
            ptype = "http"
        return (ptype, match.group("host"), int(match.group("port")))

    auth_match = re.match(
        r"^(?P<host>[^:]+):(?P<port>\d+):(?P<user>[^:]+):(?P<password>.+)$",
        raw,
    )
    if auth_match:
        ptype = (proxy_type or os.getenv("TG_PROXY_TYPE", "http")).strip().lower()
        if ptype not in {"socks5", "http"}:
            ptype = "http"
        return (
            ptype,
            auth_match.group("host"),
            int(auth_match.group("port")),
            True,
            auth_match.group("user"),
            auth_match.group("password"),
        )

    raise ValueError(
        "Формат TG_PROXY: host:port:user:pass или http://user:pass@host:port"
    )


def proxy_to_tuple(data: dict[str, Any]) -> tuple[Any, ...]:
    return (
        data["type"],
        data["host"],
        int(data["port"]),
        True,
        data["username"],
        data["password"],
    )


def load_working_proxy() -> tuple[Any, ...] | None:
    for path in (WORKING_PROXY_FILE, _PARSER_PROXY_FILE):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return proxy_to_tuple(data)
        except Exception:
            continue
    return None


def save_working_proxy(proxy: tuple[Any, ...]) -> None:
    if not proxy or len(proxy) < 6:
        return
    WORKING_PROXY_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": proxy[0],
        "host": proxy[1],
        "port": proxy[2],
        "username": proxy[4],
        "password": proxy[5],
    }
    WORKING_PROXY_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def proxy_label(proxy: tuple[Any, ...] | None) -> str:
    if not proxy:
        return "без прокси"
    return f"{proxy[0]}://{proxy[1]}:{proxy[2]}"


def proxy_from_env() -> tuple[Any, ...] | None:
    saved = load_working_proxy()
    if saved:
        return saved
    return parse_proxy(os.getenv("TG_PROXY", "").strip())


def create_telegram_client(
    session_path: str,
    api_id: int | str,
    api_hash: str,
    *,
    proxy: tuple[Any, ...] | None = None,
) -> TelegramClient:
    session = StringSession() if session_path in {":memory:", ":string:"} else session_path
    return TelegramClient(
        session,
        int(api_id),
        api_hash,
        proxy=proxy,
        use_ipv6=False,
        connection_retries=10,
        retry_delay=2,
        timeout=30,
        request_retries=5,
    )
