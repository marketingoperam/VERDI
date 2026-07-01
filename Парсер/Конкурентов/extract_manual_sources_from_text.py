#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path
from urllib.parse import urlparse


URL_PATTERNS = [
    r"https?://[^\s)\]\"'>]+",
    r"(?:t\.me|telegram\.me)/[^\s)\]\"'>]+",
    r"facebook\.com/groups/[^\s)\]\"'>]+",
    r"chat\.whatsapp\.com/[^\s)\]\"'>]+",
    r"vk\.com/[A-Za-z0-9_.-]+",
    r"discord\.gg/[A-Za-z0-9]+",
]


def clean_url(raw: str) -> str:
    s = raw.strip().rstrip(".,;#")
    s = s.replace("\\_", "_")
    s = s.replace("\\", "")
    s = s.replace(" ", "")
    if s.startswith("telegram.me/") or s.startswith("t.me/"):
        s = "https://" + s
    elif s.startswith("facebook.com/") or s.startswith("chat.whatsapp.com/") or s.startswith("vk.com/") or s.startswith("discord.gg/"):
        s = "https://" + s
    return s


def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "t.me" in host or "telegram.me" in host:
        return "telegram"
    if "facebook.com" in host:
        return "facebook"
    if "chat.whatsapp.com" in host:
        return "whatsapp"
    if "vk.com" in host:
        return "vk"
    if "discord.gg" in host or "discord.com" in host:
        return "discord"
    return "web"


def detect_kind(url: str, platform: str) -> str:
    u = url.lower()
    if platform in {"telegram", "whatsapp", "discord"}:
        return "community"
    if platform == "facebook" and "/groups/" in u:
        return "community"
    if platform == "vk":
        return "community_or_profile"
    return "web_source"


def main() -> None:
    p = argparse.ArgumentParser(description="Extract source links from text dumps.")
    p.add_argument("--input", action="append", required=True, help="Input text file path. Can repeat.")
    p.add_argument("--out-csv", default="manual_all_sources.csv")
    args = p.parse_args()

    found: dict[str, dict] = {}
    for input_path in args.input:
        text = Path(input_path).read_text(encoding="utf-8", errors="ignore")
        for pat in URL_PATTERNS:
            for raw in re.findall(pat, text, flags=re.IGNORECASE):
                url = clean_url(raw)
                if not url.startswith(("http://", "https://")):
                    continue
                if "share/url" in url:
                    continue
                platform = detect_platform(url)
                kind = detect_kind(url, platform)
                if url not in found:
                    found[url] = {
                        "url": url,
                        "platform": platform,
                        "kind": kind,
                        "source_file": str(Path(input_path).name),
                    }

    rows = sorted(found.values(), key=lambda r: (r["platform"], r["url"]))
    with open(args.out_csv, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["platform", "kind", "url", "source_file"], delimiter=";")
        writer.writeheader()
        writer.writerows(rows)

    print(f"Done. Extracted: {len(rows)}")
    print(f"CSV: {args.out_csv}")


if __name__ == "__main__":
    main()
