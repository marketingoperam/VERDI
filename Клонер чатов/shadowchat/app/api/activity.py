from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import async_session_factory, get_db
from app.health import get_listener_ref
from app.models import MirrorChat, SessionPool, SourceChat, UserActivity
from app.schemas import UserActivityResponse, UserActivitySummary
from app.services.activity_backfill import backfill_all_activity_mirrors, backfill_mirror_chat
from app.services.activity_config import ACTIVITY_MIRROR_USERNAMES

router = APIRouter(prefix="/activity", tags=["activity"])

_tech_user_session_cache: dict[int, str] | None = None


def _display_name(row: UserActivity) -> str:
    parts = [row.first_name or ""]
    if row.last_name:
        parts.append(row.last_name)
    name = " ".join(parts).strip()
    if row.username:
        return f"{name} (@{row.username})" if name else f"@{row.username}"
    return name or str(row.telegram_user_id)


async def _tech_session_for_telegram_user(telegram_user_id: int) -> str | None:
    global _tech_user_session_cache
    if _tech_user_session_cache is not None:
        return _tech_user_session_cache.get(telegram_user_id)

    listener = get_listener_ref()
    if not listener:
        return None

    mapping: dict[int, str] = {}
    settings = get_settings()
    pool = listener.session_pool
    async with async_session_factory() as db:
        result = await db.execute(
            select(SessionPool).where(
                SessionPool.is_active.is_(True),
                SessionPool.session_name != settings.listener_session,
            )
        )
        sessions = list(result.scalars().all())

    for session in sessions:
        try:
            client = await pool.get_client_for_session(session)
            me = await client.get_me()
            mapping[me.id] = session.session_name
        except Exception:
            continue

    _tech_user_session_cache = mapping
    return mapping.get(telegram_user_id)


@router.get("", response_model=list[UserActivityResponse])
async def list_activity(
    mirror_chat_id: int = Query(..., description="ID клон-чата в БД"),
    sort: str = Query("messages", pattern="^(messages|reactions|total|name)$"),
    db: AsyncSession = Depends(get_db),
):
    chat_result = await db.execute(
        select(MirrorChat).where(
            MirrorChat.id == mirror_chat_id,
            MirrorChat.mirror_username.in_(ACTIVITY_MIRROR_USERNAMES),
        )
    )
    mirror = chat_result.scalar_one_or_none()
    if not mirror:
        raise HTTPException(status_code=404, detail="Клон-чат не найден")

    result = await db.execute(
        select(UserActivity).where(UserActivity.mirror_chat_id == mirror_chat_id)
    )
    rows = list(result.scalars().all())

    if sort == "reactions":
        rows.sort(key=lambda r: (-r.reaction_count, r.first_name))
    elif sort == "total":
        rows.sort(key=lambda r: (-(r.message_count + r.reaction_count), r.first_name))
    elif sort == "name":
        rows.sort(key=lambda r: (r.first_name.lower(), r.username or ""))
    else:
        rows.sort(key=lambda r: (-r.message_count, r.first_name))

    responses: list[UserActivityResponse] = []
    for row in rows:
        tech_session = await _tech_session_for_telegram_user(row.telegram_user_id)
        responses.append(
            UserActivityResponse(
                telegram_user_id=row.telegram_user_id,
                username=row.username,
                display_name=_display_name(row),
                message_count=row.message_count,
                reaction_count=row.reaction_count,
                total_count=row.message_count + row.reaction_count,
                last_active_at=row.last_active_at,
                tech_session=tech_session,
            )
        )
    return responses


@router.get("/summary", response_model=list[UserActivitySummary])
async def activity_summary(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(
            MirrorChat.id,
            MirrorChat.title,
            MirrorChat.mirror_username,
            func.max(SourceChat.route_name),
            func.count(UserActivity.id),
            func.coalesce(func.sum(UserActivity.message_count), 0),
            func.coalesce(func.sum(UserActivity.reaction_count), 0),
        )
        .outerjoin(UserActivity, UserActivity.mirror_chat_id == MirrorChat.id)
        .outerjoin(SourceChat, SourceChat.mirror_chat_id == MirrorChat.id)
        .where(
            MirrorChat.mirror_username.in_(ACTIVITY_MIRROR_USERNAMES),
            MirrorChat.is_active.is_(True),
        )
        .group_by(MirrorChat.id)
        .order_by(MirrorChat.mirror_username)
    )
    return [
        UserActivitySummary(
            mirror_chat_id=row[0],
            title=row[1],
            mirror_username=row[2],
            route_name=row[3],
            users_count=row[4] or 0,
            messages_total=int(row[5] or 0),
            reactions_total=int(row[6] or 0),
        )
        for row in result.all()
    ]


@router.post("/backfill")
async def backfill_activity(
    mirror_chat_id: int | None = Query(None),
    limit: int = Query(3000, ge=100, le=20000),
):
    listener = get_listener_ref()
    if not listener:
        raise HTTPException(status_code=503, detail="Слушатель не запущен")

    pool = listener.session_pool
    if mirror_chat_id:
        try:
            stats = await backfill_mirror_chat(pool, mirror_chat_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except OperationalError as exc:
            raise HTTPException(
                status_code=503,
                detail="База занята, повторите сканирование через несколько секунд",
            ) from exc
        return {"status": "ok", "mirror_chat_id": mirror_chat_id, **stats}

    stats = await backfill_all_activity_mirrors(pool, limit=limit)
    return {"status": "ok", "chats": stats}
