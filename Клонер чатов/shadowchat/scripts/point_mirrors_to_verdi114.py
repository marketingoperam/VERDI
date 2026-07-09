"""Point all ai_mirror routes at https://t.me/verdi114 and refresh ShadowChat DB."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

VERDI114_ID = -1002378905143
VERDI114_USER = "verdi114"
VERDI114_LINK = "https://t.me/verdi114"

ROOT = Path(__file__).resolve().parents[2] / "ai_mirror"
SHADOW_DB = Path(__file__).resolve().parents[1] / "data" / "shadowchat.db"


def patch_configs() -> int:
    updated_files = 0
    for path in sorted(ROOT.glob("multi_config*.json")):
        if path.name == "multi_config.example.json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        routes = data.get("routes")
        if not routes:
            continue
        changed = False
        for route in routes:
            if (
                route.get("mirror_chat_id") != VERDI114_ID
                or route.get("mirror_username") != VERDI114_USER
                or route.get("mirror_public_link") != VERDI114_LINK
            ):
                route["mirror_chat_id"] = VERDI114_ID
                route["mirror_username"] = VERDI114_USER
                route["mirror_public_link"] = VERDI114_LINK
                changed = True
        if changed:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            updated_files += 1
            print(f"patched {path.name} ({len(routes)} routes)")
    return updated_files


def patch_shadow_db() -> None:
    if not SHADOW_DB.exists():
        print("shadowchat db missing, skip")
        return
    db = sqlite3.connect(SHADOW_DB)
    db.execute(
        """
        UPDATE mirror_chats
        SET telegram_chat_id=?, title='VERDI 114 (зеркало)', mirror_username=?, is_active=1
        """,
        (VERDI114_ID, VERDI114_USER),
    )
    mirror_row = db.execute(
        "SELECT id FROM mirror_chats WHERE telegram_chat_id=?",
        (VERDI114_ID,),
    ).fetchone()
    if not mirror_row:
        db.execute(
            """
            INSERT INTO mirror_chats (telegram_chat_id, title, mirror_username, is_active, mode)
            VALUES (?, 'VERDI 114 (зеркало)', ?, 1, 'profile_sync')
            """,
            (VERDI114_ID, VERDI114_USER),
        )
        mirror_row = db.execute(
            "SELECT id FROM mirror_chats WHERE telegram_chat_id=?",
            (VERDI114_ID,),
        ).fetchone()
    mirror_id = mirror_row[0]
    db.execute("UPDATE source_chats SET mirror_chat_id=?, is_active=1", (mirror_id,))
    db.commit()
    print(f"shadow db: all sources -> mirror id {mirror_id} ({VERDI114_LINK})")


async def _async_patch_via_app() -> None:
    import sys

    shadow_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(shadow_root))
    from app.db import async_session_factory
    from app.services.ai_mirror import get_ai_mirror_store, sync_routes_to_db

    get_ai_mirror_store(reload=True)
    async with async_session_factory() as db:
        count = await sync_routes_to_db(db)
        await db.commit()
        print(f"sync_routes_to_db updated {count} routes")


def main() -> None:
    n = patch_configs()
    print(f"configs updated: {n}")
    try:
        asyncio.run(_async_patch_via_app())
    except Exception as exc:
        print(f"sync via app failed ({exc}), applying SQL fallback")
        patch_shadow_db()


if __name__ == "__main__":
    main()
