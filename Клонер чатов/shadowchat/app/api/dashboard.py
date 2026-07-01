from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.health import get_health_status
from app.models import Employee, MirrorChat, SessionPool, SourceChat, SyncLog
from app.schemas import (
    ChatPairCreate,
    ChatPairResponse,
    DashboardResponse,
    DashboardStats,
    HealthResponse,
    SetupStatusResponse,
    SetupStep,
    SyncLogResponse,
)

router = APIRouter(tags=["dashboard"])


def _check_listener_session_exists() -> bool:
    settings = get_settings()
    session_path = settings.resolved_sessions_dir / f"{settings.listener_session}.session"
    return session_path.exists()


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    health = await get_health_status()
    setup = await _build_setup_status(db)
    stats = await _build_stats(db)

    logs_result = await db.execute(
        select(SyncLog).order_by(SyncLog.created_at.desc()).limit(15)
    )
    recent_logs = logs_result.scalars().all()

    return DashboardResponse(
        stats=stats,
        setup=setup,
        health=health,
        recent_logs=[SyncLogResponse.model_validate(log) for log in recent_logs],
    )


@router.get("/setup", response_model=SetupStatusResponse)
async def get_setup_status(db: AsyncSession = Depends(get_db)):
    return await _build_setup_status(db)


@router.get("/chat-pairs", response_model=list[ChatPairResponse])
async def list_chat_pairs(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SourceChat, MirrorChat)
        .join(MirrorChat, SourceChat.mirror_chat_id == MirrorChat.id)
        .order_by(SourceChat.id)
    )
    pairs = []
    for source, mirror in result.all():
        pairs.append(
            ChatPairResponse(
                source_id=source.id,
                source_telegram_chat_id=source.telegram_chat_id,
                source_title=source.title,
                source_is_active=source.is_active,
                mirror_id=mirror.id,
                mirror_telegram_chat_id=mirror.telegram_chat_id,
                mirror_title=mirror.title,
                mirror_mode=mirror.mode,
                mirror_is_active=mirror.is_active,
                created_at=source.created_at,
            )
        )
    return pairs


@router.post("/chat-pairs", response_model=ChatPairResponse, status_code=201)
async def create_chat_pair(data: ChatPairCreate, db: AsyncSession = Depends(get_db)):
    mirror_existing = await db.execute(
        select(MirrorChat).where(MirrorChat.telegram_chat_id == data.mirror_telegram_chat_id)
    )
    if mirror_existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Зеркальный чат с таким ID уже существует")

    source_existing = await db.execute(
        select(SourceChat).where(SourceChat.telegram_chat_id == data.source_telegram_chat_id)
    )
    if source_existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Исходный чат с таким ID уже существует")

    mirror = MirrorChat(
        telegram_chat_id=data.mirror_telegram_chat_id,
        title=f"{data.title} (зеркало)",
        is_active=data.is_active,
        mode=data.mode,
    )
    db.add(mirror)
    await db.flush()

    source = SourceChat(
        telegram_chat_id=data.source_telegram_chat_id,
        title=data.title,
        is_active=data.is_active,
        mirror_chat_id=mirror.id,
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)
    await db.refresh(mirror)

    return ChatPairResponse(
        source_id=source.id,
        source_telegram_chat_id=source.telegram_chat_id,
        source_title=source.title,
        source_is_active=source.is_active,
        mirror_id=mirror.id,
        mirror_telegram_chat_id=mirror.telegram_chat_id,
        mirror_title=mirror.title,
        mirror_mode=mirror.mode,
        mirror_is_active=mirror.is_active,
        created_at=source.created_at,
    )


async def _build_setup_status(db: AsyncSession) -> SetupStatusResponse:
    settings = get_settings()

    pairs_count = await db.scalar(
        select(func.count(SourceChat.id)).where(SourceChat.mirror_chat_id.isnot(None))
    )
    sessions_count = await db.scalar(
        select(func.count(SessionPool.id)).where(SessionPool.is_active.is_(True))
    )
    assigned_count = await db.scalar(
        select(func.count(SessionPool.id)).where(
            SessionPool.is_active.is_(True),
            SessionPool.assigned_employee_id.isnot(None),
        )
    )

    api_configured = bool(settings.listener_api_id and settings.listener_api_hash)
    session_exists = _check_listener_session_exists()
    has_pairs = (pairs_count or 0) > 0
    has_sessions = (sessions_count or 0) > 0

    steps = [
        SetupStep(
            id="api",
            title="API-ключи Telegram",
            description="Получите api_id и api_hash на my.telegram.org и укажите в файле .env",
            done=api_configured,
            action="help-api",
        ),
        SetupStep(
            id="listener",
            title="Авторизация слушателя",
            description="Запустите scripts/auth_session.py для входа в аккаунт-слушатель",
            done=session_exists,
            action="help-listener",
        ),
        SetupStep(
            id="pairs",
            title="Пары чатов",
            description="Добавьте хотя бы одну пару: исходный чат → зеркальный чат для обучения",
            done=has_pairs,
            action="chats",
        ),
        SetupStep(
            id="sessions",
            title="Технические аккаунты",
            description="Добавьте аккаунт и войдите в него — он сядет в зеркальный чат",
            done=has_sessions,
            action="accounts",
        ),
        SetupStep(
            id="assign",
            title="Автопривязка",
            description="Аккаунт автоматически закрепляется за сотрудником при его первом сообщении",
            done=has_sessions,
            action="accounts",
        ),
    ]

    done_count = sum(1 for s in steps if s.done)
    ready = done_count >= 3 and has_pairs

    return SetupStatusResponse(
        ready=ready,
        progress_percent=int(done_count / len(steps) * 100),
        steps=steps,
    )


async def _build_stats(db: AsyncSession) -> DashboardStats:
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    source_chats = await db.scalar(select(func.count(SourceChat.id))) or 0
    mirror_chats = await db.scalar(select(func.count(MirrorChat.id))) or 0
    active_pairs = await db.scalar(
        select(func.count(SourceChat.id)).where(
            SourceChat.is_active.is_(True),
            SourceChat.mirror_chat_id.isnot(None),
        )
    ) or 0
    employees = await db.scalar(select(func.count(Employee.id))) or 0
    sessions = await db.scalar(
        select(func.count(SessionPool.id)).where(SessionPool.is_active.is_(True))
    ) or 0
    sessions_assigned = await db.scalar(
        select(func.count(SessionPool.id)).where(
            SessionPool.is_active.is_(True),
            SessionPool.assigned_employee_id.isnot(None),
        )
    ) or 0
    messages_today = await db.scalar(
        select(func.count(SyncLog.id)).where(
            SyncLog.event_type == "new_message",
            SyncLog.status == "success",
            SyncLog.created_at >= today_start,
        )
    ) or 0
    errors_today = await db.scalar(
        select(func.count(SyncLog.id)).where(
            SyncLog.status == "error",
            SyncLog.created_at >= today_start,
        )
    ) or 0

    return DashboardStats(
        source_chats=source_chats,
        mirror_chats=mirror_chats,
        active_pairs=active_pairs,
        employees=employees,
        sessions=sessions,
        sessions_assigned=sessions_assigned,
        messages_mirrored_today=messages_today,
        errors_today=errors_today,
    )
