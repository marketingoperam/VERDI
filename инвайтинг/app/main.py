from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from app.api.routes import bind_services, router
from app.db import async_session_factory, engine
from app.db_migrate import migrate_schema
from app.models import Base
from app.services.inviter import InviteService
from app.services.outreach import OutreachService

logger = structlog.get_logger()

STATIC_DIR = Path(__file__).parent / "static"
_invite: InviteService | None = None
_outreach: OutreachService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _invite, _outreach
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await migrate_schema(engine)

    _invite = InviteService(async_session_factory)
    _outreach = OutreachService(async_session_factory)
    bind_services(_invite, _outreach)

    logger.info("inviting_started", static_dir=str(STATIC_DIR))
    yield

    try:
        if _invite:
            await _invite.stop()
        if _outreach:
            await _outreach.stop()
    except Exception:
        pass
    await engine.dispose()
    logger.info("inviting_stopped")


app = FastAPI(title="Inviting", version="1.1.0", lifespan=lifespan)
app.include_router(router)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def panel():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return HTMLResponse(content=index.read_text(encoding="utf-8"))
    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:40px'>"
        "<h1>Инвайтинг</h1><p>Панель не найдена. Проверьте app/static/</p>"
        "<a href='/docs'>API docs</a></body></html>"
    )


@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)


@app.get("/health")
async def health():
    return {"ok": True}
