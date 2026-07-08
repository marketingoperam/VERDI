"""Импорт личных диалогов тех-аккаунта в VERDI Connector API."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from telethon import TelegramClient
from telethon.tl.types import User

ROOT = Path(__file__).resolve().parents[1]
SHADOWCHAT = ROOT.parent / "shadowchat"
sys.path.insert(0, str(SHADOWCHAT))
os.chdir(SHADOWCHAT)

from app.config import get_settings  # noqa: E402


def api_request(
    base_url: str,
    method: str,
    path: str,
    token: str | None = None,
    body: dict | None = None,
) -> dict:
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
    payload = api_request(
        base_url,
        "POST",
        "/auth/login",
        body={"email": email, "password": password},
    )
    return payload["accessToken"]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sessions",
        default="tech_13309563469",
        help="Comma-separated ShadowChat session names",
    )
    parser.add_argument("--api", default="http://127.0.0.1:3001")
    parser.add_argument("--email", default="andf1n@verdi.local")
    parser.add_argument("--password", default="admin123")
    parser.add_argument("--limit-dialogs", type=int, default=30)
    parser.add_argument("--limit-messages", type=int, default=50)
    args = parser.parse_args()

    token = login(args.api, args.email, args.password)

    settings = get_settings()
    sessions = [s.strip() for s in str(args.sessions).split(",") if s.strip()]
    imported_dialogs = 0
    imported_messages = 0

    for session_name in sessions:
        client = TelegramClient(
            str(settings.resolved_sessions_dir / session_name),
            settings.listener_api_id,
            settings.listener_api_hash,
        )
        await client.connect()
        if not await client.is_user_authorized():
            print(f"WARN: session {session_name} is not authorized, skipping", file=sys.stderr)
            await client.disconnect()
            continue

        me = await client.get_me()

        async for dialog in client.iter_dialogs(limit=args.limit_dialogs):
            entity = dialog.entity
            if not isinstance(entity, User) or entity.bot:
                continue

            messages = await client.get_messages(entity, limit=args.limit_messages)
            if not messages:
                continue

            payload_messages = []
            for msg in reversed(messages):
                if not msg.message:
                    continue
                direction = "outbound" if msg.out else "inbound"
                sent_at = msg.date
                if sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=timezone.utc)
                payload_messages.append(
                    {
                        "direction": direction,
                        "body": msg.message,
                        "telegramMessageId": str(msg.id),
                        "sentAt": sent_at.isoformat(),
                    }
                )

            if not payload_messages:
                continue

            body = {
                "sessionName": session_name,
                "externalChatId": str(entity.id),
                "peerTelegramUserId": str(entity.id),
                "username": entity.username,
                "firstName": entity.first_name,
                "lastName": entity.last_name,
                "messages": payload_messages,
            }

            try:
                result = api_request(args.api, "POST", "/transport/import-dialog", token, body)
                imported_dialogs += 1
                imported_messages += int(result.get("imported", 0))
                label = entity.username or entity.first_name or entity.id
                print(
                    f"OK @{me.username or me.id} (session={session_name}): "
                    f"dialog {label} (+{result.get('imported', 0)} msgs)"
                )
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                print(f"FAIL dialog {entity.id} (session={session_name}): HTTP {exc.code} {detail}", file=sys.stderr)

        await client.disconnect()

    print(f"Done: {imported_dialogs} dialogs, {imported_messages} new messages")


if __name__ == "__main__":
    asyncio.run(main())
