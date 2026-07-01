from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import (
    SessionAuthCodeRequest,
    SessionAuthPasswordRequest,
    SessionAuthSendCodeRequest,
    SessionAuthStatusResponse,
)
from app.telegram.auth_service import auth_service

router = APIRouter(prefix="/sessions", tags=["session-auth"])


@router.get("/{session_id}/auth/status", response_model=SessionAuthStatusResponse)
async def auth_status(session_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return await auth_service.get_status(db, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{session_id}/auth/send-code", response_model=SessionAuthStatusResponse)
async def auth_send_code(
    session_id: int,
    data: SessionAuthSendCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await auth_service.send_code(
            db,
            session_id,
            data.phone,
            api_id=data.api_id,
            api_hash=data.api_hash,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/auth/verify-code", response_model=SessionAuthStatusResponse)
async def auth_verify_code(
    session_id: int,
    data: SessionAuthCodeRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await auth_service.verify_code(db, session_id, data.code)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/auth/qr-start", response_model=SessionAuthStatusResponse)
async def auth_qr_start(session_id: int, db: AsyncSession = Depends(get_db)):
    try:
        return await auth_service.start_qr(db, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/auth/qr-wait", response_model=SessionAuthStatusResponse)
async def auth_qr_wait(session_id: int):
    try:
        return await auth_service.wait_qr(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{session_id}/auth/verify-password", response_model=SessionAuthStatusResponse)
async def auth_verify_password(
    session_id: int,
    data: SessionAuthPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await auth_service.verify_password(session_id, data.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
