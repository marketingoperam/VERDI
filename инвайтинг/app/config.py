from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="INV_", env_file=".env", extra="ignore")

    app_host: str = "127.0.0.1"
    app_port: int = 8010

    database_url: str = "sqlite+aiosqlite:///./inviting.sqlite"

    tg_api_id: int = 0
    tg_api_hash: str = ""

    sessions_dir: str = "./sessions"

    tg_proxy: str = ""
    tg_proxy_type: str = "socks5"

    # VERDI Operator Inbox sync (Render API)
    connector_api_url: str = ""
    connector_sync_secret: str = ""

    @property
    def resolved_sessions_dir(self) -> Path:
        return Path(self.sessions_dir).resolve()


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

