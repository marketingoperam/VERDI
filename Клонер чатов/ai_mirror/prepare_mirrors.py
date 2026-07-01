"""Подключить техаккаунты к зеркальным чатам пула."""

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

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import UserAlreadyParticipantError
from telethon.tl.functions.channels import JoinChannelRequest

from run import api_credentials, ensure_local_session

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
load_dotenv(ROOT.parent / "shadowchat" / ".env")


async def join_chat(client: TelegramClient, username: str) -> str:
    if not username:
        return "нет username"
    try:
        channel = await client.get_entity(username)
        await client(JoinChannelRequest(channel=channel))
        return "вступил"
    except UserAlreadyParticipantError:
        return "уже в чате"
    except Exception as exc:
        err = str(exc)
        if "already" in err.lower() or "USER_ALREADY_PARTICIPANT" in err:
            return "уже в чате"
        return f"ошибка: {exc}"


async def run(config_path: Path) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    tech_sessions = list(config.get("tech_sessions", []))
    mirror_ids = {int(r["mirror_chat_id"]) for r in config["routes"]}

    api_id, api_hash = api_credentials()
    mirrors = {}
    usernames: dict[int, str] = {}
    probe = TelegramClient(ensure_local_session("listener_main"), api_id, api_hash)
    await probe.connect()
    for mid in mirror_ids:
        ent = await probe.get_entity(mid)
        mirrors[mid] = ent
        un = getattr(ent, "username", "") or ""
        usernames[mid] = un
        print(f"Зеркало: {getattr(ent, 'title', mid)} (@{un})")
    await probe.disconnect()

    for session_name in tech_sessions:
        client = TelegramClient(ensure_local_session(session_name), api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            print(f"[{session_name}] не авторизован — пропуск")
            await client.disconnect()
            continue
        me = await client.get_me()
        print(f"\n{session_name} ({me.first_name})")
        for mid, ent in mirrors.items():
            un = usernames[mid]
            status = await join_chat(client, un)
            print(f"  @{un}: {status}")
            await asyncio.sleep(0.5)
        await client.disconnect()

    print("\nГотово.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(ROOT / "multi_config.verdi7.json"))
    args = p.parse_args()
    asyncio.run(run(Path(args.config)))


if __name__ == "__main__":
    main()
