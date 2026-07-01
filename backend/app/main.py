from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from app.api import router
from app.config import get_settings
from app.database import Base, async_session, engine
from app.models import AppSettings, Competitor


async def _seed_settings() -> None:
    env = get_settings()
    async with async_session() as db:
        result = await db.execute(select(AppSettings).where(AppSettings.id == 1))
        row = result.scalar_one_or_none()
        if row is None:
            row = AppSettings(id=1)
            db.add(row)

        row.ai_base_url = env.ai_base_url
        row.ai_api_key = env.ai_api_key or row.ai_api_key
        row.ai_model = env.ai_model
        row.telegram_api_id = env.telegram_api_id or row.telegram_api_id
        row.telegram_api_hash = env.telegram_api_hash or row.telegram_api_hash
        row.google_enabled = env.google_enabled
        row.yandex_enabled = env.yandex_enabled
        row.vk_enabled = env.vk_enabled
        row.telegram_enabled = env.telegram_enabled

        if env.google_api_key:
            row.google_api_key = env.google_api_key
            row.google_cx = env.google_cx
        if env.yandex_api_key:
            row.yandex_api_key = env.yandex_api_key
            row.yandex_folder_id = env.yandex_folder_id
        if env.vk_access_token:
            row.vk_access_token = env.vk_access_token

        await db.commit()


async def _seed_demo_competitor() -> None:
    async with async_session() as db:
        count = await db.execute(select(func.count()).select_from(Competitor))
        if count.scalar_one() > 0:
            return
        db.add(
            Competitor(
                name="InstaChat6",
                region="225",
                brand_keywords=["instachat", "instagram активность"],
                money_keywords=["лайкчат", "подписчики"],
                telegram_channels=["instachat6", "actinsta"],
                google_queries=[],
                yandex_queries=[],
                vk_domains=[],
                vk_owner_ids=[],
                is_active=True,
            )
        )
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    env = get_settings()
    db_path = env.database_url.split("///")[-1]
    data_dir = Path(db_path).parent
    if str(data_dir) not in ("", "."):
        data_dir.mkdir(parents=True, exist_ok=True)
    Path("sessions").mkdir(parents=True, exist_ok=True)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _seed_settings()
    await _seed_demo_competitor()
    yield
    await engine.dispose()


app = FastAPI(title="AI Competitor Search", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}
