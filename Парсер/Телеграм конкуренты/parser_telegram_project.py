#!/usr/bin/env python3
"""
Парсер Telegram-проекта конкурента.

Стартует с одной ссылки (чат / канал / бот), собирает метаданные сущности,
читает сообщения, вытаскивает все t.me-ссылки и рекурсивно обходит связанные
чаты, каналы и ботов.

Требует Telegram-аккаунт (Telethon) — без него нельзя читать сообщения ботов
и закрытые чаты.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from dotenv import load_dotenv
from telethon import TelegramClient, utils
from tg_client import create_telegram_client, proxy_from_env, proxy_label
from telethon.errors import (
    ChannelPrivateError,
    FloodWaitError,
    InviteHashExpiredError,
    InviteHashInvalidError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)
from telethon.tl.custom.message import Message
from telethon.tl.functions.messages import CheckChatInviteRequest
from telethon.tl.types import (
    Channel,
    Chat,
    ChatInvite,
    ChatInviteAlready,
    ChatInvitePeek,
    MessageEntityTextUrl,
    MessageEntityUrl,
    User,
)

TELEGRAM_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_+][A-Za-z0-9_+\-]*)",
    flags=re.IGNORECASE,
)
INVITE_LINK_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:\+|joinchat/)([A-Za-z0-9_\-]+)",
    flags=re.IGNORECASE,
)
AT_USERNAME_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{3,31})")

BOT_COMMANDS = ("/start", "/menu", "/help")


@dataclass
class EntityRecord:
    key: str
    url: str
    username: str = ""
    invite_hash: str = ""
    entity_type: str = ""
    title: str = ""
    description: str = ""
    members_count: int | None = None
    is_bot: bool = False
    is_verified: bool = False
    is_scam: bool = False
    is_fake: bool = False
    is_private: bool = False
    discovered_from: list[str] = field(default_factory=list)
    depth: int = 0
    messages_scanned: int = 0
    links_found: list[str] = field(default_factory=list)
    mentioned_usernames: list[str] = field(default_factory=list)
    inline_buttons: list[dict[str, str]] = field(default_factory=list)
    sample_messages: list[dict[str, Any]] = field(default_factory=list)
    bot_replies: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    fetched_at: str = ""


@dataclass
class ProjectReport:
    seed_url: str
    project_name: str
    crawled_at: str
    total_entities: int
    entities: list[EntityRecord]
    all_links: list[str]
    all_usernames: list[str]
    bots: list[str]
    chats_and_channels: list[str]


def normalize_telegram_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}"
    if raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        return f"https://{raw}"
    return raw


def parse_telegram_target(url: str) -> tuple[str, str, str]:
    """
    Returns (kind, value, canonical_url)
    kind: username | invite
    """
    url = normalize_telegram_url(url)
    parsed = urlparse(url)
    path = unquote(parsed.path.strip("/"))

    invite_match = INVITE_LINK_RE.search(url)
    if invite_match or path.startswith("+") or path.startswith("joinchat/"):
        invite_hash = path.replace("joinchat/", "").lstrip("+")
        return "invite", invite_hash, f"https://t.me/+{invite_hash}"

    username = path.split("/")[0] if path else ""
    if path.startswith("s/") and "/" in path:
        username = path.split("/", 1)[1].split("/")[0]
    username = username.split("?")[0].split("#")[0]
    if not username:
        raise ValueError(f"Не удалось распознать Telegram-ссылку: {url}")
    return "username", username, f"https://t.me/{username}"


def entity_key(kind: str, value: str) -> str:
    if kind == "invite":
        return f"invite:{value}"
    return f"user:{value.lower()}"


def extract_links_from_text(text: str) -> set[str]:
    links: set[str] = set()
    for match in TELEGRAM_LINK_RE.finditer(text or ""):
        username = match.group(1)
        if username.startswith("+"):
            links.add(f"https://t.me/+{username[1:]}")
        else:
            links.add(f"https://t.me/{username}")
    for match in INVITE_LINK_RE.finditer(text or ""):
        links.add(f"https://t.me/+{match.group(1)}")
    return links


def extract_links_from_message(message: Message) -> set[str]:
    links = extract_links_from_text(message.message or "")
    if not message.entities:
        return links

    for entity in message.entities:
        if isinstance(entity, MessageEntityUrl):
            part = (message.message or "")[entity.offset : entity.offset + entity.length]
            if "t.me" in part or "telegram.me" in part:
                links.add(normalize_telegram_url(part))
        elif isinstance(entity, MessageEntityTextUrl):
            if "t.me" in entity.url or "telegram.me" in entity.url:
                links.add(normalize_telegram_url(entity.url))
    return links


def extract_inline_buttons(message: Message) -> list[dict[str, str]]:
    buttons: list[dict[str, str]] = []
    if not message.buttons:
        return buttons
    for row in message.buttons:
        for button in row:
            item = {"text": button.text or ""}
            if getattr(button, "url", None):
                item["url"] = button.url
            buttons.append(item)
    return buttons


def serialize_message(message: Message, max_text_len: int = 2000) -> dict[str, Any]:
    text = (message.message or "").strip()
    if len(text) > max_text_len:
        text = text[:max_text_len] + "…"
    return {
        "id": message.id,
        "date": message.date.isoformat() if message.date else "",
        "text": text,
        "links": sorted(extract_links_from_message(message)),
        "buttons": extract_inline_buttons(message),
    }


def classify_entity(entity: Any) -> str:
    if isinstance(entity, User):
        return "bot" if entity.bot else "user"
    if isinstance(entity, Channel):
        if entity.broadcast:
            return "channel"
        return "supergroup"
    if isinstance(entity, Chat):
        return "group"
    return "unknown"


class TelegramProjectParser:
    def __init__(
        self,
        client: TelegramClient,
        *,
        max_depth: int = 2,
        max_messages: int = 200,
        max_sample_messages: int = 15,
        bot_wait_seconds: float = 4.0,
        delay_seconds: float = 1.0,
    ) -> None:
        self.client = client
        self.max_depth = max_depth
        self.max_messages = max_messages
        self.max_sample_messages = max_sample_messages
        self.bot_wait_seconds = bot_wait_seconds
        self.delay_seconds = delay_seconds
        self.records: dict[str, EntityRecord] = {}
        self.queue: list[tuple[str, int, str]] = []
        self.visited: set[str] = set()

    def enqueue(self, url: str, depth: int, parent: str) -> None:
        if depth > self.max_depth:
            return
        try:
            kind, value, canonical = parse_telegram_target(url)
        except ValueError:
            return
        key = entity_key(kind, value)
        if key in self.visited:
            if key in self.records and parent and parent not in self.records[key].discovered_from:
                self.records[key].discovered_from.append(parent)
            return
        self.visited.add(key)
        self.queue.append((canonical, depth, parent))

    async def crawl(self, seed_url: str) -> ProjectReport:
        seed_url = normalize_telegram_url(seed_url)
        self.enqueue(seed_url, 0, "")

        while self.queue:
            url, depth, parent = self.queue.pop(0)
            await self._process_target(url, depth, parent)
            if self.delay_seconds > 0:
                await asyncio.sleep(self.delay_seconds)

        entities = list(self.records.values())
        all_links = sorted({link for e in entities for link in e.links_found})
        all_usernames = sorted(
            {
                e.username
                for e in entities
                if e.username and not e.username.startswith("+")
            }
        )
        bots = sorted({e.username for e in entities if e.is_bot and e.username})
        chats = sorted(
            {
                e.username or e.title
                for e in entities
                if e.entity_type in {"channel", "supergroup", "group"}
            }
        )
        project_name = ""
        if entities:
            root = min(entities, key=lambda e: (e.depth, e.key))
            project_name = root.title or root.username or seed_url

        return ProjectReport(
            seed_url=seed_url,
            project_name=project_name,
            crawled_at=datetime.now(timezone.utc).isoformat(),
            total_entities=len(entities),
            entities=entities,
            all_links=all_links,
            all_usernames=all_usernames,
            bots=bots,
            chats_and_channels=chats,
        )

    async def _process_target(self, url: str, depth: int, parent: str) -> None:
        try:
            kind, value, canonical = parse_telegram_target(url)
        except ValueError as exc:
            return

        key = entity_key(kind, value)
        record = EntityRecord(
            key=key,
            url=canonical,
            username=value if kind == "username" else "",
            invite_hash=value if kind == "invite" else "",
            depth=depth,
            discovered_from=[parent] if parent else [],
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )
        self.records[key] = record

        try:
            if kind == "invite":
                await self._fill_from_invite(record, value, depth)
            else:
                entity = await self.client.get_entity(value)
                await self._fill_from_entity(record, entity, depth)
        except FloodWaitError as exc:
            record.errors.append(f"FloodWait {exc.seconds}s")
            await asyncio.sleep(exc.seconds + 1)
        except (UsernameInvalidError, UsernameNotOccupiedError) as exc:
            record.errors.append(str(exc))
        except ChannelPrivateError:
            record.is_private = True
            record.errors.append("Приватный канал/чат — нет доступа")
        except Exception as exc:
            record.errors.append(f"{type(exc).__name__}: {exc}")

    async def _fill_from_invite(self, record: EntityRecord, invite_hash: str, depth: int) -> None:
        try:
            result = await self.client(CheckChatInviteRequest(invite_hash))
        except (InviteHashInvalidError, InviteHashExpiredError) as exc:
            record.errors.append(str(exc))
            return

        if isinstance(result, ChatInviteAlready):
            entity = result.chat
            await self._fill_from_entity(record, entity, depth)
            return

        if isinstance(result, (ChatInvite, ChatInvitePeek)):
            record.title = getattr(result, "title", "") or ""
            record.description = getattr(result, "about", "") or ""
            record.members_count = getattr(result, "participants_count", None)
            record.entity_type = "invite_preview"
            text = f"{record.title}\n{record.description}"
            links = extract_links_from_text(text)
            record.links_found = sorted(links)
            record.mentioned_usernames = sorted(AT_USERNAME_RE.findall(text))
            for link in links:
                self.enqueue(link, depth + 1, record.url)
            for username in record.mentioned_usernames:
                self.enqueue(f"https://t.me/{username}", depth + 1, record.url)

    async def _fill_from_entity(self, record: EntityRecord, entity: Any, depth: int) -> None:
        record.entity_type = classify_entity(entity)
        record.title = utils.get_display_name(entity)
        record.username = getattr(entity, "username", "") or record.username
        if record.username:
            record.url = f"https://t.me/{record.username}"

        if isinstance(entity, User):
            record.is_bot = bool(entity.bot)
            record.is_verified = bool(entity.verified)
            record.is_scam = bool(entity.scam)
            record.is_fake = bool(entity.fake)
            about = ""
            try:
                full = await self.client.get_entity(entity)
                about = getattr(full, "about", "") or ""
            except Exception:
                pass
            record.description = about
            if record.is_bot:
                await self._probe_bot(record, entity, depth)
            else:
                text = f"{record.title}\n{record.description}"
                self._register_links(record, text, depth)
            return

        if isinstance(entity, (Channel, Chat)):
            record.is_verified = bool(getattr(entity, "verified", False))
            record.is_scam = bool(getattr(entity, "scam", False))
            record.is_fake = bool(getattr(entity, "fake", False))
            try:
                full = await self.client.get_entity(entity)
                record.description = getattr(full, "about", "") or ""
            except Exception:
                record.description = ""

            try:
                participants = await self.client.get_participants(entity, limit=0)
                record.members_count = participants.total
            except Exception:
                if getattr(entity, "participants_count", None):
                    record.members_count = entity.participants_count

            await self._scan_messages(record, entity, depth)
            self._register_links(record, f"{record.title}\n{record.description}", depth)

    async def _scan_messages(self, record: EntityRecord, entity: Any, depth: int) -> None:
        scanned = 0
        try:
            async for message in self.client.iter_messages(entity, limit=self.max_messages):
                if not isinstance(message, Message):
                    continue
                scanned += 1
                links = extract_links_from_message(message)
                for link in links:
                    if link not in record.links_found:
                        record.links_found.append(link)
                    self.enqueue(link, depth + 1, record.url)

                mentioned = AT_USERNAME_RE.findall(message.message or "")
                for username in mentioned:
                    if username not in record.mentioned_usernames:
                        record.mentioned_usernames.append(username)
                    self.enqueue(f"https://t.me/{username}", depth + 1, record.url)

                if len(record.sample_messages) < self.max_sample_messages:
                    record.sample_messages.append(serialize_message(message))

                for button in extract_inline_buttons(message):
                    record.inline_buttons.append(button)
                    btn_url = button.get("url", "")
                    if btn_url and ("t.me" in btn_url or "telegram.me" in btn_url):
                        self.enqueue(btn_url, depth + 1, record.url)
        except ChannelPrivateError:
            record.is_private = True
            record.errors.append("Нет доступа к истории сообщений")
        except Exception as exc:
            record.errors.append(f"messages: {type(exc).__name__}: {exc}")
        record.messages_scanned = scanned
        record.links_found = sorted(set(record.links_found))

    async def _probe_bot(self, record: EntityRecord, entity: User, depth: int) -> None:
        replies: list[dict[str, Any]] = []
        try:
            async with self.client.conversation(entity, timeout=int(self.bot_wait_seconds) + 10) as conv:
                for command in BOT_COMMANDS:
                    await conv.send_message(command)
                    try:
                        response = await conv.get_response(timeout=self.bot_wait_seconds)
                    except asyncio.TimeoutError:
                        continue
                    if not isinstance(response, Message):
                        continue
                    payload = serialize_message(response)
                    payload["trigger"] = command
                    replies.append(payload)
                    for link in payload.get("links", []):
                        self.enqueue(link, depth + 1, record.url)
                    for button in payload.get("buttons", []):
                        record.inline_buttons.append(button)
                        btn_url = button.get("url", "")
                        if btn_url:
                            if "t.me" in btn_url or "telegram.me" in btn_url:
                                self.enqueue(btn_url, depth + 1, record.url)
                    text = response.message or ""
                    for username in AT_USERNAME_RE.findall(text):
                        self.enqueue(f"https://t.me/{username}", depth + 1, record.url)
        except Exception as exc:
            record.errors.append(f"bot: {type(exc).__name__}: {exc}")
        record.bot_replies = replies
        all_text = "\n".join(r.get("text", "") for r in replies)
        self._register_links(record, f"{record.title}\n{record.description}\n{all_text}", depth)

    def _register_links(self, record: EntityRecord, text: str, depth: int) -> None:
        links = extract_links_from_text(text)
        for link in links:
            if link not in record.links_found:
                record.links_found.append(link)
            self.enqueue(link, depth + 1, record.url)
        for username in AT_USERNAME_RE.findall(text):
            if username not in record.mentioned_usernames:
                record.mentioned_usernames.append(username)
            self.enqueue(f"https://t.me/{username}", depth + 1, record.url)
        record.links_found = sorted(set(record.links_found))


def save_json(report: ProjectReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(report)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def save_entities_csv(report: ProjectReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "url",
        "username",
        "entity_type",
        "title",
        "description",
        "members_count",
        "is_bot",
        "is_private",
        "depth",
        "messages_scanned",
        "links_count",
        "links_found",
        "mentioned_usernames",
        "discovered_from",
        "errors",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for entity in sorted(report.entities, key=lambda e: (e.depth, e.title.lower())):
            writer.writerow(
                {
                    "url": entity.url,
                    "username": entity.username,
                    "entity_type": entity.entity_type,
                    "title": entity.title,
                    "description": entity.description.replace("\n", " ")[:1000],
                    "members_count": entity.members_count if entity.members_count is not None else "",
                    "is_bot": "yes" if entity.is_bot else "no",
                    "is_private": "yes" if entity.is_private else "no",
                    "depth": entity.depth,
                    "messages_scanned": entity.messages_scanned,
                    "links_count": len(entity.links_found),
                    "links_found": " | ".join(entity.links_found),
                    "mentioned_usernames": " | ".join(entity.mentioned_usernames),
                    "discovered_from": " | ".join(entity.discovered_from),
                    "errors": " | ".join(entity.errors),
                }
            )


def save_summary_md(report: ProjectReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {report.project_name or 'Telegram project'}",
        "",
        f"- Seed: {report.seed_url}",
        f"- Собрано сущностей: {report.total_entities}",
        f"- Чатов/каналов: {len(report.chats_and_channels)}",
        f"- Ботов: {len(report.bots)}",
        f"- Уникальных ссылок: {len(report.all_links)}",
        f"- Время: {report.crawled_at}",
        "",
        "## Чаты и каналы",
        "",
    ]
    for entity in sorted(report.entities, key=lambda e: (-(e.members_count or 0), e.title)):
        if entity.entity_type not in {"channel", "supergroup", "group", "invite_preview"}:
            continue
        members = f"{entity.members_count:,}".replace(",", " ") if entity.members_count else "?"
        lines.append(f"- [{entity.title}]({entity.url}) — {members} участников")
        if entity.description:
            lines.append(f"  - {entity.description[:300]}")
    lines.extend(["", "## Боты", ""])
    for entity in sorted(report.entities, key=lambda e: e.title):
        if not entity.is_bot:
            continue
        lines.append(f"- [@{entity.username}]({entity.url}) — {entity.title}")
        if entity.bot_replies:
            lines.append(f"  - Ответов на /start: {len(entity.bot_replies)}")
    path.write_text("\n".join(lines), encoding="utf-8")


def slugify_seed(seed_url: str) -> str:
    try:
        _, username, _ = parse_telegram_target(seed_url)
        return re.sub(r"[^\w\-]+", "_", username.lower()).strip("_") or "project"
    except ValueError:
        return "project"


async def ensure_authorized(client: TelegramClient, phone: str) -> None:
    await client.connect()
    if await client.is_user_authorized():
        return
    raise SystemExit(
        "Сессия не авторизована. Сначала выполните:\n"
        "  python tg_login.py\n"
        "  python tg_login.py --code КОД_ИЗ_TELEGRAM"
    )


async def run_parser(args: argparse.Namespace) -> ProjectReport:
    load_dotenv(args.env_file)
    api_id = os.getenv("TG_API_ID", "").strip()
    api_hash = os.getenv("TG_API_HASH", "").strip()
    phone = os.getenv("TG_PHONE", "").strip()

    if not api_id or not api_hash:
        raise SystemExit(
            "Нужны TG_API_ID и TG_API_HASH.\n"
            "Получите на https://my.telegram.org/apps и заполните .env (см. .env.example)."
        )

    session_path = str(Path(args.session).expanduser())
    Path(session_path).parent.mkdir(parents=True, exist_ok=True)
    proxy = proxy_from_env()
    print(f"Подключение: {proxy_label(proxy)}")
    client = create_telegram_client(session_path, api_id, api_hash, proxy=proxy)
    await ensure_authorized(client, phone)

    parser = TelegramProjectParser(
        client,
        max_depth=args.max_depth,
        max_messages=args.max_messages,
        max_sample_messages=args.max_sample_messages,
        bot_wait_seconds=args.bot_wait_seconds,
        delay_seconds=args.delay,
    )
    try:
        report = await parser.crawl(args.url)
    finally:
        await client.disconnect()
    return report


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Парсер Telegram-проекта конкурента.")
    p.add_argument("--url", required=True, help="Стартовая ссылка, напр. https://t.me/instachat6")
    p.add_argument("--max-depth", type=int, default=2, help="Глубина обхода ссылок (по умолчанию 2)")
    p.add_argument("--max-messages", type=int, default=200, help="Сообщений на чат/канал")
    p.add_argument("--max-sample-messages", type=int, default=15, help="Примеров сообщений в отчёт")
    p.add_argument("--bot-wait-seconds", type=float, default=4.0, help="Ожидание ответа бота")
    p.add_argument("--delay", type=float, default=1.0, help="Пауза между сущностями")
    p.add_argument("--session", default="sessions/tg_project", help="Путь к файлу сессии Telethon")
    p.add_argument("--env-file", default=".env", help="Файл с TG_API_ID / TG_API_HASH / TG_PHONE")
    p.add_argument("--out-dir", default="output", help="Папка для результатов")
    return p


def main() -> None:
    args = build_arg_parser().parse_args()
    started = time.time()
    report = asyncio.run(run_parser(args))

    out_dir = Path(args.out_dir)
    slug = slugify_seed(args.url)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = out_dir / f"{slug}_{ts}"

    save_json(report, base.with_suffix(".json"))
    save_entities_csv(report, base.with_name(base.name + "_entities").with_suffix(".csv"))
    save_summary_md(report, base.with_name(base.name + "_summary").with_suffix(".md"))

    elapsed = time.time() - started
    print(f"Готово за {elapsed:.1f}s")
    print(f"Сущностей: {report.total_entities}")
    print(f"JSON: {base.with_suffix('.json')}")
    print(f"CSV:  {base.with_name(base.name + '_entities').with_suffix('.csv')}")
    print(f"MD:   {base.with_name(base.name + '_summary').with_suffix('.md')}")


if __name__ == "__main__":
    main()
