"""Очистить чаты и отправить + закрепить правила."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import uuid
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

import functools

print = functools.partial(print, flush=True)

from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient, utils
from telethon.errors import FloodWaitError, RPCError
from telethon.tl.functions.channels import (
    CreateChannelRequest,
    DeleteChannelRequest,
    EditPhotoRequest,
    ToggleForumRequest,
)
from telethon.tl.functions.messages import UpdatePinnedMessageRequest
from telethon.tl.types import InputChatUploadedPhoto, MessageService

from clone_forum import get_topic_tops, message_topic_id, session_path

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
LOCAL_SESSIONS = ROOT / "sessions"
LOCAL_SESSIONS.mkdir(exist_ok=True)
BATCH_FILE = ROOT / "forum_clones_batch.json"
STATE_FILE = ROOT / "forum_clone_state.json"
DEFAULT_AVATAR = ROOT / "verdi_avatar.png"


class ChatBrokenError(Exception):
    pass

RULES = """🔺ПРАВИЛА🔻

1. В день кидаем только одну ссылку до 22:00 по МСК.

2. К ссылке пишите, что требуется сделать.
Саму ссылку укорачиваем.

3. С 22 до 00 – окно тишины, посты не кидаем.
4. Перед тем, как выложить свой пост нужно пройти все предыдущие ссылки, написать «всех прошла-(ел)».
Ссылки, опубликованные после вашего поста нужно пройти до 00:00.
*если живете в др. часовом поясе или не успеваете – до 11:00 утра по МСК след. дня.

5. Проходить посты нужно каждый день, независимо от того, скидывали ли вы сегодня Свой.

6. Внимательно читайте задания участников и выполняйте согласно их просьбам.

7. Все комментарии от 4-х слов.

8. Суббота – выходной! Но если скинули пост – проходите всех.

9. «Самолет» – пересылаем на аккаунт админа.

10. Актив на сториз – выполняем.

11. Подписка на участников чата обязательна.

12. В чат «общение» скидываем скриншоты сохранений за предыдущий день до 11:00 утра.

13. Участник, не соблюдающий правила, получает предупреждение, на 3-й раз удаление.

14. Чат не должен содержать рекламы, спама и оскорблений.



🔻Дополнения к правилам🔺

2.1 ЛКС - Лайк, Комментарий, Сохранение.
ЛКССП – Лайк, Комментарий, Сохранение, Самолёт, Переход.

2.2 Ссылку укорачиваем до слеша /  или даём ссылку на профиль, указывая «последний пост».

7.1 Местоимения, союзы, предлоги и смайлы  – это не текст.

10.1 Если у участника пост есть и просит сториз в дополнение.
Проходим 2-3 сториз с быстрыми реакциями. Просмотр всех и доп активность - по желанию.

10.2 Если поста нет, просят Только сториз.
Выполняем просмотр  (быстрый, это значит на 1 сториз 1-3 секунды, да всё засчитывается), 3-5 реакции и 1 комментарий (если нужен)."""

load_dotenv(SHADOWCHAT / ".env")


def isolated_session() -> str:
    src = Path(session_path() + ".session")
    dst = LOCAL_SESSIONS / f"setup_rules_{uuid.uuid4().hex[:8]}.session"
    if src.exists():
        shutil.copy2(src, dst)
    return str(dst.with_suffix(""))


def collect_chats() -> list[dict]:
    seen: set[int] = set()
    items: list[dict] = []

    def add(cid: int, title: str, label: str) -> None:
        if cid in seen:
            return
        seen.add(cid)
        items.append({"id": cid, "title": title, "label": label})

    if STATE_FILE.exists():
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if s.get("mirror_chat_id"):
            add(int(s["mirror_chat_id"]), s.get("mirror_title", ""), "первая копия")

    if BATCH_FILE.exists():
        batch = json.loads(BATCH_FILE.read_text(encoding="utf-8"))
        for c in batch.get("clones", []):
            add(
                int(c["mirror_chat_id"]),
                c.get("mirror_title", ""),
                f"batch #{c.get('index', '?')}",
            )

    return items


async def api_call(client, req, label: str = ""):
    try:
        return await client(req)
    except FloodWaitError as exc:
        print(f"    пауза Telegram {exc.seconds}s ({label})")
        await asyncio.sleep(exc.seconds + 2)
        return await client(req)


async def ensure_forum(client, chat) -> None:
    ent = await client.get_entity(chat)
    if getattr(ent, "forum", False):
        return
    await api_call(
        client,
        ToggleForumRequest(channel=ent, enabled=True, tabs=False),
        "включение тем",
    )
    await asyncio.sleep(2)


async def set_avatar(client: TelegramClient, mirror, photo_path: Path) -> None:
    uploaded = await client.upload_file(str(photo_path))
    await api_call(
        client,
        EditPhotoRequest(
            channel=mirror,
            photo=InputChatUploadedPhoto(file=uploaded),
        ),
        "аватар",
    )


async def chat_is_broken(client: TelegramClient, chat) -> bool:
    ent = await client.get_entity(chat)
    if getattr(ent, "forum", False):
        return False
    test = await client.send_message(ent, ".")
    await asyncio.sleep(1)
    got = await client.get_messages(ent, ids=test.id)
    try:
        await client.delete_messages(ent, test.id)
    except Exception:
        pass
    return got is None


async def recreate_plain_chat(client: TelegramClient, info: dict) -> int:
    old_id = info["id"]
    title = info["title"] or "VERDI COMMUNITY | Взаимная активность Инстаграм · копия"
    try:
        old = await client.get_entity(old_id)
        await api_call(client, DeleteChannelRequest(channel=old), "удаление старой группы")
        print("  старая группа удалена")
        await asyncio.sleep(3)
    except Exception as exc:
        print(f"  предупреждение при удалении: {exc}")

    result = await api_call(
        client,
        CreateChannelRequest(title=title, megagroup=True, about=""),
        "создание группы",
    )
    mirror = await client.get_entity(result.chats[0])
    if DEFAULT_AVATAR.exists():
        await set_avatar(client, mirror, DEFAULT_AVATAR)
        print("  аватар установлен")
    return utils.get_peer_id(mirror)


async def clear_chat(client: TelegramClient, chat) -> int:
    deleted = 0
    async for msg in client.iter_messages(chat):
        if isinstance(msg, MessageService):
            continue
        try:
            await client.delete_messages(chat, msg.id)
            deleted += 1
            if deleted % 10 == 0:
                print(f"    ... удалено {deleted}")
            await asyncio.sleep(0.2)
        except FloodWaitError as exc:
            print(f"    пауза {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 1)
        except Exception:
            continue
    return deleted


async def post_and_pin(client: TelegramClient, chat) -> int:
    ent = await client.get_entity(chat)
    if getattr(ent, "forum", False):
        msg = await client.send_message(ent, RULES, reply_to=1)
    else:
        msg = await client.send_message(ent, RULES)
    await asyncio.sleep(2)
    got = await client.get_messages(ent, ids=msg.id)
    if got is None:
        raise ChatBrokenError("сообщение не видно в чате")
    try:
        await client.pin_message(ent, msg, notify=False)
    except RPCError:
        await api_call(
            client,
            UpdatePinnedMessageRequest(peer=ent, id=msg.id, silent=True),
            "закреп",
        )
    return msg.id


async def setup_chat(client: TelegramClient, info: dict, *, recreate: bool) -> bool:
    print(f"\n[{info['label']}] {info['title']}")
    chat_id = info["id"]
    try:
        chat = await client.get_entity(chat_id)
    except Exception as exc:
        print(f"  ✗ чат недоступен: {exc}")
        if not recreate:
            return False
        chat = None

    broken = recreate or chat is None
    if chat is not None and not broken:
        broken = await chat_is_broken(client, chat)

    if broken:
        print("  пересоздаю группу как обычный чат...")
        chat_id = await recreate_plain_chat(client, info)
        chat = await client.get_entity(chat_id)
        if info["label"] == "первая копия" and STATE_FILE.exists():
            state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            state["mirror_chat_id"] = chat_id
            state["mirror_title"] = getattr(chat, "title", info["title"])
            state["topic_map"] = {}
            state["last_msg"] = {}
            state["recreated_at"] = datetime.now().isoformat(timespec="seconds")
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        ent = await client.get_entity(chat)
        if getattr(ent, "forum", False):
            await ensure_forum(client, chat)
        n = await clear_chat(client, chat)
        print(f"  удалено сообщений: {n}")

    try:
        mid = await post_and_pin(client, chat)
        print(f"  ✓ правила отправлены и закреплены (msg #{mid})")
        return True
    except FloodWaitError as exc:
        print(f"  пауза {exc.seconds}s")
        await asyncio.sleep(exc.seconds + 2)
        mid = await post_and_pin(client, chat)
        print(f"  ✓ правила отправлены и закреплены (msg #{mid})")
        return True
    except ChatBrokenError as exc:
        print(f"  ✗ {exc}")
        return False
    except RPCError as exc:
        print(f"  ✗ {exc}")
        return False


async def run(only_first: bool, recreate: bool) -> None:
    chats = collect_chats()
    if only_first:
        chats = [c for c in chats if c["label"] == "первая копия"]

    client = TelegramClient(
        isolated_session(),
        int(os.environ["LISTENER_API_ID"]),
        os.environ["LISTENER_API_HASH"],
    )
    await client.connect()
    if not await client.is_user_authorized():
        print("listener_main не авторизован")
        return

    me = await client.get_me()
    print(f"Аккаунт: {me.first_name} (@{me.username})")
    print(f"Чатов: {len(chats)}")

    ok = 0
    for info in chats:
        if await setup_chat(client, info, recreate=recreate):
            ok += 1
        await asyncio.sleep(5)

    if STATE_FILE.exists() and only_first:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state["last_msg"] = {}
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    await client.disconnect()
    print(f"\nГотово: {ok}/{len(chats)}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--only-first", action="store_true", help="Только первая копия")
    p.add_argument(
        "--recreate",
        action="store_true",
        help="Пересоздать повреждённую группу как обычный чат",
    )
    args = p.parse_args()
    asyncio.run(run(args.only_first, args.recreate))


if __name__ == "__main__":
    main()
