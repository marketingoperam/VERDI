#!/usr/bin/env python3
from __future__ import annotations

import csv
import re


INPUT = "all_sources_master_ru_telegram.csv"
OUTPUT = "all_sources_master_ru_telegram_clean.csv"

GOOD_SOURCE_HINTS = [
    "telegram-store",
    "niksolovov",
    "smmplanner",
    "dtf.ru",
    "vc.ru",
    "sendpulse",
    "remarka",
    "buysellshoutouts",
    "gettinggrowth",
    "usapowerlikes",
    "t.me/",
]

BAD_SOURCE_HINTS = [
    "apkpure",
    "play.google.com",
    "apps.apple.com",
    "apps.microsoft.com",
    "rustore",
    "roblox",
    "rhs.org",
    "yandex",
    "google.com/android/find",
    "clubic",
    "calculator",
    "desmos",
    "chatroulette",
    "ruletka.chat",
]

BAD_USERS = {
    "apkpure",
    "apkpurechannel",
    "appstore",
    "gmail",
    "iterator",
    "toprimitive",
    "tostringtag",
    "bytedance",
    "meta",
    "example",
    "font",
    "keyframes",
    "type",
    "share",
    "like",
    "likee",
    "ruwiki",
    "ruwikiofficial",
    "microsoftstore",
}


def main() -> None:
    rows: list[dict] = []
    with open(INPUT, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f, delimiter=";")
        for row in reader:
            if row.get("is_mutual_related") != "YES":
                continue

            username = (row.get("username") or "").strip()
            username_lower = username.lower()
            if username_lower in BAD_USERS:
                continue
            if re.fullmatch(r"\d+", username_lower):
                continue

            src = (row.get("source_pages") or "").lower()
            if any(bad in src for bad in BAD_SOURCE_HINTS):
                continue
            if not any(good in src for good in GOOD_SOURCE_HINTS):
                continue

            terms = (row.get("matched_terms") or "").lower()
            if not any(term in terms for term in ["взаим", "актив", "лайк", "коммент", "engagement", "like", "comment"]):
                continue

            rows.append(row)

    unique: dict[str, dict] = {}
    for row in rows:
        key = (row.get("username") or "").lower()
        if key and key not in unique:
            unique[key] = row

    clean_rows = list(unique.values())
    clean_rows.sort(key=lambda x: (-int(x.get("sources_count") or 0), (x.get("username") or "").lower()))

    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        fields = [
            "platform",
            "kind",
            "username",
            "url",
            "sources_count",
            "matched_terms",
            "is_mutual_related",
            "source_pages",
        ]
        writer = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        writer.writeheader()
        writer.writerows(clean_rows)

    print(f"Done. Clean rows: {len(clean_rows)}")
    print(f"CSV: {OUTPUT}")


if __name__ == "__main__":
    main()
