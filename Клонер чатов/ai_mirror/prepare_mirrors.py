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
from telethon.tl.functions.channels import JoinChannelRequest, LeaveChannelRequest

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


async def leave_chat(client: TelegramClient, username: str) -> str:
    if not username:
        return "нет username"
    try:
        channel = await client.get_entity(username)
        await client(LeaveChannelRequest(channel=channel))
        return "вышел"
    except Exception as exc:
        err = str(exc).lower()
        if "not a member" in err or "user_not_participant" in err:
            return "не был в чате"
        return f"ошибка: {exc}"


async def run(config_path: Path, *, report_fraction: float | None = None) -> None:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    all_sessions = list(config.get("tech_sessions", []))
    routes = config["routes"]

    task_routes = [r for r in routes if r.get("type") == "task"]
    report_routes = [r for r in routes if r.get("type") == "report"]

    if report_fraction is not None:
        cut = max(1, int(len(all_sessions) * report_fraction))
        report_sessions = all_sessions[:cut]
        task_sessions = all_sessions
        print(
            f"Режим split: задания — {len(task_sessions)} акк., "
            f"отчёты — {len(report_sessions)} акк."
        )
    else:
        report_sessions = all_sessions
        task_sessions = all_sessions

    api_id, api_hash = api_credentials()

    async def load_mirrors(route_list: list[dict]) -> dict[str, str]:
        probe = TelegramClient(ensure_local_session("listener_main"), api_id, api_hash)
        await probe.connect()
        out: dict[str, str] = {}
        for r in route_list:
            un = r.get("mirror_username", "")
            if not un:
                ent = await probe.get_entity(int(r["mirror_chat_id"]))
                un = getattr(ent, "username", "") or ""
            out[un] = getattr(
                await probe.get_entity(un or int(r["mirror_chat_id"])),
                "title",
                un,
            )
            print(f"  @{un}: {out[un]}")
        await probe.disconnect()
        return out

    task_mirrors: dict[str, str] = {}
    report_mirrors: dict[str, str] = {}
    if task_routes:
        print("\nЧаты заданий:")
        task_mirrors = await load_mirrors(task_routes)
    if report_routes:
        print("\nЧаты отчётов:")
        report_mirrors = await load_mirrors(report_routes)

    leave_from_reports = set(all_sessions) - set(report_sessions)

    for session_name in all_sessions:
        client = TelegramClient(ensure_local_session(session_name), api_id, api_hash)
        await client.connect()
        if not await client.is_user_authorized():
            print(f"[{session_name}] не авторизован — пропуск")
            await client.disconnect()
            continue
        me = await client.get_me()
        print(f"\n{session_name} ({me.first_name})")

        if session_name in task_sessions:
            for un in task_mirrors:
                print(f"  [задание] @{un}: {await join_chat(client, un)}")
                await asyncio.sleep(0.4)

        if session_name in report_sessions:
            for un in report_mirrors:
                print(f"  [отчёт] @{un}: {await join_chat(client, un)}")
                await asyncio.sleep(0.4)
        elif session_name in leave_from_reports and report_mirrors:
            for un in report_mirrors:
                print(f"  [отчёт] @{un}: {await leave_chat(client, un)}")
                await asyncio.sleep(0.4)

        await client.disconnect()

    print("\nГотово.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default=str(ROOT / "multi_config.verdi7.json"))
    p.add_argument(
        "--report-fraction",
        type=float,
        default=None,
        help="доля аккаунтов в чатах отчётов (0.5 = половина); остальные только в заданиях",
    )
    args = p.parse_args()
    asyncio.run(run(Path(args.config), report_fraction=args.report_fraction))


if __name__ == "__main__":
    main()
