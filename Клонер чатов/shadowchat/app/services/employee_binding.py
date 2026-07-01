import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, SessionPool
from app.services.message_mapper import MessageMapper

logger = structlog.get_logger()


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

    async def get_session_for_employee(self, employee_id: int) -> SessionPool | None:
        result = await self.db.execute(
            select(SessionPool).where(
                SessionPool.assigned_employee_id == employee_id,
                SessionPool.is_active.is_(True),
                SessionPool.binding_mode == "permanent",
            )
        )
        return result.scalar_one_or_none()

    async def get_fallback_session(self) -> SessionPool | None:
        result = await self.db.execute(
            select(SessionPool).where(
                SessionPool.is_fallback.is_(True),
                SessionPool.is_active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    async def _get_free_account(self) -> SessionPool | None:
        result = await self.db.execute(
            select(SessionPool)
            .where(
                SessionPool.is_active.is_(True),
                SessionPool.session_type == "user",
                SessionPool.is_fallback.is_(False),
                SessionPool.assigned_employee_id.is_(None),
            )
            .order_by(SessionPool.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _get_any_active_account(self) -> SessionPool | None:
        result = await self.db.execute(
            select(SessionPool)
            .where(
                SessionPool.is_active.is_(True),
                SessionPool.session_type == "user",
            )
            .order_by(SessionPool.last_used_at.asc().nullsfirst(), SessionPool.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def resolve_session(
        self, employee: Employee, mirror_mode: str = "safe"
    ) -> tuple[SessionPool | None, bool]:
        """Returns (session, used_shared_account)."""
        session = await self.get_session_for_employee(employee.id)
        if session:
            return session, False

        free = await self._get_free_account()
        if free:
            free.assigned_employee_id = employee.id
            free.binding_mode = "permanent"
            await self.db.flush()
            logger.info(
                "account_auto_assigned",
                employee_id=employee.id,
                telegram_user_id=employee.telegram_user_id,
                session_name=free.session_name,
            )
            return free, False

        fallback = await self.get_fallback_session()
        if fallback:
            logger.warning(
                "using_fallback_session",
                employee_id=employee.id,
                telegram_user_id=employee.telegram_user_id,
                fallback_session=fallback.session_name,
            )
            return fallback, True

        if mirror_mode == "safe":
            shared = await self._get_any_active_account()
            if shared:
                logger.info(
                    "using_shared_account",
                    employee_id=employee.id,
                    session_name=shared.session_name,
                )
                return shared, True

        logger.error(
            "no_account_for_employee",
            employee_id=employee.id,
            telegram_user_id=employee.telegram_user_id,
        )
        return None, False

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
