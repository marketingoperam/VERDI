"""Export StringSession from inviting DB for Render TELEGRAM_SESSION_STRING_<name>."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export inviting account StringSession for Render")
    parser.add_argument("account_name", help="Account name, e.g. outreach1")
    parser.add_argument("--db", default="inviting.sqlite", help="Path to inviting.sqlite")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    row = sqlite3.connect(db_path).execute(
        "SELECT session_string, is_authorized FROM accounts WHERE name = ?",
        (args.account_name,),
    ).fetchone()
    if not row or not row[0]:
        raise SystemExit(f"Account '{args.account_name}' has no session_string in DB")

    session_string = row[0]
    env_key = f"TELEGRAM_SESSION_STRING_{args.account_name}"
    out = Path(f".telegram-sessions/{args.account_name}.string.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(session_string, encoding="utf-8")

    print(f"OK: saved to {out}")
    print(f"Render env key: {env_key}")
    print("Add account to TELEGRAM_SESSIONS, e.g. listener_main,tech_4,tech_5,tech_6,outreach1")
    print("WARNING: do not run the same outreach session locally and on Render at once (AuthKeyDuplicated).")


if __name__ == "__main__":
    main()
