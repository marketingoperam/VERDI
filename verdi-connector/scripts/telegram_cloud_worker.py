"""Long-lived Telethon worker for VERDI Connector (Render / local).

Protocol (newline-delimited JSON):
  stdin  -> {"cmd":"send","reqId":"...","peerId":"123","text":"..."}
           {"cmd":"sync","reqId":"...","limitDialogs":30,"limitMessages":40}
  stdout <- {"type":"ready","session":"...","meId":"...","username":"..."}
           {"type":"inbound", ...}
           {"type":"send_ok","reqId":"...","telegramMessageId":"...","sentAt":"..."}
           {"type":"send_err","reqId":"...","error":"..."}
           {"type":"sync_dialog", ...}
           {"type":"sync_done","reqId":"...","dialogs":N}
           {"type":"log","level":"info|warn|error","message":"..."}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import timezone
from pathlib import Path

from telethon import TelegramClient, events
from telethon.tl.types import User


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def log(level: str, message: str) -> None:
    emit({"type": "log", "level": level, "message": message})


def resolve_session_path(session: str, sessions_dir: Path) -> Path:
    candidates = [
        sessions_dir / f"{session}.session",
        sessions_dir / session,
        Path("/etc/secrets") / f"{session}.session",
        Path("/etc/secrets") / session,
        Path.cwd() / f"{session}.session",
        Path.cwd() / session,
    ]
    for path in candidates:
        if path.is_file():
            return path if path.suffix == ".session" else path
    # Telethon appends .session — return stem path without suffix for client ctor
    preferred = sessions_dir / session
    preferred.parent.mkdir(parents=True, exist_ok=True)
    return preferred


def prepare_session_file(session: str, sessions_dir: Path) -> Path:
    """Materialize Telethon SQLite session (needs a writable path).

    Important: never overwrite an existing writable session on every restart —
    Telethon updates the SQLite file after connect; rewriting stale B64 races
    and can raise 'too many values to unpack'.
    """
    import base64

    sessions_dir.mkdir(parents=True, exist_ok=True)
    dest = sessions_dir / f"{session}.session"

    if dest.is_file() and dest.stat().st_size > 0:
        log("info", f"Using existing session file {dest}")
        return sessions_dir / session

    b64 = (os.environ.get("TELEGRAM_SESSION_B64") or "").strip()
    if b64:
        dest.write_bytes(base64.b64decode(b64))
        log("info", f"Wrote session from TELEGRAM_SESSION_B64 -> {dest}")
        return sessions_dir / session

    secret_candidates = [
        Path("/etc/secrets") / f"{session}.session",
        Path("/etc/secrets") / session,
        Path("/etc/secrets") / f"{session}.session.b64",
    ]
    for src in secret_candidates:
        if not src.is_file():
            continue
        raw = src.read_bytes()
        if src.name.endswith(".b64"):
            raw = base64.b64decode(raw)
        dest.write_bytes(raw)
        log("info", f"Copied session from {src} -> {dest}")
        return sessions_dir / session

    return resolve_session_path(session, sessions_dir)


async def handle_send(client: TelegramClient, req: dict) -> None:
    req_id = req.get("reqId", "")
    try:
        peer_id = int(str(req["peerId"]))
        text = str(req.get("text") or "").strip()
        if not text:
            raise RuntimeError("empty text")
        entity = await client.get_entity(peer_id)
        msg = await client.send_message(entity, text)
        sent_at = msg.date
        if sent_at.tzinfo is None:
            sent_at = sent_at.replace(tzinfo=timezone.utc)
        emit(
            {
                "type": "send_ok",
                "reqId": req_id,
                "telegramMessageId": str(msg.id),
                "sentAt": sent_at.isoformat(),
            }
        )
    except Exception as exc:  # noqa: BLE001
        emit({"type": "send_err", "reqId": req_id, "error": str(exc)})


async def handle_sync(client: TelegramClient, session_name: str, me_id: int, req: dict) -> None:
    req_id = req.get("reqId", "")
    limit_dialogs = int(req.get("limitDialogs") or 30)
    limit_messages = int(req.get("limitMessages") or 40)
    count = 0
    async for dialog in client.iter_dialogs(limit=limit_dialogs):
        entity = dialog.entity
        if not isinstance(entity, User) or entity.bot:
            continue
        messages = await client.get_messages(entity, limit=limit_messages)
        payload_messages = []
        for msg in reversed(list(messages)):
            if not msg.message:
                continue
            sent_at = msg.date
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            payload_messages.append(
                {
                    "direction": "outbound" if msg.out else "inbound",
                    "body": msg.message,
                    "telegramMessageId": str(msg.id),
                    "sentAt": sent_at.isoformat(),
                }
            )
        if not payload_messages:
            continue
        emit(
            {
                "type": "sync_dialog",
                "reqId": req_id,
                "sessionName": session_name,
                "externalChatId": str(entity.id),
                "peerTelegramUserId": str(entity.id),
                "username": entity.username,
                "firstName": entity.first_name,
                "lastName": entity.last_name,
                "messages": payload_messages,
            }
        )
        count += 1
    emit({"type": "sync_done", "reqId": req_id, "dialogs": count, "meId": str(me_id)})


async def stdin_loop(client: TelegramClient, session_name: str, me_id: int, queue: asyncio.Queue) -> None:
    loop = asyncio.get_event_loop()
    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if line == "":
            log("warn", "stdin closed — stopping worker")
            await queue.put(None)
            return
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            log("warn", f"invalid stdin JSON: {line[:120]}")
            continue
        cmd = req.get("cmd")
        if cmd == "send":
            await handle_send(client, req)
        elif cmd == "sync":
            await handle_sync(client, session_name, me_id, req)
        elif cmd == "ping":
            emit({"type": "pong", "reqId": req.get("reqId", "")})
        else:
            log("warn", f"unknown cmd: {cmd}")


async def main_async(args: argparse.Namespace) -> None:
    api_id = int(os.environ.get("TELEGRAM_API_ID") or args.api_id or "0")
    api_hash = os.environ.get("TELEGRAM_API_HASH") or args.api_hash or ""
    session = os.environ.get("TELEGRAM_SESSION") or args.session
    sessions_dir = Path(
        os.environ.get("TELEGRAM_SESSIONS_DIR")
        or args.sessions_dir
        or "/var/data/telegram-sessions"
    )

    if not api_id or not api_hash:
        raise RuntimeError("TELEGRAM_API_ID / TELEGRAM_API_HASH required")

    session_base = prepare_session_file(session, sessions_dir)
    client = TelegramClient(str(session_base), api_id, api_hash)
    await client.connect()
    if not await client.is_user_authorized():
        raise RuntimeError(f"Session {session} is not authorized")

    me = await client.get_me()
    me_id = int(me.id)
    emit(
        {
            "type": "ready",
            "session": session,
            "meId": str(me_id),
            "username": me.username,
            "firstName": me.first_name,
        }
    )

    @client.on(events.NewMessage(incoming=True))
    async def on_new_message(event: events.NewMessage.Event) -> None:  # noqa: N802
        if not event.is_private:
            return
        sender = await event.get_sender()
        if not isinstance(sender, User) or sender.bot:
            return
        text = event.raw_text or ""
        if not text.strip():
            return
        received_at = event.message.date
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=timezone.utc)
        emit(
            {
                "type": "inbound",
                "sessionName": session,
                "externalChatId": str(sender.id),
                "telegramMessageId": str(event.message.id),
                "senderTelegramUserId": str(sender.id),
                "senderUsername": sender.username,
                "senderFirstName": sender.first_name,
                "senderLastName": sender.last_name,
                "body": text,
                "receivedAt": received_at.isoformat(),
            }
        )

    stop_queue: asyncio.Queue = asyncio.Queue()
    reader = asyncio.create_task(stdin_loop(client, session, me_id, stop_queue))
    await stop_queue.get()
    reader.cancel()
    await client.disconnect()


def main() -> None:
    import traceback

    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="listener_main")
    parser.add_argument("--api-id", default="")
    parser.add_argument("--api-hash", default="")
    parser.add_argument("--sessions-dir", default="")
    args = parser.parse_args()
    try:
        asyncio.run(main_async(args))
    except Exception as exc:  # noqa: BLE001
        tb = traceback.format_exc()
        emit({"type": "fatal", "error": str(exc), "traceback": tb[-1500:]})
        print(json.dumps({"error": str(exc), "traceback": tb[-1500:]}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
