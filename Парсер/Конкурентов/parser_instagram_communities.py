#!/usr/bin/env python3
"""
Parser for Instagram-only mutual-activity communities.

What it does:
1) Searches the web (Bing RSS by default, DuckDuckGo optional) with niche queries.
2) Extracts Telegram community links from result pages.
3) Opens public Telegram previews and filters only Instagram mutual-activity groups/channels.
4) Saves structured output to JSON/CSV.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Iterable
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


DEFAULT_QUERIES = [
    "взаимная активность instagram telegram чат",
    "инстаграм взаимные лайки telegram t.me",
    "чат взаимной активности инстаграм",
    "взаимный пиар instagram telegram",
    "instagram engagement group telegram",
    "instagram pods telegram t.me",
    "site:t.me instagram взаимная активность",
    "site:t.me instagram engagement",
]

RU_QUERIES = [
    "взаимная активность инстаграм telegram чат",
    "инстаграм взаимные лайки t.me",
    "взаимные комментарии инстаграм телеграм",
    "чат взаимопиара инстаграм telegram",
    "взаимные лайки и комментарии instagram группа",
    "site:t.me инстаграм взаимная активность",
]

DEFAULT_SEED_URLS = [
    # Public article with large Telegram pod list for Instagram.
    "https://www.buysellshoutouts.com/instagram-engagement-pods-free-list-of-groups/",
    # Telegram directory pages about engagement/Instagram.
    "https://telegramchannels.me/tag/engagements",
    "https://telegramchannels.me/channels/engagementgroupsforinstagram",
    # Catalog page that can still provide Instagram-group metadata for additional crawling.
    "https://telegram-group.com/en/search/instagram/",
]

RU_SEED_URLS = [
    "https://sendpulse.com/ru/blog/mutual-pr-on-instagram",
    "https://dtf.ru/pro-smm/4762864-vzaimnyj-piar-telegram-kanalov",
    "https://vc.ru/smm-promotion/1280480-kak-nabrat-laiki-instagram-na-post-21-media-smm-platform",
    "https://timeweb.com/ru/community/articles/nakrutka-kommentariev-v-instagram-luchshie-servisy-po-rabote-s-kommentariyami-v-instagram",
]

DEFAULT_SEED_USERNAMES = [
    # Curated from public Instagram engagement pod directories/posts.
    "engagementgroupsforinstagram",
    "engagementgroupsIG",
    "boostuppowerlikes",
    "engagementgroups",
    "igbst",
    "successed",
    "VGNCHAT",
    "iggainzgrowthlist",
    "igmasslikes",
    "instaempiremarket",
    "instagains20k",
    "instagains50k",
    "instagains100k",
    "instagramventuresmarket",
    "VGNLIKES",
    "MoneyMartOG",
    "NsmIGGroup",
    "apocmarket",
    "beaversmarketplace",
    "PUSHGROUPDX5",
    "elitemarket",
    "elite_chat",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

INSTAGRAM_TERMS = [
    "instagram",
    "инстаграм",
    "инста",
    "insta",
    "ig",
]

MUTUAL_ACTIVITY_TERMS = [
    "взаим",
    "актив",
    "лайк",
    "коммент",
    "сохран",
    "репост",
    "engagement",
    "likes",
    "comments",
    "dx",
    "pod",
    "like for like",
    "comment for comment",
    "l4l",
]

# If any of these are present in the community text, we treat it as multi-platform,
# while the task requires Instagram-only communities.
NON_INSTAGRAM_TERMS = [
    "вконтакте",
    "вк ",
    "vk ",
    "vk.com",
    "тикток",
    "tiktok",
    "youtube",
    "ютуб",
    "одноклассники",
    "ok.ru",
    "facebook",
    "twitter",
    "x.com",
    "telegram-канал",
    "продвижение telegram",
    "likee",
]

SPAM_MARKET_TERMS = [
    "buy",
    "sell",
    "market",
    "shop",
    "premium",
    "vip",
    "boost",
    "smm",
    "накрут",
    "подписчик",
    "подписки",
    "дешево",
    "cheap",
    "coins",
    "coin",
    "оплата",
    "payment",
    "услуг",
    "service",
    "продам",
    "купить",
]

TELEGRAM_LINK_RE = re.compile(
    r"((?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?[A-Za-z0-9_+/\-\\]+)",
    flags=re.IGNORECASE,
)


@dataclass
class Candidate:
    username: str
    url: str
    source_pages: set[str] = field(default_factory=set)
    evidence_texts: set[str] = field(default_factory=set)


@dataclass
class CommunityResult:
    username: str
    url: str
    title: str
    description: str
    participants: str
    matched_instagram_terms: list[str]
    matched_mutual_terms: list[str]
    matched_non_instagram_terms: list[str]
    matched_spam_market_terms: list[str]
    is_mutual_activity: bool
    is_instagram_only: bool
    is_clean_competitor_candidate: bool
    is_match: bool
    source_pages: list[str]


def make_session(timeout_seconds: int) -> tuple[requests.Session, int]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.9"})
    return session, timeout_seconds


def fetch(session: requests.Session, timeout_seconds: int, url: str) -> str:
    response = session.get(url, timeout=timeout_seconds)
    response.raise_for_status()
    return response.text


def sleep_between(min_delay: float, max_delay: float) -> None:
    if max_delay <= 0:
        return
    delay = random.uniform(min_delay, max_delay)
    time.sleep(delay)


def extract_real_link(ddg_href: str) -> str:
    # DuckDuckGo HTML often wraps target URLs as /l/?uddg=<encoded_url>
    parsed = urlparse(ddg_href)
    if parsed.path == "/l/":
        query = parse_qs(parsed.query)
        encoded = query.get("uddg", [""])[0]
        if encoded:
            return unquote(encoded)
    return ddg_href


def search_bing_rss(
    session: requests.Session,
    timeout_seconds: int,
    query: str,
) -> list[dict]:
    url = f"https://www.bing.com/search?q={quote_plus(query)}&format=rss"
    xml = fetch(session, timeout_seconds, url)
    soup = BeautifulSoup(xml, "xml")
    results: list[dict] = []

    for item in soup.find_all("item"):
        link_tag = item.find("link")
        title_tag = item.find("title")
        desc_tag = item.find("description")
        if not link_tag or not link_tag.text.strip():
            continue
        results.append(
            {
                "query": query,
                "title": title_tag.text.strip() if title_tag else "",
                "url": link_tag.text.strip(),
                "snippet": desc_tag.text.strip() if desc_tag else "",
            }
        )
    return results


def search_duckduckgo(
    session: requests.Session,
    timeout_seconds: int,
    query: str,
    pages: int,
    min_delay: float,
    max_delay: float,
) -> list[dict]:
    results: list[dict] = []
    next_path = f"/html/?q={quote_plus(query)}"
    for _ in range(pages):
        url = f"https://duckduckgo.com{next_path}"
        html = fetch(session, timeout_seconds, url)
        if "anomaly-modal__title" in html:
            # DDG bot challenge page.
            return []
        soup = BeautifulSoup(html, "html.parser")

        for block in soup.select(".result"):
            a_tag = block.select_one(".result__a")
            if not a_tag:
                continue

            href = a_tag.get("href", "").strip()
            real_link = extract_real_link(href)
            title = a_tag.get_text(" ", strip=True)
            snippet_tag = block.select_one(".result__snippet")
            snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""

            results.append(
                {
                    "query": query,
                    "title": title,
                    "url": real_link,
                    "snippet": snippet,
                }
            )

        next_link = soup.select_one("a.result--more__btn")
        if not next_link:
            break
        next_path = next_link.get("href", "").strip()
        if not next_path:
            break
        sleep_between(min_delay, max_delay)
    return results


def clean_telegram_username(raw: str) -> str | None:
    raw = raw.strip()
    raw = raw.replace("\\_", "_")
    raw = raw.replace("https://", "").replace("http://", "")
    raw = raw.replace("t.me/", "").replace("telegram.me/", "")
    raw = raw.replace("s/", "")
    raw = raw.split("?")[0].split("#")[0].strip("/")
    if not raw:
        return None
    # Ignore invite links without a stable public username.
    if raw.startswith("+") or raw.startswith("joinchat/"):
        return None
    # Keep only first segment.
    raw = raw.split("/")[0]
    if not re.fullmatch(r"[A-Za-z0-9_]{4,}", raw):
        return None
    return raw


def extract_telegram_links_from_html(html: str, base_url: str) -> set[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: set[str] = set()

    for a_tag in soup.select("a[href]"):
        href = a_tag.get("href", "").strip()
        if not href:
            continue
        full = urljoin(base_url, href)
        if "t.me/" in full or "telegram.me/" in full:
            links.add(full)

    # Fallback: regex scan over raw html content.
    for match in TELEGRAM_LINK_RE.findall(html):
        if match.startswith("http://") or match.startswith("https://"):
            links.add(match)
        else:
            links.add(f"https://{match}")

    return links


def collect_candidates(
    search_results: list[dict],
    session: requests.Session,
    timeout_seconds: int,
    min_delay: float,
    max_delay: float,
    max_pages_to_scrape: int,
) -> dict[str, Candidate]:
    candidates: dict[str, Candidate] = {}

    def remember(link: str, source_page: str, evidence_text: str = "") -> None:
        username = clean_telegram_username(link)
        if not username:
            return
        url = f"https://t.me/{username}"
        if username not in candidates:
            candidates[username] = Candidate(username=username, url=url)
        candidates[username].source_pages.add(source_page)
        if evidence_text.strip():
            candidates[username].evidence_texts.add(evidence_text.strip()[:4000])

    for idx, item in enumerate(search_results):
        source_url = item["url"]
        base_evidence = f"{item.get('query', '')} {item.get('title', '')} {item.get('snippet', '')}"
        if "t.me/" in source_url or "telegram.me/" in source_url:
            remember(source_url, source_url, base_evidence)

        if idx >= max_pages_to_scrape:
            continue

        try:
            html = fetch(session, timeout_seconds, source_url)
            page_text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
            for link in extract_telegram_links_from_html(html, source_url):
                remember(link, source_url, f"{base_evidence} {page_text}")
        except Exception:
            # Keep crawling even if one source fails or blocks.
            pass
        sleep_between(min_delay, max_delay)

    return candidates


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def find_terms(text: str, terms: Iterable[str]) -> list[str]:
    normalized = normalize_text(text)
    found: list[str] = []
    for term in terms:
        if term in normalized:
            found.append(term)
    return found


def parse_telegram_preview(
    session: requests.Session,
    timeout_seconds: int,
    username: str,
) -> tuple[str, str, str, str]:
    # /s/<username> works for public channels/groups and is parse-friendly.
    url = f"https://t.me/s/{username}"
    html = fetch(session, timeout_seconds, url)
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    description = ""
    participants = ""

    meta_title = soup.find("meta", attrs={"property": "og:title"})
    if meta_title and meta_title.get("content"):
        title = meta_title["content"].strip()

    desc_tag = soup.select_one(".tgme_channel_info_description")
    if desc_tag:
        description = desc_tag.get_text(" ", strip=True)

    participants_tag = soup.select_one(".tgme_channel_info_counter .counter_value")
    if participants_tag:
        participants = participants_tag.get_text(" ", strip=True)

    visible_text = soup.get_text(" ", strip=True)
    return title, description, participants, visible_text


def can_access_telegram_preview(session: requests.Session, timeout_seconds: int) -> bool:
    try:
        # Fast connectivity probe to avoid repeated long timeouts.
        response = session.get("https://t.me/s/durov", timeout=max(3, min(timeout_seconds, 8)))
        return response.status_code == 200 and "tgme_channel_info_header" in response.text
    except Exception:
        return False


def evaluate_community(
    session: requests.Session,
    timeout_seconds: int,
    candidate: Candidate,
    allow_preview: bool,
    ru_only: bool,
    strict_filter: bool,
) -> CommunityResult | None:
    fallback_text = f"{candidate.username.replace('_', ' ')} " + " ".join(candidate.evidence_texts)
    preview_available = True

    if allow_preview:
        try:
            title, description, participants, text = parse_telegram_preview(
                session, timeout_seconds, candidate.username
            )
            full_text = f"{title}\n{description}\n{text}\n{fallback_text}"
        except Exception:
            preview_available = False
            title = candidate.username
            description = "Parsed from source pages (Telegram preview unavailable)."
            participants = ""
            full_text = fallback_text
    else:
        preview_available = False
        title = candidate.username
        description = "Parsed from source pages (Telegram preview unavailable)."
        participants = ""
        full_text = fallback_text

    matched_instagram = find_terms(full_text, INSTAGRAM_TERMS)
    matched_mutual = find_terms(full_text, MUTUAL_ACTIVITY_TERMS)
    matched_non_instagram = find_terms(full_text, NON_INSTAGRAM_TERMS)
    matched_spam_market = find_terms(full_text, SPAM_MARKET_TERMS)

    if preview_available:
        is_mutual_activity = bool(matched_mutual)
        is_instagram_only = bool(matched_instagram) and not bool(matched_non_instagram)
    else:
        username_lower = candidate.username.lower()
        insta_hint = bool(re.search(r"(instagram|insta|(^|_)ig(_|$))", username_lower))
        mutual_hint = bool(re.search(r"(engage|like|comment|pod|dx\d+|l4l|group)", username_lower))
        is_mutual_activity = bool(matched_mutual) or mutual_hint
        is_instagram_only = (bool(matched_instagram) or insta_hint) and not bool(matched_non_instagram)

    if ru_only:
        has_ru_text = bool(re.search(r"[а-яё]", normalize_text(full_text)))
        has_ru_source = any(".ru" in url.lower() or "/ru/" in url.lower() for url in candidate.source_pages)
        if not (has_ru_text or has_ru_source):
            is_mutual_activity = False

    is_clean_competitor_candidate = not bool(matched_spam_market)
    if strict_filter and not is_clean_competitor_candidate:
        is_mutual_activity = False

    is_match = is_mutual_activity and is_instagram_only and (is_clean_competitor_candidate or not strict_filter)

    return CommunityResult(
        username=candidate.username,
        url=candidate.url,
        title=title,
        description=description,
        participants=participants,
        matched_instagram_terms=matched_instagram,
        matched_mutual_terms=matched_mutual,
        matched_non_instagram_terms=matched_non_instagram,
        matched_spam_market_terms=matched_spam_market,
        is_mutual_activity=is_mutual_activity,
        is_instagram_only=is_instagram_only,
        is_clean_competitor_candidate=is_clean_competitor_candidate,
        is_match=is_match,
        source_pages=sorted(candidate.source_pages),
    )


def save_json(path: str, data: list[CommunityResult]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(item) for item in data], f, ensure_ascii=False, indent=2)


def save_csv(path: str, data: list[CommunityResult]) -> None:
    fieldnames = [
        "username",
        "url",
        "title",
        "description",
        "participants",
        "matched_instagram_terms",
        "matched_mutual_terms",
        "matched_non_instagram_terms",
        "matched_spam_market_terms",
        "is_mutual_activity",
        "is_instagram_only",
        "is_clean_competitor_candidate",
        "is_match",
        "source_pages",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in data:
            row = asdict(item)
            row["matched_instagram_terms"] = ", ".join(item.matched_instagram_terms)
            row["matched_mutual_terms"] = ", ".join(item.matched_mutual_terms)
            row["matched_non_instagram_terms"] = ", ".join(item.matched_non_instagram_terms)
            row["matched_spam_market_terms"] = ", ".join(item.matched_spam_market_terms)
            row["source_pages"] = " | ".join(item.source_pages)
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Telegram communities for Instagram mutual activity."
    )
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Custom search query. Can be passed multiple times.",
    )
    parser.add_argument(
        "--seed-url",
        action="append",
        default=[],
        help="Page URL with possible Telegram links. Can be passed multiple times.",
    )
    parser.add_argument(
        "--seed-username",
        action="append",
        default=[],
        help="Known Telegram username (without @). Can be passed multiple times.",
    )
    parser.add_argument(
        "--ru-only",
        action="store_true",
        help="Keep only Russian-language candidates (text/source hints).",
    )
    parser.add_argument(
        "--strict-filter",
        action="store_true",
        help="Apply strict anti-spam / anti-market filtering.",
    )
    parser.add_argument(
        "--ru-sources",
        action="store_true",
        help="Use built-in Russian queries and Russian seed source pages.",
    )
    parser.add_argument(
        "--search-engine",
        choices=["bing_rss", "ddg"],
        default="bing_rss",
        help="Web search source. Default: bing_rss.",
    )
    parser.add_argument(
        "--ddg-pages",
        type=int,
        default=2,
        help="How many DuckDuckGo pages per query to fetch (used only when --search-engine ddg).",
    )
    parser.add_argument(
        "--max-source-pages",
        type=int,
        default=60,
        help="How many result pages to open for extracting Telegram links.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=8,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--min-delay",
        type=float,
        default=0.8,
        help="Min delay between requests, seconds.",
    )
    parser.add_argument(
        "--max-delay",
        type=float,
        default=1.8,
        help="Max delay between requests, seconds.",
    )
    parser.add_argument(
        "--out-json",
        default="instagram_communities.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--out-csv",
        default="instagram_communities.csv",
        help="Output CSV path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.ru_sources:
        queries = args.query if args.query else RU_QUERIES
        seed_urls = list(dict.fromkeys([*DEFAULT_SEED_URLS, *RU_SEED_URLS, *args.seed_url]))
    else:
        queries = args.query if args.query else DEFAULT_QUERIES
        seed_urls = list(dict.fromkeys([*DEFAULT_SEED_URLS, *args.seed_url]))
    seed_usernames = list(dict.fromkeys([*DEFAULT_SEED_USERNAMES, *args.seed_username]))
    session, timeout_seconds = make_session(args.timeout)

    search_results: list[dict] = []
    for seed in seed_urls:
        search_results.append(
            {
                "query": "seed",
                "title": seed,
                "url": seed,
                "snippet": "",
            }
        )
    for username in seed_usernames:
        username = clean_telegram_username(username or "")
        if not username:
            continue
        search_results.append(
            {
                "query": "seed_username",
                "title": username,
                "url": f"https://t.me/{username}",
                "snippet": "",
            }
        )

    for query in queries:
        try:
            if args.search_engine == "bing_rss":
                rows = search_bing_rss(
                    session=session,
                    timeout_seconds=timeout_seconds,
                    query=query,
                )
            else:
                rows = search_duckduckgo(
                    session=session,
                    timeout_seconds=timeout_seconds,
                    query=query,
                    pages=args.ddg_pages,
                    min_delay=args.min_delay,
                    max_delay=args.max_delay,
                )
            search_results.extend(rows)
        except Exception:
            continue
        sleep_between(args.min_delay, args.max_delay)

    candidates = collect_candidates(
        search_results=search_results,
        session=session,
        timeout_seconds=timeout_seconds,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        max_pages_to_scrape=args.max_source_pages,
    )

    allow_preview = can_access_telegram_preview(session, timeout_seconds)

    evaluated: list[CommunityResult] = []
    for candidate in candidates.values():
        item = evaluate_community(
            session=session,
            timeout_seconds=timeout_seconds,
            candidate=candidate,
            allow_preview=allow_preview,
            ru_only=args.ru_only,
            strict_filter=args.strict_filter,
        )
        if item:
            evaluated.append(item)
        sleep_between(args.min_delay, args.max_delay)

    evaluated.sort(key=lambda x: (not x.is_match, x.username.lower()))

    save_json(args.out_json, evaluated)
    save_csv(args.out_csv, evaluated)

    total = len(evaluated)
    matched = sum(1 for x in evaluated if x.is_match)
    print(f"Done. Checked: {total} communities, matched Instagram mutual: {matched}")
    print(f"JSON: {args.out_json}")
    print(f"CSV:  {args.out_csv}")


if __name__ == "__main__":
    main()
