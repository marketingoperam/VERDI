"""Надёжный запуск ShadowChat одной командой."""
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./data/shadowchat.db")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SESSIONS_DIR", "sessions")
os.environ.setdefault("MEDIA_CACHE_DIR", "media_cache")

for d in ("data", "sessions", "media_cache"):
    (ROOT / d).mkdir(exist_ok=True)


def _port() -> int:
    from app.config import get_settings

    return int(get_settings().admin_api_port)


def _base_url() -> str:
    return f"http://127.0.0.1:{_port()}"


def _server_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{_base_url()}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _open_browser_when_ready() -> None:
    url = _base_url()
    for _ in range(30):
        if _server_ready():
            webbrowser.open(url)
            print(f"\nПанель открыта в браузере: {url}\n")
            return
        time.sleep(1)
    print(f"\nСервер запущен. Откройте вручную: {url}\n")


def main() -> None:
    port = _port()
    print("=" * 40)
    print("  ShadowChat — Клонер чатов")
    print("=" * 40)
    print(f"\nЗапуск сервера на { _base_url() }...")
    print("Остановка: Ctrl+C\n")

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=False)


if __name__ == "__main__":
    main()
