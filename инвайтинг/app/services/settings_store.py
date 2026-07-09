from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppSetting
from app.schemas import RuntimeSettings


DEFAULT_CHAT_LINK = "https://t.me/verdi114"
DEFAULT_OUTREACH_MESSAGE = "Привет! Добавили вас в чат VERDI — напишите, если есть вопросы."

DEFAULTS = RuntimeSettings(
    chat_link=DEFAULT_CHAT_LINK,
    min_delay_seconds=45,
    daily_limit=50,
    inviter_sessions=["inviter_01", "inviter_02", "inviter_03", "inviter_04", "inviter_05"],
    outreach_sessions=["outreach1"],
    outreach_enabled=True,
    outreach_message=DEFAULT_OUTREACH_MESSAGE,
    outreach_delay_seconds=60,
    outreach_daily_limit=20,
)


async def get_runtime_settings(db: AsyncSession) -> RuntimeSettings:
    result = await db.execute(select(AppSetting))
    rows = {r.key: r for r in result.scalars().all()}
    data = DEFAULTS.model_dump()

    for key in (
        "chat_link",
        "min_delay_seconds",
        "daily_limit",
        "outreach_enabled",
        "outreach_message",
        "outreach_delay_seconds",
        "outreach_daily_limit",
    ):
        if key not in rows:
            continue
        raw = rows[key].value
        if key in (
            "min_delay_seconds",
            "daily_limit",
            "outreach_delay_seconds",
            "outreach_daily_limit",
        ):
            try:
                data[key] = int(raw)
            except Exception:
                pass
        elif key == "outreach_enabled":
            data[key] = raw.strip().lower() in {"1", "true", "yes", "on"}
        else:
            data[key] = raw

    for key in ("inviter_sessions", "outreach_sessions"):
        if key in rows:
            raw = rows[key].value.strip()
            if raw:
                data[key] = [p.strip() for p in raw.split(",") if p.strip()]

    return RuntimeSettings(**data)


async def set_runtime_settings(db: AsyncSession, settings: RuntimeSettings) -> None:
    now = datetime.utcnow()
    kv: dict[str, str] = {
        "chat_link": settings.chat_link.strip(),
        "min_delay_seconds": str(settings.min_delay_seconds),
        "daily_limit": str(settings.daily_limit),
        "inviter_sessions": ",".join([s.strip() for s in settings.inviter_sessions if s.strip()]),
        "outreach_sessions": ",".join([s.strip() for s in settings.outreach_sessions if s.strip()]),
        "outreach_enabled": "true" if settings.outreach_enabled else "false",
        "outreach_message": settings.outreach_message.strip(),
        "outreach_delay_seconds": str(settings.outreach_delay_seconds),
        "outreach_daily_limit": str(settings.outreach_daily_limit),
    }

    for key, value in kv.items():
        row = await db.get(AppSetting, key)
        if row is None:
            row = AppSetting(key=key, value=value, updated_at=now)
            db.add(row)
        else:
            row.value = value
            row.updated_at = now
