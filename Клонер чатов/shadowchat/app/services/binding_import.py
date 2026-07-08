"""Импорт привязок sender → tech из ai_mirror (sender_bindings_*.json)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Employee, SessionPool

logger = structlog.get_logger()

ROUTE_PRIORITY = (
    "verdi7_задания",
    "verdi10_задания",
    "verdi13_задания",
    "verdi7_отчеты",
    "verdi10_отчеты",
    "verdi13_отчеты",
)

TEST_SESSION_RE = re.compile(r"^tech_\d{1,2}$")


def _pick_binding_per_sender(bindings: dict[str, str]) -> dict[int, str]:
    by_sender: dict[int, list[tuple[str, str]]] = {}
    for key, session_name in bindings.items():
        route, sender_raw = key.split(":", 1)
        by_sender.setdefault(int(sender_raw), []).append((route, session_name))

    chosen: dict[int, str] = {}
    for sender_id, items in by_sender.items():
        items.sort(key=lambda x: (ROUTE_PRIORITY.index(x[0]) if x[0] in ROUTE_PRIORITY else 99, x[0]))
        chosen[sender_id] = items[0][1]
    return chosen


async def deactivate_test_sessions(db: AsyncSession) -> int:
    result = await db.execute(select(SessionPool).where(SessionPool.is_active.is_(True)))
    count = 0
    for session in result.scalars():
        if TEST_SESSION_RE.match(session.session_name):
            session.is_active = False
            session.assigned_employee_id = None
            count += 1
    if count:
        await db.flush()
    return count


async def import_sender_bindings(
    db: AsyncSession,
    bindings_path: Path,
    *,
    reset_existing: bool = False,
) -> dict[str, int]:
    if not bindings_path.exists():
        return {"imported": 0, "skipped": 0, "conflicts": 0}

    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    chosen = _pick_binding_per_sender(bindings)

    if reset_existing:
        result = await db.execute(select(SessionPool))
        for session in result.scalars():
            if session.session_name != "listener_main":
                session.assigned_employee_id = None

    imported = skipped = conflicts = 0
    for sender_id, session_name in chosen.items():
        session_result = await db.execute(
            select(SessionPool).where(SessionPool.session_name == session_name)
        )
        session = session_result.scalar_one_or_none()
        if not session or not session.is_active:
            skipped += 1
            continue

        employee_result = await db.execute(
            select(Employee).where(Employee.telegram_user_id == sender_id)
        )
        employee = employee_result.scalar_one_or_none()
        if not employee:
            employee = Employee(
                telegram_user_id=sender_id,
                first_name=f"User {sender_id}",
                consent_signed=False,
            )
            db.add(employee)
            await db.flush()

        if session.assigned_employee_id and session.assigned_employee_id != employee.id:
            conflicts += 1
            continue

        existing = await db.execute(
            select(SessionPool).where(
                SessionPool.assigned_employee_id == employee.id,
                SessionPool.id != session.id,
            )
        )
        if existing.scalar_one_or_none():
            conflicts += 1
            continue

        session.assigned_employee_id = employee.id
        session.binding_mode = "permanent"
        imported += 1

    await db.flush()
    logger.info(
        "sender_bindings_imported",
        path=str(bindings_path),
        imported=imported,
        skipped=skipped,
        conflicts=conflicts,
    )
    return {"imported": imported, "skipped": skipped, "conflicts": conflicts}
