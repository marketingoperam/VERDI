"""Разовый бэкфилл: последние N сообщений из источников → зеркала (пул техаккаунтов)."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

import functools

print = functools.partial(print, flush=True)

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from run_pool import PoolRunner  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description="Разовый бэкфилл истории в зеркала")
    p.add_argument("--config", default=str(ROOT / "multi_config.verdi7.json"))
    p.add_argument("--limit", type=int, default=10, help="сообщений на маршрут")
    p.add_argument("--min-delay", type=float, default=3.0, help="мин. пауза между копиями (мин)")
    p.add_argument("--max-delay", type=float, default=10.0, help="макс. пауза между копиями (мин)")
    p.add_argument(
        "--then-live",
        dest="then_live",
        action="store_true",
        default=True,
        help="после бэкфилла запустить run_pool.py (прямой эфир, по умолчанию вкл.)",
    )
    p.add_argument(
        "--no-then-live",
        dest="then_live",
        action="store_false",
        help="только бэкфилл, без прямого эфира",
    )
    args = p.parse_args()

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    asyncio.run(
        PoolRunner(config).backfill(
            limit=args.limit,
            min_delay_min=args.min_delay,
            max_delay_min=args.max_delay,
            then_live=args.then_live,
        )
    )


if __name__ == "__main__":
    main()
