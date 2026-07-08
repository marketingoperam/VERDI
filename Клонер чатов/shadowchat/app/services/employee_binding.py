import re

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import Employee, SessionPool, SourceChat
from app.services.ai_mirror import get_ai_mirror_store

logger = structlog.get_logger()

TEST_SESSION_RE = re.compile(r"^tech_\d{1,2}$")


class EmployeeBindingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_employee(
        self,
        telegram_user_id: int,
        first_name: str = "",
        last_name: str | None = None,
        username: str | None = None,
    ) -> Employee:
        result = await self.db.execute(
            select(Employee).where(Employee.telegram_user_id == telegram_user_id)
        )
        employee = result.scalar_one_or_none()
        if employee:
            changed = False
            if first_name and employee.first_name != first_name:
                employee.first_name = first_name
                changed = True
            if last_name is not None and employee.last_name != last_name:
                employee.last_name = last_name
                changed = True
            if username is not None and employee.username != username:
                employee.username = username
                changed = True
            if changed:
                await self.db.flush()
            return employee

        employee = Employee(
            telegram_user_id=telegram_user_id,
            first_name=first_name or "Unknown",
            last_name=last_name,
            username=username,
            consent_signed=False,
        )
        self.db.add(employee)
        await self.db.flush()
        logger.info(
            "employee_created",
            telegram_user_id=telegram_user_id,
            employee_id=employee.id,
        )
        return employee

    def _exclude_listener(self, query):
        listener_name = get_settings().listener_session
        return query.where(SessionPool.session_name != listener_name)

    async def resolve_session(
        self,
        employee: Employee,
        source_chat: SourceChat,
        mirror_mode: str = "safe",
    ) -> tuple[SessionPool | None, bool]:
        """Привязка как в ai_mirror: route_name:sender_id → tech session."""
        route_name = source_chat.route_name
        if not route_name:
            store = get_ai_mirror_store()
            route = store.route_for_source(source_chat.telegram_chat_id)
            if route:
                route_name = route.name
                source_chat.route_name = route_name
                await self.db.flush()

        if route_name:
            return await self._resolve_via_ai_mirror(route_name, employee)

        logger.error(
            "no_route_for_source_chat",
            source_chat_id=source_chat.id,
            telegram_chat_id=source_chat.telegram_chat_id,
        )
        return None, False

    async def _resolve_via_ai_mirror(
        self, route_name: str, employee: Employee
    ) -> tuple[SessionPool | None, bool]:
        store = get_ai_mirror_store()
        try:
            session_name = store.assign_session(route_name, employee.telegram_user_id)
        except RuntimeError as exc:
            logger.error("ai_mirror_pool_empty", route=route_name, error=str(exc))
            return None, False

        result = await self.db.execute(
            select(SessionPool).where(
                SessionPool.session_name == session_name,
                SessionPool.is_active.is_(True),
            )
        )
        session = result.scalar_one_or_none()
        if not session:
            logger.error("ai_mirror_session_missing", session_name=session_name)
            return None, False
        return session, False

    async def assign_session(
        self, session_id: int, employee_id: int, *, allow_reassign: bool = False
    ) -> SessionPool:
        result = await self.db.execute(select(SessionPool).where(SessionPool.id == session_id))
        session = result.scalar_one()
        if not allow_reassign:
            existing = await self.db.execute(
                select(SessionPool).where(
                    SessionPool.assigned_employee_id == employee_id,
                    SessionPool.id != session_id,
                    SessionPool.is_active.is_(True),
                )
            )
            if existing.scalar_one_or_none():
                raise ValueError("Employee already has a permanent session assigned")

            if session.assigned_employee_id and session.assigned_employee_id != employee_id:
                raise ValueError("Session already assigned to another employee")

        session.assigned_employee_id = employee_id
        session.binding_mode = "permanent"
        await self.db.flush()
        logger.info(
            "session_assigned",
            session_id=session_id,
            employee_id=employee_id,
            session_name=session.session_name,
        )
        return session
