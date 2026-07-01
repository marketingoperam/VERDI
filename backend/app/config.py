from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[str(_ENV_FILE), str(_ROOT / "backend" / ".env"), ".env"],
        extra="ignore",
    )

    database_url: str = f"sqlite+aiosqlite:///{(_ROOT / 'data' / 'competitor_search.db').as_posix()}"
    redis_url: str = "redis://localhost:6379/0"

    ai_base_url: str = "https://proxy.gonka.gg/v1"
    ai_api_key: str = ""
    ai_model: str = "Qwen/Qwen3-235B-A22B-Instruct-2507-FP8"

    google_api_key: str = ""
    google_cx: str = ""

    yandex_api_key: str = ""
    yandex_folder_id: str = ""

    vk_access_token: str = ""

    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_session_path: str = "sessions/telegram"

    monitor_interval_hours: int = 6
    max_results_per_query: int = 10
    collector_concurrency: int = 3

    google_enabled: bool = True
    yandex_enabled: bool = True
    vk_enabled: bool = True
    telegram_enabled: bool = True

    auto_export_docx: bool = True
    auto_export_with_ai: bool = True
    report_output_dir: str = "output"


@lru_cache
def get_settings() -> Settings:
    return Settings()
