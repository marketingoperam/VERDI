#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import random
import re
import time
from dataclasses import dataclass, field
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

RU_QUERIES = [
    "чат активности инстаграм telegram",
    "инстаграм взаимные лайки telegram группа",
    "взаимные комментарии инстаграм телеграм",
    "взаимная активность instagram telegram chat",
    "лайк чат инстаграм telegram",
    "инстаграм чат активности t.me",
    "взаимопиар инстаграм telegram",
    "где найти чат активности инстаграм",
    "site:t.me инстаграм активность",
    "site:ru.telegram-store.com инстаграм чат активности",
    "site:niksolovov.ru чат активности инстаграм",
    "site:smmplanner.com чат активности инстаграм",
]

SEED_PAGES = [
    "https://niksolovov.ru/chat-aktivnosti-v-instagram",
    "https://ru.telegram-store.com/catalog/chats/inst_activ_ru",
    "https://smmplanner.com/blog/rukovodstvo-po-chatam-aktivnosti-v-instaghramie/",
]

TG_LINK_RE = re.compile(r"(https?://(?:t\.me|telegram\.me)/[A-Za-z0-9_+/\\-]+)", re.IGNORECASE)
TG_HANDLE_RE = re.compile(r"@([A-Za-z0-9_]{4,})")

MUTUAL_TERMS = [
    "взаим",
    "актив",
    "лайк",
    "коммент",
    "like",
    "comment",
    "engagement",
    "instagram",
    "инстаграм",
    "инста",
]

BAD_USERNAMES = {
    "instagram",
    "telegram",
    "channel",
    "chat",
    "admin",
    "support",
    "context",
    "media",
    "graph",
}


@dataclass
class Candidate:
    username: str
    links: set[str] = field(default_factory=set)
    evidence: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.9"})
    return s


def fetch(session: requests.Session, url: str, timeout: int) -> str:
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.text


def sleep_between(min_delay: float, max_delay: float) -> None:
    if max_delay <= 0:
        return
    time.sleep(random.uniform(min_delay, max_delay))


def search_bing_rss(session: requests.Session, query: str, timeout: int) -> list[dict]:
    url = f"https://www.bing.com/search?q={quote_plus(query)}&format=rss"
    xml = fetch(session, url, timeout)
    soup = BeautifulSoup(xml, "xml")
    hits: list[dict] = []
    for item in soup.find_all("item"):
        title = item.find("title").text.strip() if item.find("title") else ""
        link = item.find("link").text.strip() if item.find("link") else ""
        desc = item.find("description").text.strip() if item.find("description") else ""
        if link:
            hits.append({"query": query, "title": title, "url": link, "snippet": desc})
    return hits


def normalize_username(raw: str) -> str | None:
    s = raw.strip().replace("\\_", "_").replace("\\", "")
    s = s.split("?")[0].split("#")[0].strip("/")
    if s.startswith("+") or s.startswith("joinchat/"):
        return None
    s = s.replace("https://", "").replace("http://", "")
    s = s.replace("t.me/", "").replace("telegram.me/", "")
    s = s.split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9_]{4,}", s):
        return None
    if s.lower() in BAD_USERNAMES:
        return None
    return s


def add_candidate(candidates: dict[str, Candidate], username: str, link: str, source: str, evidence: str) -> None:
    if username not in candidates:
        candidates[username] = Candidate(username=username)
    c = candidates[username]
    c.links.add(link)
    c.sources.add(source)
    if evidence and len(c.evidence) < 8:
        c.evidence.append(evidence[:1200])


def extract_from_text(candidates: dict[str, Candidate], text: str, source: str) -> None:
    for m in TG_LINK_RE.findall(text):
        username = normalize_username(m)
        if username:
            add_candidate(candidates, username, f"https://t.me/{username}", source, text)
    for handle in TG_HANDLE_RE.findall(text):
        username = normalize_username(handle)
        if username:
            add_candidate(candidates, username, f"https://t.me/{username}", source, text)


def is_mutual_candidate(candidate: Candidate) -> tuple[bool, list[str]]:
    merged = " ".join(candidate.evidence).lower() + " " + candidate.username.lower()
    found = [t for t in MUTUAL_TERMS if t in merged]
    return bool(found), found


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect Russian Telegram Instagram mutual groups.")
    p.add_argument("--timeout", type=int, default=6)
    p.add_argument("--min-delay", type=float, default=0.0)
    p.add_argument("--max-delay", type=float, default=0.05)
    p.add_argument("--max-pages", type=int, default=80, help="How many result pages to open")
    p.add_argument("--out-csv", default="all_sources_master_ru_telegram.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    session = make_session()
    hits: list[dict] = []

    for q in RU_QUERIES:
        try:
            hits.extend(search_bing_rss(session, q, args.timeout))
        except Exception:
            continue
        sleep_between(args.min_delay, args.max_delay)

    # Force seed pages even if search misses them.
    for seed in SEED_PAGES:
        hits.append({"query": "seed", "title": seed, "url": seed, "snippet": ""})

    candidates: dict[str, Candidate] = {}

    # Parse search result metadata itself.
    for h in hits:
        block = f"{h['title']} {h['snippet']} {h['url']}"
        extract_from_text(candidates, block, h["url"])

    # Crawl result pages for more usernames/links.
    for i, h in enumerate(hits):
        if i >= args.max_pages:
            break
        try:
            html = fetch(session, h["url"], args.timeout)
            text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            extract_from_text(candidates, html, h["url"])
            extract_from_text(candidates, text, h["url"])
        except Exception:
            pass
        sleep_between(args.min_delay, args.max_delay)

    rows: list[dict] = []
    for c in candidates.values():
        mutual_ok, terms = is_mutual_candidate(c)
        rows.append(
            {
                "platform": "telegram",
                "kind": "community",
                "username": c.username,
                "url": f"https://t.me/{c.username}",
                "sources_count": len(c.sources),
                "matched_terms": ", ".join(terms) if terms else "-",
                "is_mutual_related": "YES" if mutual_ok else "NO",
                "source_pages": " | ".join(sorted(c.sources)),
            }
        )

    rows.sort(
        key=lambda r: (
            r["is_mutual_related"] != "YES",
            -int(r["sources_count"]),
            r["username"].lower(),
        )
    )

    with open(args.out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "platform",
                "kind",
                "username",
                "url",
                "sources_count",
                "matched_terms",
                "is_mutual_related",
                "source_pages",
            ],
            delimiter=";",
        )
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    mutual = sum(1 for r in rows if r["is_mutual_related"] == "YES")
    print(f"Done. Total TG usernames: {total}, mutual-related: {mutual}")
    print(f"CSV: {args.out_csv}")


if __name__ == "__main__":
    main()
