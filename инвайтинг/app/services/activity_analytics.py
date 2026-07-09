"""Аналитика активности приглашённых в чате (данные из ShadowChat)."""

from __future__ import annotations

from datetime import datetime

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import InviteTarget
from app.schemas import InvitedActivityItem, InvitedActivityResponse
from app.telegram.entities import normalize_username

logger = structlog.get_logger()

ACTIVITY_MIRROR_USERNAME = "verdi114"


def _shadow_base() -> str:
    return (get_settings().shadowchat_api_url or "").strip().rstrip("/")


async def _fetch_json(path: str) -> object | None:
    base = _shadow_base()
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            res = await client.get(f"{base}{path}")
        if res.status_code >= 400:
            logger.warning("shadowchat_fetch_failed", path=path, status=res.status_code)
            return None
        return res.json()
    except Exception as exc:
        logger.warning("shadowchat_unreachable", path=path, error=str(exc))
        return None


async def _resolve_mirror_chat_id() -> tuple[int | None, str | None]:
    summary = await _fetch_json("/api/v1/activity/summary")
    if not isinstance(summary, list) or not summary:
        return None, None

    preferred = next(
        (row for row in summary if str(row.get("mirror_username") or "").lower() == ACTIVITY_MIRROR_USERNAME),
        None,
    )
    row = preferred or summary[0]
    mirror_chat_id = row.get("mirror_chat_id")
    mirror_username = row.get("mirror_username")
    if mirror_chat_id is None:
        return None, mirror_username
    return int(mirror_chat_id), mirror_username


async def get_invited_activity(
    db: AsyncSession,
    *,
    sort: str = "total",
    invited_only: bool = True,
) -> InvitedActivityResponse:
    targets = (
        await db.execute(
            select(InviteTarget).order_by(InviteTarget.invited_at.desc().nullslast(), InviteTarget.id.desc())
        )
    ).scalars().all()

    if invited_only:
        targets = [t for t in targets if t.is_invited and not t.is_skipped]

    mirror_chat_id, mirror_username = await _resolve_mirror_chat_id()
    activity_by_username: dict[str, dict] = {}
    activity_by_user_id: dict[int, dict] = {}

    if mirror_chat_id is not None:
        raw = await _fetch_json(f"/api/v1/activity?mirror_chat_id={mirror_chat_id}&sort=total")
        if isinstance(raw, list):
            for row in raw:
                uname = normalize_username(row.get("username"))
                if uname:
                    activity_by_username[uname] = row
                uid = row.get("telegram_user_id")
                if uid is not None:
                    activity_by_user_id[int(uid)] = row

    items: list[InvitedActivityItem] = []
    messages_total = 0
    reactions_total = 0
    with_activity = 0

    for target in targets:
        uname = normalize_username(target.username)
        activity = None
        if uname and uname in activity_by_username:
            activity = activity_by_username[uname]
        elif target.user_id and int(target.user_id) in activity_by_user_id:
            activity = activity_by_user_id[int(target.user_id)]

        message_count = int(activity.get("message_count", 0)) if activity else 0
        reaction_count = int(activity.get("reaction_count", 0)) if activity else 0
        total_count = message_count + reaction_count
        last_active_at = activity.get("last_active_at") if activity else None
        if isinstance(last_active_at, str):
            try:
                last_active_at = datetime.fromisoformat(last_active_at.replace("Z", "+00:00"))
            except Exception:
                last_active_at = None

        if total_count > 0:
            with_activity += 1
        messages_total += message_count
        reactions_total += reaction_count

        items.append(
            InvitedActivityItem(
                id=target.id,
                username=target.username,
                user_id=target.user_id,
                is_invited=target.is_invited,
                invited_at=target.invited_at,
                is_messaged=target.is_messaged,
                messaged_at=target.messaged_at,
                message_count=message_count,
                reaction_count=reaction_count,
                total_count=total_count,
                last_active_at=last_active_at,
                tech_session=activity.get("tech_session") if activity else None,
                has_activity=total_count > 0,
            )
        )

    if sort == "invited_at":
        items.sort(key=lambda r: (r.invited_at is None, r.invited_at or datetime.min), reverse=True)
    elif sort == "messages":
        items.sort(key=lambda r: (-r.message_count, r.username or ""))
    elif sort == "reactions":
        items.sort(key=lambda r: (-r.reaction_count, r.username or ""))
    elif sort == "username":
        items.sort(key=lambda r: (r.username or "", r.id))
    elif sort == "last_active":
        items.sort(
            key=lambda r: (r.last_active_at is None, r.last_active_at or datetime.min),
            reverse=True,
        )
    else:
        items.sort(key=lambda r: (-r.total_count, r.username or ""))

    return InvitedActivityResponse(
        shadowchat_reachable=mirror_chat_id is not None,
        mirror_username=mirror_username,
        mirror_chat_id=mirror_chat_id,
        invited_total=len(items),
        with_activity=with_activity,
        messages_total=messages_total,
        reactions_total=reactions_total,
        items=items,
    )


async def trigger_activity_backfill() -> dict:
    base = _shadow_base()
    if not base:
        raise ValueError("ShadowChat не настроен (INV_SHADOWCHAT_API_URL)")

    mirror_chat_id, _ = await _resolve_mirror_chat_id()
    if mirror_chat_id is None:
        raise ValueError("Не найден чат активности в ShadowChat")

    async with httpx.AsyncClient(timeout=120.0) as client:
        res = await client.post(
            f"{base}/api/v1/activity/backfill",
            params={"mirror_chat_id": mirror_chat_id, "limit": 5000},
        )
    if res.status_code >= 400:
        detail = res.text[:300]
        raise ValueError(f"ShadowChat backfill failed: {detail}")
    return res.json()
