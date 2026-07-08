import redis.asyncio as aioredis
from sqlalchemy import text

import asyncio

from app.config import get_settings
from app.db import async_session_factory
from app.schemas import HealthResponse

_listener_ref = None


def set_listener_ref(listener) -> None:
    global _listener_ref
    _listener_ref = listener


def get_listener_ref():
    return _listener_ref


async def get_health_status() -> HealthResponse:
    db_status = "ok"
    redis_status = "ok"
    listener_status = "ok"

    try:
        async with async_session_factory() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {exc}"

    try:
        settings = get_settings()
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
    except Exception as exc:
        redis_status = f"error: {exc}"

    if _listener_ref is None or not _listener_ref._running:
        listener_status = "stopped"
    elif hasattr(_listener_ref, "is_connected") and not _listener_ref.is_connected():
        listener_status = "disconnected"
    else:
        try:
            client = _listener_ref.session_pool._listener_client
            if client and client.is_connected():
                await asyncio.wait_for(client.get_me(), timeout=8.0)
            else:
                listener_status = "disconnected"
        except Exception as exc:
            listener_status = f"unreachable: {exc}"

    overall = "ok" if all(s == "ok" for s in (db_status, redis_status, listener_status)) else "degraded"
    return HealthResponse(
        status=overall,
        database=db_status,
        redis=redis_status,
        listener=listener_status,
    )
