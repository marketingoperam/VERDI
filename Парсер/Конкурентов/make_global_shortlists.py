#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_rows(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter=";")
        w.writeheader()
        w.writerows(rows)


def as_joined(v) -> str:
    if isinstance(v, list):
        return ", ".join(str(x) for x in v if str(x).strip()) or "-"
    return str(v) if v not in (None, "") else "-"


def to_readable(rows: list[dict]) -> list[dict]:
    out: list[dict] = []
    for r in rows:
        out.append(
            {
                "URL": r.get("url", ""),
                "Платформа": r.get("platform", ""),
                "Тип": r.get("kind", ""),
                "Источников": r.get("source_count", 0),
                "Instagram сигналы": as_joined(r.get("matched_instagram_terms")),
                "Взаимность сигналы": as_joined(r.get("matched_mutual_terms")),
                "Service сигналы": as_joined(r.get("matched_service_terms")),
                "Релевантно": "YES" if r.get("is_relevant") else "NO",
                "Confidence": r.get("confidence", ""),
                "Где найдено": " | ".join(r.get("source_pages", [])[:5]),
            }
        )
    out.sort(key=lambda x: (-int(x["Источников"]), x["Платформа"], x["URL"]))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Build strict/wide shortlists from global parser JSON.")
    p.add_argument("--input-json", default="all_instagram_mutual_candidates_v3.json")
    p.add_argument("--out-strict-communities", default="global_communities_strict.csv")
    p.add_argument("--out-wide-communities", default="global_communities_wide.csv")
    p.add_argument("--out-wide-services", default="global_services_wide.csv")
    args = p.parse_args()

    rows = load_rows(Path(args.input_json))
    strict_communities = [
        r
        for r in rows
        if r.get("kind") == "community" and r.get("is_relevant") and r.get("confidence") in {"medium", "high"}
    ]
    wide_communities = [
        r
        for r in rows
        if r.get("kind") == "community" and (r.get("is_instagram_related") or r.get("is_mutual_related"))
    ]
    wide_services = [
        r
        for r in rows
        if r.get("kind") == "service_or_article"
        and (r.get("is_instagram_related") or r.get("is_mutual_related") or r.get("matched_service_terms"))
    ]

    save_csv(Path(args.out_strict_communities), to_readable(strict_communities))
    save_csv(Path(args.out_wide_communities), to_readable(wide_communities))
    save_csv(Path(args.out_wide_services), to_readable(wide_services))

    print(f"Strict communities: {len(strict_communities)} -> {args.out_strict_communities}")
    print(f"Wide communities: {len(wide_communities)} -> {args.out_wide_communities}")
    print(f"Wide services: {len(wide_services)} -> {args.out_wide_services}")


if __name__ == "__main__":
    main()
