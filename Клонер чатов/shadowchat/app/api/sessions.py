from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models import Employee, SessionPool, SessionType
from app.schemas import SessionCreate, SessionDetailResponse, SessionResponse, SessionUpdate
from app.services.employee_binding import EmployeeBindingService

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _session_authorized(session: SessionPool) -> bool:
    if session.session_string:
        return True
    settings = get_settings()
    path = settings.resolved_sessions_dir / f"{session.session_name}.session"
    return path.exists()


def _session_to_detail(session: SessionPool, employee: Employee | None = None) -> SessionDetailResponse:
    name = None
    tg_id = None
    if employee:
        parts = [employee.first_name or ""]
        if employee.last_name:
            parts.append(employee.last_name)
        name = " ".join(parts).strip() or None
        tg_id = employee.telegram_user_id
    return SessionDetailResponse(
        id=session.id,
        session_name=session.session_name,
        session_type=session.session_type,
        api_id=session.api_id,
        assigned_employee_id=session.assigned_employee_id,
        is_active=session.is_active,
        is_fallback=session.is_fallback,
        binding_mode=session.binding_mode,
        last_profile_sync_at=session.last_profile_sync_at,
        last_used_at=session.last_used_at,
        employee_name=name,
        employee_telegram_id=tg_id,
        is_authorized=_session_authorized(session),
    )


@router.get("", response_model=list[SessionDetailResponse])
async def list_sessions(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SessionPool).order_by(SessionPool.id))
    sessions = result.scalars().all()
    details = []
    for session in sessions:
        employee = None
        if session.assigned_employee_id:
            emp_result = await db.execute(
                select(Employee).where(Employee.id == session.assigned_employee_id)
            )
            employee = emp_result.scalar_one_or_none()
        details.append(_session_to_detail(session, employee))
    return details


@router.post("", response_model=SessionResponse, status_code=201)
async def create_session(data: SessionCreate, db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    if not settings.listener_api_id or not settings.listener_api_hash:
        raise HTTPException(
            status_code=400,
            detail="Укажите LISTENER_API_ID и LISTENER_API_HASH в файле .env",
        )

    existing = await db.execute(
        select(SessionPool).where(SessionPool.session_name == data.session_name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Аккаунт с таким именем уже существует")

    session = SessionPool(
        session_name=data.session_name,
        session_type=SessionType.USER.value,
        api_id=settings.listener_api_id,
        api_hash=settings.listener_api_hash,
        bot_token=None,
        is_active=data.is_active,
        is_fallback=False,
        binding_mode="permanent",
    )
    db.add(session)
    await db.flush()
    await db.refresh(session)
    return session


@router.put("/{session_id}", response_model=SessionResponse)
async def update_session(
    session_id: int, data: SessionUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(SessionPool).where(SessionPool.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    updates = data.model_dump(exclude_unset=True)
    if updates.pop("unassign_employee", False):
        session.assigned_employee_id = None
        session.binding_mode = "permanent"

    if "assigned_employee_id" in updates and updates["assigned_employee_id"]:
        binding = EmployeeBindingService(db)
        try:
            await binding.assign_session(
                session_id, updates["assigned_employee_id"], allow_reassign=False
            )
            updates.pop("assigned_employee_id", None)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    for field, value in updates.items():
        setattr(session, field, value)
    await db.flush()
    await db.refresh(session)
    return session
