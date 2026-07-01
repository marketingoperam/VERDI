#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def as_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    return []


def build_reason(row: dict) -> str:
    if row.get("is_match"):
        return "Подходит: Instagram-only + взаимная активность + чистый кандидат"

    reasons: list[str] = []
    if not row.get("is_instagram_only"):
        reasons.append("не Instagram-only")
    if not row.get("is_mutual_activity"):
        reasons.append("нет явной взаимной активности")
    if not row.get("is_clean_competitor_candidate"):
        spam = ", ".join(as_str_list(row.get("matched_spam_market_terms")))
        if spam:
            reasons.append(f"маркет/спам маркеры: {spam}")
        else:
            reasons.append("маркет/спам сигналы")

    return "; ".join(reasons) if reasons else "не прошёл фильтры"


def to_readable_rows(data: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for item in data:
        instagram_terms = ", ".join(as_str_list(item.get("matched_instagram_terms")))
        mutual_terms = ", ".join(as_str_list(item.get("matched_mutual_terms")))
        non_inst_terms = ", ".join(as_str_list(item.get("matched_non_instagram_terms")))
        spam_terms = ", ".join(as_str_list(item.get("matched_spam_market_terms")))
        sources = " | ".join(as_str_list(item.get("source_pages")))

        rows.append(
            {
                "Статус": "OK" if item.get("is_match") else "NO",
                "Username": item.get("username", ""),
                "Ссылка": item.get("url", ""),
                "Instagram сигналы": instagram_terms or "-",
                "Сигналы взаимности": mutual_terms or "-",
                "Сигналы других платформ": non_inst_terms or "-",
                "Маркет/спам сигналы": spam_terms or "-",
                "Источник": sources or "-",
                "Причина/Комментарий": build_reason(item),
            }
        )

    rows.sort(key=lambda r: (r["Статус"] != "OK", r["Username"].lower()))
    return rows


def write_csv(path: Path, rows: list[dict], delimiter: str = ";") -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=list(rows[0].keys()),
            delimiter=delimiter,
            quoting=csv.QUOTE_MINIMAL,
        )
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict]) -> None:
    headers = [
        "Статус",
        "Username",
        "Ссылка",
        "Instagram сигналы",
        "Сигналы взаимности",
        "Маркет/спам сигналы",
        "Причина/Комментарий",
    ]
    with path.open("w", encoding="utf-8") as f:
        f.write("# Читаемая таблица кандидатов\n\n")
        f.write("| " + " | ".join(headers) + " |\n")
        f.write("|" + "|".join(["---"] * len(headers)) + "|\n")
        for row in rows:
            values = [str(row[h]).replace("|", "\\|") for h in headers]
            f.write("| " + " | ".join(values) + " |\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build readable table from parser JSON.")
    parser.add_argument(
        "--input-json",
        default="instagram_communities_ru_strict_relaxed.json",
        help="Source JSON file from parser.",
    )
    parser.add_argument(
        "--out-csv",
        default="instagram_communities_readable.csv",
        help="Readable CSV output path.",
    )
    parser.add_argument(
        "--out-md",
        default="instagram_communities_readable.md",
        help="Readable Markdown table output path.",
    )
    parser.add_argument(
        "--out-shortlist-csv",
        default="instagram_communities_shortlist.csv",
        help="CSV with only OK candidates.",
    )
    parser.add_argument(
        "--delimiter",
        default=";",
        help="CSV delimiter. Use ';' for Russian Excel.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    src = Path(args.input_json)
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = to_readable_rows(data)
    shortlist = [row for row in rows if row["Статус"] == "OK"]

    write_csv(Path(args.out_csv), rows, delimiter=args.delimiter)
    write_csv(Path(args.out_shortlist_csv), shortlist, delimiter=args.delimiter)
    write_markdown(Path(args.out_md), rows)

    ok = len(shortlist)
    print(f"Done. Total: {len(rows)}, OK: {ok}")
    print(f"CSV: {args.out_csv}")
    print(f"Shortlist CSV: {args.out_shortlist_csv}")
    print(f"MD:  {args.out_md}")


if __name__ == "__main__":
    main()
