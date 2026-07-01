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
WORKING_PROXY_FILE = Path(__file__).resolve().parent / "sessions" / "working_proxy.json"


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


def proxy_to_env_value(proxy: tuple[Any, ...]) -> str:
    if not proxy or len(proxy) < 3:
        return ""
    ptype, host, port = proxy[0], proxy[1], proxy[2]
    if len(proxy) >= 6:
        user, password = proxy[4], proxy[5]
        return f"{ptype}://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    return f"{ptype}://{host}:{port}"


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
    update_env_proxy_settings(proxy[0], proxy)


def load_working_proxy() -> tuple[Any, ...] | None:
    if not WORKING_PROXY_FILE.exists():
        return None
    try:
        data = json.loads(WORKING_PROXY_FILE.read_text(encoding="utf-8"))
        return proxy_to_tuple(data)
    except Exception:
        return None


def update_env_proxy_settings(proxy_type: str, proxy: tuple[Any, ...]) -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines: list[str] = []
    seen_type = False
    for line in lines:
        if line.startswith("TG_PROXY_TYPE="):
            new_lines.append(f"TG_PROXY_TYPE={proxy_type}")
            seen_type = True
        elif line.startswith("# Если не работает"):
            continue
        else:
            new_lines.append(line)
    if not seen_type:
        new_lines.append(f"TG_PROXY_TYPE={proxy_type}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def proxy_label(proxy: tuple[Any, ...] | dict[str, Any] | None) -> str:
    if not proxy:
        return "без прокси"
    if isinstance(proxy, dict):
        return f"{proxy.get('type', 'proxy')}://{proxy.get('host')}:{proxy.get('port')}"
    return f"{proxy[0]}://{proxy[1]}:{proxy[2]}"


def resolve_session(session_path: str) -> str | StringSession:
    if session_path in {":memory:", ":string:"}:
        return StringSession()
    return session_path


def create_telegram_client(
    session_path: str,
    api_id: int | str,
    api_hash: str,
    *,
    proxy: tuple[Any, ...] | dict[str, Any] | None = None,
    connection_retries: int = 10,
    timeout: int = 30,
) -> TelegramClient:
    return TelegramClient(
        resolve_session(session_path),
        int(api_id),
        api_hash,
        proxy=proxy,
        use_ipv6=False,
        connection_retries=connection_retries,
        retry_delay=2,
        timeout=timeout,
        request_retries=5,
    )


def proxy_from_env() -> tuple[Any, ...] | None:
    saved = load_working_proxy()
    if saved:
        return saved
    return parse_proxy(os.getenv("TG_PROXY", "").strip())


def auth_proxy_variants(raw: str) -> list[tuple[Any, ...]]:
    auth_match = re.match(
        r"^(?P<host>[^:]+):(?P<port>\d+):(?P<user>[^:]+):(?P<password>.+)$",
        raw,
    )
    if not auth_match:
        return []
    host = auth_match.group("host")
    port = int(auth_match.group("port"))
    user = auth_match.group("user")
    password = auth_match.group("password")
    return [
        ("http", host, port, True, user, password),
        ("socks5", host, port, True, user, password),
    ]


def candidate_proxies(explicit: str | None = "") -> list[tuple[Any, ...] | None]:
    candidates: list[tuple[Any, ...] | None] = []

    def add(proxy: tuple[Any, ...] | None) -> None:
        if proxy not in candidates:
            candidates.append(proxy)

    saved = load_working_proxy()
    if saved:
        add(saved)

    explicit = (explicit or "").strip()
    if explicit:
        if "://" not in explicit and explicit.count(":") >= 3:
            for item in auth_proxy_variants(explicit):
                add(item)
        else:
            add(parse_proxy(explicit))

    env_proxy = os.getenv("TG_PROXY", "").strip()
    if env_proxy:
        if "://" not in env_proxy and env_proxy.count(":") >= 3:
            for item in auth_proxy_variants(env_proxy):
                add(item)
        else:
            preferred = os.getenv("TG_PROXY_TYPE", "http").strip().lower()
            add(parse_proxy(env_proxy, proxy_type=preferred))
            alt = "socks5" if preferred == "http" else "http"
            parsed = parse_proxy(env_proxy, proxy_type=alt)
            if parsed:
                add(parsed)

    for port in COMMON_SOCKS_PORTS:
        add(("socks5", "127.0.0.1", port))

    if None not in candidates:
        candidates.insert(0, None)
    return candidates
