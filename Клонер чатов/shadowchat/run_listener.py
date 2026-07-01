"""Run Telegram listener as standalone process."""

import asyncio

from app.logging_config import setup_logging
from app.telegram.listener import run_listener


def main() -> None:
    setup_logging()
    asyncio.run(run_listener())


if __name__ == "__main__":
    main()
