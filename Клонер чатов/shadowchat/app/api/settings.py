from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings, update_runtime_settings
from app.db import get_db
from app.models import AppSettings, SyncLog
from app.schemas import SettingsResponse, SettingsUpdate, SyncLogResponse

router = APIRouter(tags=["settings"])


def _settings_to_response(settings: Settings) -> SettingsResponse:
    return SettingsResponse(
        profile_sync_enabled=settings.profile_sync_enabled,
        profile_sync_interval_hours=settings.profile_sync_interval_hours,
        delete_mode=settings.delete_mode,
        ignore_bots=settings.ignore_bots,
        ignore_service_messages=settings.ignore_service_messages,
        max_media_size_mb=settings.max_media_size_mb,
        message_filter_mode=settings.message_filter_mode,
        min_message_length=settings.min_message_length,
    )


@router.get("/logs", response_model=list[SyncLogResponse])
async def list_logs(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SyncLog).order_by(SyncLog.created_at.desc()).limit(limit).offset(offset)
    )
    return result.scalars().all()


@router.get("/settings", response_model=SettingsResponse)
async def get_settings_endpoint():
    return _settings_to_response(get_settings())


@router.put("/settings", response_model=SettingsResponse)
async def update_settings(data: SettingsUpdate, db: AsyncSession = Depends(get_db)):
    updates = data.model_dump(exclude_unset=True)

    for key, value in updates.items():
        db_key = key.upper()
        result = await db.execute(select(AppSettings).where(AppSettings.key == db_key))
        row = result.scalar_one_or_none()
        if row:
            row.value = str(value)
        else:
            db.add(AppSettings(key=db_key, value=str(value)))
    await db.flush()

    return _settings_to_response(update_runtime_settings(updates))
