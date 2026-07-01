"""Общие модели и утилиты для Telegram-парсеров."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

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
    parser_mode: str = "telethon"


def normalize_telegram_url(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("@"):
        return f"https://t.me/{raw[1:]}"
    if raw.startswith("t.me/") or raw.startswith("telegram.me/"):
        return f"https://{raw}"
    return raw


def parse_telegram_target(url: str) -> tuple[str, str, str]:
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


def register_links(record: EntityRecord, text: str, depth: int, enqueue) -> None:
    links = extract_links_from_text(text)
    for link in links:
        if link not in record.links_found:
            record.links_found.append(link)
        enqueue(link, depth + 1, record.url)
    for username in AT_USERNAME_RE.findall(text):
        if username not in record.mentioned_usernames:
            record.mentioned_usernames.append(username)
        enqueue(f"https://t.me/{username}", depth + 1, record.url)
    record.links_found = sorted(set(record.links_found))


def save_json(report: ProjectReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")


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
        f"- Режим: {report.parser_mode}",
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


def build_report(seed_url: str, entities: list[EntityRecord], parser_mode: str) -> ProjectReport:
    all_links = sorted({link for e in entities for link in e.links_found})
    all_usernames = sorted({e.username for e in entities if e.username and not e.username.startswith("+")})
    bots = sorted({e.username for e in entities if e.is_bot and e.username})
    chats = sorted(
        {e.username or e.title for e in entities if e.entity_type in {"channel", "supergroup", "group"}}
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
        parser_mode=parser_mode,
    )
