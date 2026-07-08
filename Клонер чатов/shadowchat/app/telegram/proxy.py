"""Прокси для Telethon (host:port:user:pass или URL)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


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
        ptype = (proxy_type or "http").strip().lower()
        if ptype not in {"socks5", "http"}:
            ptype = "http"
        return (ptype, match.group("host"), int(match.group("port")))

    auth_match = re.match(
        r"^(?P<host>[^:]+):(?P<port>\d+):(?P<user>[^:]+):(?P<password>.+)$",
        raw,
    )
    if auth_match:
        ptype = (proxy_type or "http").strip().lower()
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

    raise ValueError("Формат TG_PROXY: host:port:user:pass или http://user:pass@host:port")


def proxy_label(proxy: tuple[Any, ...] | None) -> str:
    if not proxy:
        return "без прокси"
    return f"{proxy[0]}://{proxy[1]}:{proxy[2]}"


def chat_id_variants(chat_id: int) -> set[int]:
    """Варианты ID для сравнения (Telethon / боты иногда отдают разный формат)."""
    variants = {chat_id}
    s = str(chat_id)
    if s.startswith("-100"):
        variants.add(int(f"-{s[4:]}"))
        variants.add(int(s[4:]))
    elif chat_id < 0:
        bare = abs(chat_id)
        variants.add(int(f"-100{bare}"))
        variants.add(bare)
    else:
        variants.add(int(f"-100{chat_id}"))
        variants.add(-chat_id)
    return variants
