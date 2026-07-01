#!/usr/bin/env python3
"""
Global parser of Instagram mutual-activity communities/services across platforms.

Collects candidates from:
- search engine result pages (Bing RSS)
- article pages from discovered links

Extracts and classifies links to:
- Telegram / VK / Facebook groups / Discord / WhatsApp / Reddit / etc.
- external SMM-like services and directories.
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import random
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Iterable
from urllib.parse import quote_plus, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup


DEFAULT_QUERIES = [
    # RU
    "взаимная активность instagram",
    "инстаграм взаимные лайки",
    "взаимные комментарии инстаграм",
    "чат взаимопиара instagram telegram",
    "группа взаимных лайков instagram vk",
    "взаимный пиар инстаграм сообщество",
    "site:vc.ru взаимная активность instagram",
    "site:dtf.ru взаимная активность instagram",
    "site:vk.com инстаграм взаимные лайки",
    "site:t.me instagram взаимная активность",
    # EN
    "instagram engagement groups telegram",
    "instagram engagement group whatsapp",
    "instagram like for like group",
    "instagram comment for comment group",
    "instagram pods list telegram",
    "best instagram engagement groups",
    "site:facebook.com/groups instagram engagement",
    "site:discord.gg instagram engagement",
    "site:reddit.com instagram engagement group",
]

DEFAULT_SEED_URLS = [
    "https://www.buysellshoutouts.com/instagram-engagement-pods-free-list-of-groups/",
    "https://likesnetwork.com/groups",
    "https://telegramchannels.me/tag/engagements",
    "https://telegramchannels.me/channels/engagementgroupsforinstagram",
]

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

URL_RE = re.compile(r"(https?://[^\s\"'<>]+)", flags=re.IGNORECASE)

INSTAGRAM_TERMS = [
    "instagram",
    "инстаграм",
    "инста",
    "insta",
    "ig",
]

MUTUAL_TERMS = [
    "взаим",
    "mutual",
    "engagement",
    "pod",
    "like for like",
    "comment for comment",
    "l4l",
    "лайк",
    "коммент",
    "сохран",
    "репост",
    "dx",
]

SERVICE_TERMS = [
    "smm",
    "service",
    "сервис",
    "накрут",
    "premium",
    "vip",
    "buy",
    "shop",
    "order",
    "bot",
    "automation",
]

UTILITY_BAD_PATTERNS = [
    "telegram.me/share/url",
    "t.me/share/url",
    "discord.com/channels/",
    "t.me/iv?",
]

PLATFORM_PATTERNS = {
    "telegram": [r"^t\.me$", r"^telegram\.me$"],
    "vk": [r"(^|\.)vk\.com$"],
    "facebook": [r"(^|\.)facebook\.com$", r"(^|\.)fb\.com$"],
    "discord": [r"(^|\.)discord\.gg$", r"(^|\.)discord\.com$"],
    "whatsapp": [r"(^|\.)chat\.whatsapp\.com$"],
    "reddit": [r"(^|\.)reddit\.com$"],
    "instagram": [r"(^|\.)instagram\.com$"],
    "youtube": [r"(^|\.)youtube\.com$", r"(^|\.)youtu\.be$"],
}


@dataclass
class SearchHit:
    query: str
    title: str
    url: str
    snippet: str


@dataclass
class Candidate:
    url: str
    platform: str
    kind: str
    source_pages: set[str] = field(default_factory=set)
    evidence_texts: list[str] = field(default_factory=list)


@dataclass
class CandidateResult:
    url: str
    platform: str
    kind: str
    source_count: int
    source_pages: list[str]
    matched_instagram_terms: list[str]
    matched_mutual_terms: list[str]
    matched_service_terms: list[str]
    is_instagram_related: bool
    is_mutual_related: bool
    is_relevant: bool
    confidence: str


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ru,en;q=0.9"})
    return s


def sleep_between(min_delay: float, max_delay: float) -> None:
    if max_delay <= 0:
        return
    time.sleep(random.uniform(min_delay, max_delay))


def fetch(session: requests.Session, url: str, timeout_seconds: int) -> str:
    r = session.get(url, timeout=timeout_seconds)
    r.raise_for_status()
    return r.text


def search_bing_rss(session: requests.Session, query: str, timeout_seconds: int) -> list[SearchHit]:
    url = f"https://www.bing.com/search?q={quote_plus(query)}&format=rss"
    xml = fetch(session, url, timeout_seconds)
    soup = BeautifulSoup(xml, "xml")
    out: list[SearchHit] = []
    for item in soup.find_all("item"):
        link_tag = item.find("link")
        if not link_tag or not link_tag.text.strip():
            continue
        title = item.find("title").text.strip() if item.find("title") else ""
        snippet = item.find("description").text.strip() if item.find("description") else ""
        out.append(SearchHit(query=query, title=title, url=link_tag.text.strip(), snippet=snippet))
    return out


def normalize_url(raw: str) -> str | None:
    raw = html.unescape(raw).strip().rstrip(".,);")
    raw = raw.replace("\\u003cbr\\u003e", "")
    raw = raw.replace("\\", "")
    if not raw.startswith(("http://", "https://")):
        return None
    parsed = urlparse(raw)
    if not parsed.netloc:
        return None
    # Drop fragments and tracking params.
    clean_query_parts = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        k = part.split("=")[0].lower()
        if k.startswith("utm_") or k in {"fbclid", "gclid"}:
            continue
        clean_query_parts.append(part)
    query = "&".join(clean_query_parts)
    clean = parsed._replace(query=query, fragment="")
    return urlunparse(clean)


def detect_platform(hostname: str) -> str:
    h = hostname.lower()
    for name, patterns in PLATFORM_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, h):
                return name
    return "web"


def detect_kind(platform: str, parsed_url) -> str:
    path = (parsed_url.path or "").lower()
    host = (parsed_url.netloc or "").lower()
    if platform == "telegram":
        return "community"
    if platform == "vk":
        if re.match(r"^/(club\d+|public\d+|event\d+)", path) or "/topic" in path:
            return "community"
        return "profile_or_other"
    if platform == "facebook":
        if "/groups/" in path:
            return "community"
        return "profile_or_other"
    if platform == "discord":
        if host == "discord.gg" or "/invite/" in path:
            return "community"
        return "profile_or_other"
    if platform == "whatsapp":
        return "community"
    if platform == "reddit":
        if path.startswith("/r/"):
            return "community"
        return "profile_or_other"
    if platform == "instagram":
        return "profile_or_other"
    return "service_or_article"


def candidate_allowed(url: str, parsed_url) -> bool:
    # Skip obvious static/file links.
    path = (parsed_url.path or "").lower()
    if any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".zip", ".mp4")):
        return False
    # Keep only http(s).
    lowered = url.lower()
    if any(bad in lowered for bad in UTILITY_BAD_PATTERNS):
        return False
    return url.startswith(("http://", "https://"))


def extract_links_with_anchor(html: str, base_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    found: list[tuple[str, str]] = []
    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full = urljoin(base_url, href)
        anchor = a.get_text(" ", strip=True)
        found.append((full, anchor))

    # Also parse raw links in text.
    for m in URL_RE.findall(html):
        found.append((m, "raw-url"))
    return found


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def find_terms(text: str, terms: Iterable[str]) -> list[str]:
    t = normalize_text(text)
    return [term for term in terms if term in t]


def collect_candidates(
    session: requests.Session,
    hits: list[SearchHit],
    timeout_seconds: int,
    min_delay: float,
    max_delay: float,
    max_pages_to_crawl: int,
) -> dict[str, Candidate]:
    candidates: dict[str, Candidate] = {}

    def remember(url: str, source_page: str, evidence: str) -> None:
        clean = normalize_url(url)
        if not clean:
            return
        parsed = urlparse(clean)
        if not candidate_allowed(clean, parsed):
            return
        platform = detect_platform(parsed.netloc)
        kind = detect_kind(platform, parsed)

        if clean not in candidates:
            candidates[clean] = Candidate(url=clean, platform=platform, kind=kind)
        candidates[clean].source_pages.add(source_page)
        if evidence and len(candidates[clean].evidence_texts) < 8:
            candidates[clean].evidence_texts.append(evidence[:2000])

    # First pass: include SERP hits as candidates.
    for hit in hits:
        evidence = f"{hit.title} {hit.snippet}"
        remember(hit.url, hit.url, evidence)

    # Second pass: crawl result pages and collect outgoing links.
    for i, hit in enumerate(hits):
        if i >= max_pages_to_crawl:
            break
        try:
            html = fetch(session, hit.url, timeout_seconds)
            base_evidence = f"{hit.title} {hit.snippet}"
            for link, anchor in extract_links_with_anchor(html, hit.url):
                # Do not propagate full page text into every outbound URL signal;
                # this keeps relevance tied to the actual link/anchor context.
                remember(link, hit.url, f"{anchor} {base_evidence}")
        except Exception:
            pass
        sleep_between(min_delay, max_delay)

    return candidates


def evaluate_candidate(candidate: Candidate) -> CandidateResult:
    evidence = "\n".join(candidate.evidence_texts)
    url_lower = candidate.url.lower()
    parsed = urlparse(candidate.url)
    slug = re.sub(r"[-_/]+", " ", (parsed.path or "").lower())
    merged = f"{url_lower}\n{slug}\n{evidence}"

    instagram_terms = find_terms(merged, INSTAGRAM_TERMS)
    mutual_terms = find_terms(merged, MUTUAL_TERMS)
    service_terms = find_terms(merged, SERVICE_TERMS)

    is_instagram_related = bool(instagram_terms)
    is_mutual_related = bool(mutual_terms)
    is_relevant = is_instagram_related and is_mutual_related

    # Confidence heuristic.
    src_count = len(candidate.source_pages)
    if is_relevant and src_count >= 2:
        confidence = "high"
    elif is_relevant:
        confidence = "medium"
    elif is_instagram_related or is_mutual_related:
        confidence = "low"
    else:
        confidence = "very_low"

    return CandidateResult(
        url=candidate.url,
        platform=candidate.platform,
        kind=candidate.kind,
        source_count=src_count,
        source_pages=sorted(candidate.source_pages),
        matched_instagram_terms=instagram_terms,
        matched_mutual_terms=mutual_terms,
        matched_service_terms=service_terms,
        is_instagram_related=is_instagram_related,
        is_mutual_related=is_mutual_related,
        is_relevant=is_relevant,
        confidence=confidence,
    )


def save_json(path: str, rows: list[CandidateResult]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in rows], f, ensure_ascii=False, indent=2)


def save_csv(path: str, rows: list[CandidateResult]) -> None:
    fieldnames = [
        "url",
        "platform",
        "kind",
        "source_count",
        "matched_instagram_terms",
        "matched_mutual_terms",
        "matched_service_terms",
        "is_instagram_related",
        "is_mutual_related",
        "is_relevant",
        "confidence",
        "source_pages",
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=";")
        writer.writeheader()
        for r in rows:
            row = asdict(r)
            row["matched_instagram_terms"] = ", ".join(r.matched_instagram_terms)
            row["matched_mutual_terms"] = ", ".join(r.matched_mutual_terms)
            row["matched_service_terms"] = ", ".join(r.matched_service_terms)
            row["source_pages"] = " | ".join(r.source_pages)
            writer.writerow(row)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Parse Instagram mutual-activity communities/services across platforms."
    )
    p.add_argument("--query", action="append", default=[], help="Custom query, can be repeated.")
    p.add_argument("--seed-url", action="append", default=[], help="Direct source URL to crawl.")
    p.add_argument("--timeout", type=int, default=6, help="HTTP timeout seconds.")
    p.add_argument("--min-delay", type=float, default=0.0, help="Min delay between requests.")
    p.add_argument("--max-delay", type=float, default=0.08, help="Max delay between requests.")
    p.add_argument(
        "--max-pages-to-crawl",
        type=int,
        default=120,
        help="How many SERP target pages to open and parse links from.",
    )
    p.add_argument("--out-all-json", default="all_instagram_mutual_candidates.json")
    p.add_argument("--out-all-csv", default="all_instagram_mutual_candidates.csv")
    p.add_argument("--out-communities-json", default="instagram_mutual_communities.json")
    p.add_argument("--out-communities-csv", default="instagram_mutual_communities.csv")
    p.add_argument("--out-services-json", default="instagram_mutual_services.json")
    p.add_argument("--out-services-csv", default="instagram_mutual_services.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    queries = args.query if args.query else DEFAULT_QUERIES
    seed_urls = list(dict.fromkeys([*DEFAULT_SEED_URLS, *args.seed_url]))
    session = make_session()

    hits: list[SearchHit] = []
    for q in queries:
        try:
            hits.extend(search_bing_rss(session, q, args.timeout))
        except Exception:
            continue
        sleep_between(args.min_delay, args.max_delay)
    for seed in seed_urls:
        hits.append(SearchHit(query="seed", title=seed, url=seed, snippet=""))

    candidates = collect_candidates(
        session=session,
        hits=hits,
        timeout_seconds=args.timeout,
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        max_pages_to_crawl=args.max_pages_to_crawl,
    )

    evaluated = [evaluate_candidate(c) for c in candidates.values()]
    evaluated.sort(key=lambda x: (not x.is_relevant, -x.source_count, x.platform, x.url))

    communities = [
        r for r in evaluated if r.kind == "community" and r.is_relevant and r.confidence in {"medium", "high"}
    ]
    services = [
        r
        for r in evaluated
        if r.kind == "service_or_article"
        and (
            r.is_relevant
            and bool(r.matched_service_terms)
            and r.confidence in {"medium", "high"}
        )
    ]

    save_json(args.out_all_json, evaluated)
    save_csv(args.out_all_csv, evaluated)
    save_json(args.out_communities_json, communities)
    save_csv(args.out_communities_csv, communities)
    save_json(args.out_services_json, services)
    save_csv(args.out_services_csv, services)

    print(f"Done. Search hits: {len(hits)}")
    print(f"All candidates: {len(evaluated)}")
    print(f"Relevant communities: {len(communities)}")
    print(f"Relevant services/articles: {len(services)}")
    print(f"All CSV: {args.out_all_csv}")
    print(f"Communities CSV: {args.out_communities_csv}")
    print(f"Services CSV: {args.out_services_csv}")


if __name__ == "__main__":
    main()
