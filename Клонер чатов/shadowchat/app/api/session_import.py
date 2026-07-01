from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.schemas import SessionImportResponse, SessionImportStringRequest
from app.telegram.session_import import session_import_service

router = APIRouter(prefix="/sessions", tags=["session-import"])


@router.post("/import/file", response_model=SessionImportResponse)
async def import_session_file(
    session_name: str = Form(...),
    session_file: UploadFile = File(...),
    api_id: int | None = Form(None),
    api_hash: str | None = Form(None),
    journal_file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
):
    if not session_file.filename:
        raise HTTPException(status_code=400, detail="Файл сессии не выбран")

    content = await session_file.read()
    journal_bytes = None
    if journal_file and journal_file.filename:
        journal_bytes = await journal_file.read()

    try:
        return await session_import_service.import_file(
            db,
            session_name,
            content,
            api_id=api_id,
            api_hash=api_hash,
            journal_bytes=journal_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/import/string", response_model=SessionImportResponse)
async def import_session_string(
    data: SessionImportStringRequest,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await session_import_service.import_string(
            db,
            data.session_name,
            data.session_string,
            api_id=data.api_id,
            api_hash=data.api_hash,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
