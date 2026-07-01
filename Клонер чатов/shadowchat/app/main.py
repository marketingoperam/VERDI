import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import APIRouter, FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.api import chats, dashboard, employees, session_auth, session_import, sessions, settings as settings_api
from app.config import get_settings
from app.db import async_session_factory, engine
from app.health import get_health_status, set_listener_ref
from app.logging_config import setup_logging
from app.models import AppSettings, Base
from app.telegram.listener import TelegramListener

logger = structlog.get_logger()
_listener_task: asyncio.Task | None = None
_listener: TelegramListener | None = None

STATIC_DIR = Path(__file__).parent / "static"


def _should_start_listener() -> bool:
    settings = get_settings()
    if not settings.listener_api_id or not settings.listener_api_hash:
        return False
    if settings.listener_api_hash.startswith("xxxx"):
        return False
    session_file = settings.resolved_sessions_dir / f"{settings.listener_session}.session"
    return session_file.exists()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _listener_task, _listener
    setup_logging()
    settings = get_settings()

    try:
        settings.resolved_sessions_dir.mkdir(parents=True, exist_ok=True)
        settings.resolved_media_cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        logger.warning("dirs_create_failed", error=str(exc))

    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            if settings.database_url.startswith("sqlite"):
                from sqlalchemy import text

                try:
                    await conn.execute(
                        text("ALTER TABLE session_pool ADD COLUMN session_string TEXT")
                    )
                except Exception:
                    pass
    except Exception as exc:
        logger.warning("db_init_failed", error=str(exc))

    try:
        async with async_session_factory() as db:
            from app.telegram.session_import import session_import_service

            synced = await session_import_service.sync_disk_sessions(db)
            if synced:
                logger.info("sessions_synced_from_disk", count=synced)
            await db.commit()

            result = await db.execute(select(AppSettings))
            from app.config import update_runtime_settings

            overrides = {}
            for row in result.scalars().all():
                key = row.key.lower()
                if hasattr(settings, key):
                    field_type = type(getattr(settings, key))
                    if field_type is bool:
                        overrides[key] = row.value.lower() in ("true", "1", "yes")
                    elif field_type is int:
                        overrides[key] = int(row.value)
                    else:
                        overrides[key] = row.value
            if overrides:
                update_runtime_settings(overrides)
    except Exception as exc:
        logger.warning("settings_load_failed", error=str(exc))

    try:
        if _should_start_listener():
            _listener = TelegramListener()
            set_listener_ref(_listener)
            _listener_task = asyncio.create_task(_listener.start())
        else:
            logger.info("listener_skipped", reason="session not configured yet")
    except Exception as exc:
        logger.warning("listener_start_failed", error=str(exc))

    logger.info("shadowchat_started", env=settings.app_env, static_dir=str(STATIC_DIR))

    yield

    if _listener:
        await _listener.stop()
    if _listener_task:
        _listener_task.cancel()
        try:
            await _listener_task
        except asyncio.CancelledError:
            pass
    await engine.dispose()
    logger.info("shadowchat_stopped")


app = FastAPI(
    title="ShadowChat",
    description="Internal Telegram chat mirroring for employee onboarding",
    version="1.0.0",
    lifespan=lifespan,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(chats.source_router)
api_router.include_router(chats.mirror_router)
api_router.include_router(employees.router)
api_router.include_router(sessions.router)
api_router.include_router(session_auth.router)
api_router.include_router(session_import.router)
api_router.include_router(settings_api.router)
api_router.include_router(dashboard.router)
app.include_router(api_router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def admin_panel():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:40px'>"
        "<h1>ShadowChat</h1><p>Панель не найдена. Проверьте папку app/static/</p>"
        "<a href='/docs'>API docs</a></body></html>"
    )


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/health")
async def healthcheck():
    return await get_health_status()
