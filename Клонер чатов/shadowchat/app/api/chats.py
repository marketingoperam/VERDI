from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import MirrorChat, SourceChat
from app.schemas import (
    MirrorChatCreate,
    MirrorChatResponse,
    MirrorChatUpdate,
    SourceChatCreate,
    SourceChatResponse,
    SourceChatUpdate,
)

source_router = APIRouter(prefix="/source-chats", tags=["source-chats"])
mirror_router = APIRouter(prefix="/mirror-chats", tags=["mirror-chats"])


@source_router.get("", response_model=list[SourceChatResponse])
async def list_source_chats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SourceChat).order_by(SourceChat.id))
    return result.scalars().all()


@source_router.post("", response_model=SourceChatResponse, status_code=201)
async def create_source_chat(data: SourceChatCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(SourceChat).where(SourceChat.telegram_chat_id == data.telegram_chat_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Source chat already exists")

    chat = SourceChat(**data.model_dump())
    db.add(chat)
    await db.flush()
    await db.refresh(chat)
    return chat


@source_router.put("/{chat_id}", response_model=SourceChatResponse)
async def update_source_chat(
    chat_id: int, data: SourceChatUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(SourceChat).where(SourceChat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Source chat not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(chat, field, value)
    await db.flush()
    await db.refresh(chat)
    return chat


@mirror_router.get("", response_model=list[MirrorChatResponse])
async def list_mirror_chats(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(MirrorChat).order_by(MirrorChat.id))
    return result.scalars().all()


@mirror_router.post("", response_model=MirrorChatResponse, status_code=201)
async def create_mirror_chat(data: MirrorChatCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(MirrorChat).where(MirrorChat.telegram_chat_id == data.telegram_chat_id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Mirror chat already exists")

    chat = MirrorChat(**data.model_dump())
    db.add(chat)
    await db.flush()
    await db.refresh(chat)
    return chat


@mirror_router.put("/{chat_id}", response_model=MirrorChatResponse)
async def update_mirror_chat(
    chat_id: int, data: MirrorChatUpdate, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(MirrorChat).where(MirrorChat.id == chat_id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Mirror chat not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(chat, field, value)
    await db.flush()
    await db.refresh(chat)
    return chat
