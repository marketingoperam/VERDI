"""Импорт .session файлов техаккаунтов в shadowchat/sessions и обновление конфигов пулов."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent
SHADOWCHAT_SESSIONS = ROOT.parent / "shadowchat" / "sessions"
CONFIGS = [
    ROOT / "multi_config.verdi7.json",
    ROOT / "multi_config.verdi10.json",
    ROOT / "multi_config.verdi13.json",
]


def session_name_from(path: Path) -> str:
    name = path.stem.lstrip("+")
    if not name.isdigit():
        raise ValueError(f"неожиданное имя сессии: {path.name}")
    return name


def import_sessions(source_dir: Path) -> list[str]:
    SHADOWCHAT_SESSIONS.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for src in sorted(source_dir.glob("*.session")):
        name = session_name_from(src)
        dst = SHADOWCHAT_SESSIONS / f"{name}.session"
        shutil.copy2(src, dst)
        journal = src.with_name(f"{src.stem}.session-journal")
        if journal.exists():
            shutil.copy2(journal, dst.with_name(f"{name}.session-journal"))
        names.append(name)
    return names


def update_configs(names: list[str]) -> None:
    for cfg_path in CONFIGS:
        if not cfg_path.exists():
            continue
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        data["tech_sessions"] = names
        cfg_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"  обновлён {cfg_path.name}: {len(names)} аккаунтов")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("source", type=Path, help="папка с *.session")
    p.add_argument("--manifest", type=Path, default=ROOT / "tech_sessions_manifest.json")
    args = p.parse_args()

    if not args.source.is_dir():
        raise SystemExit(f"Папка не найдена: {args.source}")

    names = import_sessions(args.source)
    if not names:
        raise SystemExit("Нет .session файлов")

    print(f"Скопировано: {len(names)} сессий → {SHADOWCHAT_SESSIONS}")
    update_configs(names)

    args.manifest.write_text(
        json.dumps({"tech_sessions": names}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Манифест: {args.manifest.name}")


if __name__ == "__main__":
    main()
