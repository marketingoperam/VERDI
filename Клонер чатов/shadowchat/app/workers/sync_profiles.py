import asyncio
import time
from pathlib import Path

import structlog

from app.config import get_settings
from app.db import async_session_factory
from app.logging_config import setup_logging
from app.telegram.profile_sync import run_profile_sync_worker
from app.telegram.session_pool import SessionPoolManager

logger = structlog.get_logger()


async def main() -> None:
    setup_logging()
    settings = get_settings()
    session_pool = SessionPoolManager(async_session_factory)
    logger.info("profile_sync_worker_starting")
    await run_profile_sync_worker(async_session_factory, session_pool)


if __name__ == "__main__":
    asyncio.run(main())
