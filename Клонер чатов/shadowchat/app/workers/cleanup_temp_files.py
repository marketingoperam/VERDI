import time
from pathlib import Path

import structlog

from app.config import get_settings
from app.logging_config import setup_logging

logger = structlog.get_logger()

MAX_AGE_SECONDS = 3600


def cleanup_stale_media() -> int:
    settings = get_settings()
    cache_dir = settings.resolved_media_cache_dir
    if not cache_dir.exists():
        return 0

    removed = 0
    now = time.time()
    for path in cache_dir.iterdir():
        if not path.is_file():
            continue
        try:
            if now - path.stat().st_mtime > MAX_AGE_SECONDS:
                path.unlink()
                removed += 1
        except OSError as exc:
            logger.warning("cleanup_failed", path=str(path), error=str(exc))
    return removed


def main() -> None:
    setup_logging()
    removed = cleanup_stale_media()
    logger.info("media_cache_cleaned", removed=removed)


if __name__ == "__main__":
    main()
