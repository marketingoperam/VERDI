from functools import lru_cache
import os
from pathlib import Path
from typing import Any, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_runtime_overrides: dict[str, Any] = {}
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _resolve_data_path(path: Path) -> Path:
    """Корректные пути и на Windows, и в Docker."""
    raw = str(path).replace("\\", "/")
    if raw.startswith("/app/"):
        return PROJECT_ROOT / Path(raw).name
    if os.name == "nt" and raw.startswith("/"):
        return PROJECT_ROOT / Path(raw.lstrip("/")).name
    if not path.is_absolute():
        return PROJECT_ROOT / path
    return path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+asyncpg://shadowchat:shadowchat@localhost:5432/shadowchat"
    redis_url: str = "redis://localhost:6379/0"

    listener_api_id: int = 0
    listener_api_hash: str = ""
    listener_session: str = "listener_main"

    admin_api_host: str = "0.0.0.0"
    admin_api_port: int = 8000

    profile_sync_enabled: bool = False
    profile_sync_interval_hours: int = 24
    delete_mode: Literal["hard_delete", "soft_delete"] = "hard_delete"
    ignore_bots: bool = True
    ignore_service_messages: bool = True
    max_media_size_mb: int = 50
    message_filter_mode: Literal["all", "text_only", "min_length"] = "all"
    min_message_length: int = 0

    sessions_dir: Path = Path("sessions")
    media_cache_dir: Path = Path("media_cache")

    tg_proxy: str = ""
    tg_proxy_type: str = "http"

    @property
    def resolved_sessions_dir(self) -> Path:
        return _resolve_data_path(self.sessions_dir)

    @property
    def resolved_media_cache_dir(self) -> Path:
        return _resolve_data_path(self.media_cache_dir)

    @property
    def max_media_size_bytes(self) -> int:
        return self.max_media_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    for key, value in _runtime_overrides.items():
        if hasattr(settings, key):
            setattr(settings, key, value)
    return settings


def update_runtime_settings(updates: dict[str, Any]) -> Settings:
    _runtime_overrides.update(updates)
    get_settings.cache_clear()
    return get_settings()
