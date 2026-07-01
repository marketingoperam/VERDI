"""Простой клонер: один техаккаунт копирует имя, аватар и сообщения."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

import functools
print = functools.partial(print, flush=True)

from dotenv import load_dotenv
from telethon import TelegramClient, events, utils
from telethon.errors import FloodWaitError
from telethon.tl.functions.account import UpdateProfileRequest
from telethon.tl.functions.users import GetFullUserRequest
from telethon.tl.functions.photos import DeletePhotosRequest, UploadProfilePhotoRequest
from telethon.tl.types import MessageService, User

ROOT = Path(__file__).resolve().parent
SHADOWCHAT = ROOT.parent / "shadowchat"
sys.path.insert(0, str(SHADOWCHAT))

load_dotenv(ROOT / ".env")
load_dotenv(SHADOWCHAT / ".env")

from brain import MirrorBrain

CACHE = ROOT / "cache"
CACHE.mkdir(exist_ok=True)
LOCAL_SESSIONS = ROOT / "sessions"
LOCAL_SESSIONS.mkdir(exist_ok=True)

@dataclass
class ProfileState:
    last_name_key: tuple[int, str, str] | None = None
    avatar_by_sender: dict[int, str] = field(default_factory=dict)
    last_sender_id: int | None = None


_profile_states: dict[str, ProfileState] = {}
# совместимость со старым одиночным режимом
_last_applied_name: tuple[int, str, str] | None = None
_avatar_hashes: dict[int, str] = {}


def profile_state(client: TelegramClient, profile_key: str | None = None) -> ProfileState:
    key = profile_key or Path(client.session.filename).stem
    if key not in _profile_states:
        _profile_states[key] = ProfileState()
    return _profile_states[key]


def api_credentials() -> tuple[int, str]:
    api_id = int(os.environ["LISTENER_API_ID"])
    api_hash = os.environ["LISTENER_API_HASH"]
    return api_id, api_hash


def ensure_local_session(session_name: str) -> str:
    """Отдельная копия .session — не конфликтует с ShadowChat."""
    src = SHADOWCHAT / "sessions" / f"{session_name}.session"
    dst = LOCAL_SESSIONS / f"{session_name}.session"
    if src.exists() and (not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime):
        shutil.copy2(src, dst)
    return str(LOCAL_SESSIONS / session_name)


def same_chat(chat_id: int, entity) -> bool:
    try:
        return utils.get_peer_id(chat_id) == utils.get_peer_id(entity)
    except Exception:
        return chat_id == getattr(entity, "id", None)


async def refresh_sender(client: TelegramClient, sender: User) -> User:
    try:
        full = await client(GetFullUserRequest(sender))
        if isinstance(full.users[0], User):
            return full.users[0]
    except Exception:
        pass
    try:
        entity = await client.get_entity(sender.id)
        if isinstance(entity, User):
            return entity
    except Exception:
        pass
    return sender


async def download_sender_avatar(client: TelegramClient, sender: User, dest: Path) -> str | None:
    path = await client.download_profile_photo(sender, file=str(dest))
    if path:
        return path
    photos = await client.get_profile_photos(sender, limit=1)
    if photos:
        return await client.download_media(photos[0], file=str(dest))
    return None


async def sync_profile(
    client: TelegramClient,
    sender: User,
    *,
    sync_name: bool,
    sync_avatar: bool,
    avatar_client: TelegramClient | None = None,
    profile_key: str | None = None,
) -> None:
    global _last_applied_name
    st = profile_state(client, profile_key)
    sender_changed = st.last_sender_id != sender.id
    st.last_sender_id = sender.id

    if sync_name:
        me = await client.get_me()
        first = (sender.first_name or "")[:64]
        last = (sender.last_name or "")[:64]
        name_key = (sender.id, first, last)
        if (st.last_name_key != name_key or sender_changed) and (
            me.first_name != first or (me.last_name or "") != last
        ):
            await client(UpdateProfileRequest(first_name=first, last_name=last))
            st.last_name_key = name_key
            _last_applied_name = name_key
            print(f"  имя: {first} {last}".strip())
        elif me.first_name == first and (me.last_name or "") == last:
            st.last_name_key = name_key
            _last_applied_name = name_key

    if not sync_avatar:
        return

    dl = avatar_client or client
    avatar_file = CACHE / f"avatar_{sender.id}.jpg"
    path = await download_sender_avatar(dl, sender, avatar_file)
    me_photos = await client.get_profile_photos("me", limit=100)

    if not path:
        print("  аватар: у отправителя нет фото в Telegram")
        if me_photos and (sender_changed or st.avatar_by_sender.get(sender.id)):
            await client(
                DeletePhotosRequest(id=[utils.get_input_photo(p) for p in me_photos])
            )
            st.avatar_by_sender.pop(sender.id, None)
            print("  аватар техаккаунта сброшен")
        return

    data = Path(path).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if not sender_changed and st.avatar_by_sender.get(sender.id) == digest:
        return

    uploaded = await client.upload_file(path)
    if me_photos:
        await client(
            DeletePhotosRequest(id=[utils.get_input_photo(p) for p in me_photos])
        )

    async def _upload() -> None:
        await client(UploadProfilePhotoRequest(file=uploaded))

    try:
        await _upload()
    except FloodWaitError as exc:
        print(f"  аватар: пауза Telegram {exc.seconds}s")
        await asyncio.sleep(exc.seconds + 1)
        await _upload()

    st.avatar_by_sender[sender.id] = digest
    _avatar_hashes[sender.id] = digest
    print("  аватар обновлён")


async def send_to_mirror(
    client: TelegramClient,
    message,
    mirror_entity,
    *,
    sync_name: bool,
    sync_avatar: bool,
    mirror_topic_id: int | None = None,
    brain: MirrorBrain | None = None,
    use_ai: bool = False,
) -> None:
    sender = await message.get_sender()
    if not isinstance(sender, User):
        return

    sender = await refresh_sender(client, sender)

    copy_profile = sync_name or sync_avatar
    copy_message = True

    if use_ai and brain:
        try:
            decision = await brain.decide(
                sender_name=" ".join(
                    p for p in (sender.first_name, sender.last_name) if p
                ).strip()
                or "Unknown",
                sender_is_bot=bool(sender.bot),
                has_text=bool(message.message),
                has_media=bool(message.media),
                is_service=isinstance(message, MessageService),
            )
            copy_profile = copy_profile and decision["copy_profile"]
            copy_message = decision["copy_message"]
            if decision.get("reason"):
                print(f"  ИИ: {decision['reason']}")
        except Exception as exc:
            print(f"  ИИ недоступен, копирую напрямую: {exc}")

    if not copy_message:
        print("  ИИ: пропуск")
        return

    if copy_profile:
        try:
            await sync_profile(
                client,
                sender,
                sync_name=sync_name,
                sync_avatar=sync_avatar,
            )
        except Exception as exc:
            print(f"  профиль: ошибка — {exc}")

    text = message.message or ""

    if message.media:
        file_path = await client.download_media(message, file=str(CACHE / f"msg_{message.id}"))
        if file_path:
            await client.send_file(
                mirror_entity,
                file_path,
                caption=text or None,
                reply_to=mirror_topic_id,
            )
            Path(file_path).unlink(missing_ok=True)
            return

    if text:
        await client.send_message(mirror_entity, text, reply_to=mirror_topic_id)


async def send_to_mirror_pooled(
    listener: TelegramClient,
    tech: TelegramClient,
    message,
    mirror_chat_id: int,
    *,
    sync_name: bool,
    sync_avatar: bool,
    mirror_topic_id: int | None = None,
    mirror_username: str | None = None,
    tech_session_name: str | None = None,
) -> None:
    """listener читает источник, tech публикует в зеркало (разные сессии)."""
    sender = await message.get_sender()
    if not isinstance(sender, User):
        return

    sender = await refresh_sender(listener, sender)

    if sync_name or sync_avatar:
        try:
            await sync_profile(
                tech,
                sender,
                sync_name=sync_name,
                sync_avatar=sync_avatar,
                avatar_client=listener,
                profile_key=tech_session_name,
            )
            await asyncio.sleep(2)
        except Exception as exc:
            print(f"  профиль: ошибка — {exc}")

    try:
        mirror = await tech.get_entity(mirror_chat_id)
    except (ValueError, TypeError):
        if not mirror_username:
            raise
        mirror = await tech.get_entity(mirror_username)

    text = message.message or ""

    if message.media:
        file_path = await listener.download_media(
            message, file=str(CACHE / f"pool_{message.id}_{message.chat_id}")
        )
        if file_path:
            await tech.send_file(
                mirror,
                file_path,
                caption=text or None,
                reply_to=mirror_topic_id,
            )
            Path(file_path).unlink(missing_ok=True)
            return

    if text:
        await tech.send_message(mirror, text, reply_to=mirror_topic_id)


async def resolve_clone_user(
    client: TelegramClient,
    config: dict,
) -> tuple[int | None, str | None]:
    user_id = config.get("clone_user_id")
    if user_id is not None:
        user_id = int(user_id)
        try:
            user = await client.get_entity(user_id)
            if isinstance(user, User):
                name = " ".join(p for p in (user.first_name, user.last_name) if p)
                return user.id, name
        except Exception:
            pass
        return user_id, None

    username = (config.get("clone_username") or "").strip().lstrip("@")
    if not username:
        return None, None

    user = await client.get_entity(username)
    if isinstance(user, User):
        name = " ".join(p for p in (user.first_name, user.last_name) if p)
        return user.id, name
    return None, None


async def ensure_clone_user(
    client: TelegramClient,
    source_entity,
    user_id: int,
) -> User | None:
    try:
        user = await client.get_entity(user_id)
        if isinstance(user, User):
            return user
    except Exception:
        pass
    try:
        async for user in client.iter_participants(source_entity, limit=200):
            if user.id == user_id:
                return user
    except Exception:
        pass
    async for msg in client.iter_messages(source_entity, limit=100):
        if msg.sender_id == user_id:
            sender = await msg.get_sender()
            if isinstance(sender, User):
                return sender
    return None


async def bootstrap_bound_profile(
    client: TelegramClient,
    source_entity,
    user_id: int,
    *,
    sync_name: bool,
    sync_avatar: bool,
) -> None:
    global _last_applied_name
    _last_applied_name = None
    _avatar_hashes.pop(user_id, None)
    user = await ensure_clone_user(client, source_entity, user_id)
    if user:
        await sync_profile(client, user, sync_name=sync_name, sync_avatar=sync_avatar)


async def run(config: dict) -> None:
    api_id, api_hash = api_credentials()
    session_name = config["session_name"]
    source_id = int(config["source_chat_id"])
    mirror_id = int(config["mirror_chat_id"])
    use_ai = bool(config.get("use_ai"))
    brain = MirrorBrain() if use_ai else None

    sync_profile = bool(config.get("sync_profile"))
    sync_name = bool(config.get("sync_name", sync_profile))
    sync_avatar = bool(config.get("sync_avatar", sync_profile))

    client = TelegramClient(
        ensure_local_session(session_name),
        api_id,
        api_hash,
        sequential_updates=True,
    )
    await client.connect()

    if not await client.is_user_authorized():
        print("Аккаунт не авторизован. Запустите вход через shadowchat или auth_session.py")
        return

    me = await client.get_me()
    print("=" * 44)
    print("  AI Mirror — простой клонер")
    print("=" * 44)
    print(f"Аккаунт: {me.first_name} ({me.phone})")
    print(f"Источник: {source_id}")
    print(f"Зеркало:  {mirror_id}")
    print(f"Имя: {'да' if sync_name else 'нет'} | Аватар: {'да' if sync_avatar else 'нет'}")
    clone_user_id, clone_user_name = await resolve_clone_user(client, config)
    if clone_user_id:
        label = clone_user_name or str(clone_user_id)
        print(f"Закреплён за: {label} (id={clone_user_id})")
    else:
        print("Закреплён за: все отправители (укажите clone_user_id в config)")
    print(f"ИИ (Gonka): {'да' if use_ai else 'нет'}")
    if use_ai and brain:
        try:
            ping = await brain.ping()
            print(f"  Gonka: {ping.strip()}")
        except Exception as exc:
            print(f"  Gonka: ошибка — {exc}")
    print("Ожидаю сообщения... Ctrl+C для остановки\n")

    source_entity = await client.get_entity(source_id)
    mirror_entity = await client.get_entity(mirror_id)

    for ent, label in ((source_entity, "источник"), (mirror_entity, "зеркало")):
        print(f"  {label}: OK — {getattr(ent, 'title', ent.id)}")

    if clone_user_id and (sync_name or sync_avatar):
        try:
            await bootstrap_bound_profile(
                client,
                source_entity,
                clone_user_id,
                sync_name=sync_name,
                sync_avatar=sync_avatar,
            )
            print("  профиль техаккаунта выставлен под закреплённого пользователя")
        except Exception as exc:
            print(f"  не удалось выставить профиль при старте: {exc}")

    # Прогрев диалогов — Telethon надёжнее ловит апдейты
    await client.get_dialogs(limit=50)

    @client.on(events.NewMessage())
    async def on_message(event):
        if not same_chat(event.chat_id, source_entity):
            return
        if config.get("ignore_service_messages") and isinstance(event.message, MessageService):
            return
        sender = await event.message.get_sender()
        if config.get("ignore_bots") and isinstance(sender, User) and sender.bot:
            return
        if clone_user_id and (not isinstance(sender, User) or sender.id != clone_user_id):
            who = getattr(sender, "id", "?")
            print(f"  пропуск: отправитель {who} не закреплённый профиль")
            return

        try:
            print(f"→ сообщение #{event.message.id} из chat {event.chat_id}")
            await send_to_mirror(
                client,
                event.message,
                mirror_entity,
                sync_name=sync_name,
                sync_avatar=sync_avatar,
                brain=brain,
                use_ai=use_ai,
            )
            print("  отправлено в зеркало")
        except Exception as exc:
            err = str(exc)
            if "banned from sending" in err.lower():
                print("  ошибка: техаккаунт ЗАБЛОКИРОВАН в зеркальном чате")
                print("  → в Telegram: зеркало → участники → разблокировать +91 аккаунт")
            else:
                print(f"  ошибка: {exc}")

    await client.run_until_disconnected()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.json"))
    args = parser.parse_args()
    with open(args.config, encoding="utf-8") as f:
        config = json.load(f)
    asyncio.run(run(config))


if __name__ == "__main__":
    main()
