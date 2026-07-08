"""Import one inviting outreach chat into Render Operator Inbox."""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.sessions import StringSession

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "inviting.sqlite"


def api_request(base_url: str, method: str, path: str, token: str | None = None, body: dict | None = None) -> dict:
    url = f"{base_url.rstrip('/')}/api{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def login(base_url: str, email: str, password: str) -> str:
    return api_request(base_url, "POST", "/auth/login", body={"email": email, "password": password})["accessToken"]


async def resolve_user(username: str, api_id: int, api_hash: str, session_string: str):
    client = TelegramClient(StringSession(session_string), api_id, api_hash)
    await client.connect()
    ent = await client.get_entity(username)
    await client.disconnect()
    return ent


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="operamadmin")
    parser.add_argument("--session", default="outreach1")
    parser.add_argument("--api", default="https://verdi-connector-api.onrender.com")
    parser.add_argument("--email", default="andf1n@verdi.local")
    parser.add_argument("--password", default="admin123")
    args = parser.parse_args()

    if not DB.exists():
        raise SystemExit(f"DB not found: {DB}")

    conn = sqlite3.connect(DB)
    acc = conn.execute(
        "SELECT session_string FROM accounts WHERE name=? AND is_authorized=1",
        (args.session,),
    ).fetchone()
    if not acc or not acc[0]:
        raise SystemExit(f"Account {args.session} not authorized in inviting DB")

    import os

    api_id = int(os.environ.get("INV_TG_API_ID") or 30268202)
    api_hash = os.environ.get("INV_TG_API_HASH") or "cf9ba5f50a18310f0bf22ae9457ed5a1"

    ent = await resolve_user(args.username, api_id, api_hash, acc[0])
    user_id = int(ent.id)
    conn.execute("UPDATE invite_targets SET user_id=? WHERE username=?", (user_id, args.username))
    conn.commit()

    row = conn.execute("SELECT value FROM app_settings WHERE key='outreach_message'").fetchone()
    body = (row[0] if row else "") or "Привет! Добавили вас в чат — напишите, если есть вопросы."

    token = login(args.api, args.email, args.password)
    sent_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "sessionName": args.session,
        "externalChatId": str(user_id),
        "peerTelegramUserId": str(user_id),
        "username": ent.username or args.username,
        "firstName": ent.first_name,
        "lastName": ent.last_name,
        "messages": [
            {
                "direction": "outbound",
                "body": body,
                "telegramMessageId": f"invite-backfill-{user_id}",
                "sentAt": sent_at,
            }
        ],
    }

    try:
        res = api_request(args.api, "POST", "/transport/import-dialog", token=token, body=payload)
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise SystemExit(exc.code) from exc

    print(json.dumps({"user_id": user_id, **res}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
