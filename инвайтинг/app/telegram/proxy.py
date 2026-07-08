from __future__ import annotations

from urllib.parse import urlparse


def parse_proxy(raw: str, proxy_type: str) -> tuple:
    """
    raw examples:
      socks5://user:pass@host:1080
      socks5://host:1080
      http://host:8080
    """
    p = urlparse(raw)
    if not p.scheme or not p.hostname or not p.port:
        raise ValueError("Invalid proxy URL")
    user = p.username
    password = p.password
    if user and password:
        return (proxy_type, p.hostname, p.port, True, user, password)
    return (proxy_type, p.hostname, p.port)


def proxy_label(proxy: tuple) -> str:
    try:
        return f"{proxy[0]}://{proxy[1]}:{proxy[2]}"
    except Exception:
        return "proxy"

