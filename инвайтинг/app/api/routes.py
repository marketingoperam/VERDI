from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, File, HTTPException, UploadFile
from sqlalchemy import func, select

from app.db import async_session_factory
from app.models import Account, InviteLog, InviteTarget
from app.schemas import (
    AccountCreate,
    AccountItem,
    AuthSendCode,
    AuthVerifyCode,
    AuthVerifyPassword,
    InvitedActivityResponse,
    ImportResponse,
    LogItem,
    RuntimeSettings,
    StatusResponse,
    TargetItem,
)
from app.services.activity_analytics import get_invited_activity, trigger_activity_backfill
from app.services.connector_sync import sync_outreach_to_inbox
from app.services.csv_import import import_targets_file
from app.services.inviter import InviteService
from app.services.outreach import OutreachService
from app.services.settings_store import get_runtime_settings, set_runtime_settings
from app.telegram.auth_service import auth_service

router = APIRouter(prefix="/api/v1")

invite_service: InviteService | None = None
outreach_service: OutreachService | None = None


def bind_services(invite: InviteService, outreach: OutreachService) -> None:
    global invite_service, outreach_service
    invite_service = invite
    outreach_service = outreach


def bind_invite_service(svc: InviteService) -> None:
    """Backward-compatible alias."""
    global invite_service
    invite_service = svc


def _account_item(a: Account) -> AccountItem:
    return AccountItem(
        id=a.id,
        name=a.name,
        role=a.role,
        phone=a.phone,
        username=a.username,
        telegram_user_id=a.telegram_user_id,
        is_authorized=a.is_authorized,
        is_active=a.is_active,
        last_error=a.last_error,
    )


@router.get("/settings", response_model=RuntimeSettings)
async def api_get_settings():
    async with async_session_factory() as db:
        return await get_runtime_settings(db)


@router.put("/settings")
async def api_put_settings(body: RuntimeSettings):
    inviters = [s for s in body.inviter_sessions if s.strip()]
    outreach = [s for s in body.outreach_sessions if s.strip()]
    if not inviters:
        raise HTTPException(status_code=400, detail="Укажите хотя бы 1 аккаунт-инвайтер")
    if body.outreach_enabled and not outreach:
        raise HTTPException(status_code=400, detail="Для отписки укажите хотя бы 1 outreach-аккаунт")
    overlap = set(inviters) & set(outreach)
    if overlap:
        raise HTTPException(
            status_code=400,
            detail=f"Аккаунты для инвайта и отписки должны быть разными: {', '.join(sorted(overlap))}",
        )
    if body.outreach_enabled and not (body.outreach_message or "").strip():
        raise HTTPException(status_code=400, detail="Укажите текст холодной отписки")

    async with async_session_factory() as db:
        # verify outreach accounts exist & authorized when enabled
        if body.outreach_enabled:
            res = await db.execute(
                select(func.count(Account.id)).where(
                    Account.name.in_(outreach),
                    Account.role == "outreach",
                    Account.is_authorized.is_(True),
                    Account.is_active.is_(True),
                    Account.session_string.is_not(None),
                )
            )
            ready = int(res.scalar() or 0)
            if ready < 1:
                raise HTTPException(
                    status_code=400,
                    detail="Нет авторизованных outreach-аккаунтов. Создайте во вкладке «Аккаунты» и войдите по коду.",
                )
        await set_runtime_settings(db, body)
        await db.commit()

    # hot-reload outreach worker based on checkbox
    if body.outreach_enabled and outreach_service:
        await outreach_service.start()
    elif outreach_service:
        await outreach_service.stop()

    return {"ok": True, "outreach_running": bool(body.outreach_enabled and outreach_service)}


@router.get("/status", response_model=StatusResponse)
async def api_status():
    from app.config import get_settings

    cfg = get_settings()
    async with async_session_factory() as db:
        s = await get_runtime_settings(db)
        total = await db.execute(select(func.count(InviteTarget.id)))
        remaining = await db.execute(
            select(func.count(InviteTarget.id)).where(
                InviteTarget.is_invited.is_(False),
                InviteTarget.is_skipped.is_(False),
            )
        )
        outreach_pending = await db.execute(
            select(func.count(InviteTarget.id)).where(
                InviteTarget.is_invited.is_(True),
                InviteTarget.is_messaged.is_(False),
                InviteTarget.is_skipped.is_(False),
            )
        )
        queue_total = int(total.scalar() or 0)
        queue_remaining = int(remaining.scalar() or 0)
        outreach_pending_n = int(outreach_pending.scalar() or 0)

        inviter_names = [x.strip() for x in s.inviter_sessions if x.strip()]
        outreach_names = [x.strip() for x in s.outreach_sessions if x.strip()]

        inv_ready = 0
        if inviter_names:
            res = await db.execute(
                select(func.count(Account.id)).where(
                    Account.name.in_(inviter_names),
                    Account.role == "inviter",
                    Account.is_authorized.is_(True),
                    Account.is_active.is_(True),
                    Account.session_string.is_not(None),
                )
            )
            inv_ready = int(res.scalar() or 0)

        out_ready = 0
        if outreach_names:
            res = await db.execute(
                select(func.count(Account.id)).where(
                    Account.name.in_(outreach_names),
                    Account.role == "outreach",
                    Account.is_authorized.is_(True),
                    Account.is_active.is_(True),
                    Account.session_string.is_not(None),
                )
            )
            out_ready = int(res.scalar() or 0)

        authorized_names = (
            await db.execute(
                select(Account.name).where(
                    Account.is_authorized.is_(True),
                    Account.session_string.is_not(None),
                )
            )
        ).scalars().all()

    has_api = bool(cfg.tg_api_id) and bool(cfg.tg_api_hash) and not str(cfg.tg_api_hash).startswith("xxxx")

    blockers: list[str] = []
    if not s.chat_link.strip():
        blockers.append("Не указана ссылка на чат")
    if queue_remaining <= 0:
        blockers.append("База пустая — загрузите CSV/XLS/XLSX во вкладке «База»")
    if not has_api:
        blockers.append("Нет API: создайте файл .env с INV_TG_API_ID и INV_TG_API_HASH")
    if not inviter_names:
        blockers.append("Не указаны аккаунты-инвайтеры")
    elif inv_ready == 0:
        blockers.append("Инвайтеры не авторизованы — войдите по телефону+коду во вкладке «Аккаунты»")
    elif inv_ready < len(inviter_names):
        blockers.append(f"Авторизовано инвайтеров: {inv_ready}/{len(inviter_names)}")
    if s.daily_limit <= 0:
        blockers.append("Дневной лимит = 0")
    if s.outreach_enabled:
        if not outreach_names:
            blockers.append("Отписка включена, но нет outreach-аккаунтов")
        elif out_ready == 0:
            blockers.append("Outreach-аккаунты не авторизованы — войдите по коду")
        if not (s.outreach_message or "").strip():
            blockers.append("Пустой текст холодной отписки")

    configured = (
        bool(s.chat_link.strip())
        and len(inviter_names) >= 1
        and inv_ready >= 1
        and s.daily_limit > 0
        and has_api
    )
    running = bool(invite_service and invite_service.state.running)
    outreach_running = bool(outreach_service and outreach_service.state.running)
    last_tick_at = invite_service.state.last_tick_at if invite_service else None
    invited_today = invite_service.state.invited_today if invite_service else 0
    outreach_sent = outreach_service.state.sent_today if outreach_service else 0

    return StatusResponse(
        running=running,
        configured=configured,
        last_tick_at=last_tick_at,
        invited_today=invited_today,
        daily_limit=s.daily_limit,
        queue_total=queue_total,
        queue_remaining=queue_remaining,
        outreach_running=outreach_running,
        outreach_pending=outreach_pending_n,
        outreach_sent_today=outreach_sent,
        sessions_ready=inv_ready,
        sessions_expected=max(1, len(inviter_names)),
        outreach_ready=out_ready,
        outreach_expected=len(outreach_names),
        blockers=blockers,
        session_files=sorted(authorized_names),
        has_api_credentials=has_api,
    )


@router.post("/run/start")
async def api_start():
    if not invite_service:
        raise HTTPException(status_code=500, detail="Service not initialized")
    await invite_service.start()
    async with async_session_factory() as db:
        s = await get_runtime_settings(db)
    if s.outreach_enabled and outreach_service:
        await outreach_service.start()
    return {"running": True, "outreach": bool(s.outreach_enabled)}


@router.post("/run/stop")
async def api_stop():
    if not invite_service:
        raise HTTPException(status_code=500, detail="Service not initialized")
    await invite_service.stop()
    if outreach_service:
        await outreach_service.stop()
    return {"running": False}


@router.post("/outreach/start")
async def api_outreach_start():
    if not outreach_service:
        raise HTTPException(status_code=500, detail="Outreach not initialized")
    async with async_session_factory() as db:
        s = await get_runtime_settings(db)
        if not s.outreach_enabled:
            raise HTTPException(status_code=400, detail="Включите отписку в настройках")
        if not (s.outreach_message or "").strip():
            raise HTTPException(status_code=400, detail="Укажите текст отписки")
        if not [x for x in s.outreach_sessions if x.strip()]:
            raise HTTPException(status_code=400, detail="Укажите outreach-аккаунты")
    await outreach_service.start()
    return {"running": True}


@router.post("/outreach/stop")
async def api_outreach_stop():
    if not outreach_service:
        raise HTTPException(status_code=500, detail="Outreach not initialized")
    await outreach_service.stop()
    return {"running": False}


@router.get("/accounts", response_model=list[AccountItem])
async def api_list_accounts(role: Literal["inviter", "outreach"] | None = None):
    async with async_session_factory() as db:
        q = select(Account).order_by(Account.role.asc(), Account.name.asc())
        if role:
            q = q.where(Account.role == role)
        res = await db.execute(q)
        return [_account_item(a) for a in res.scalars().all()]


@router.post("/accounts", response_model=AccountItem)
async def api_create_account(body: AccountCreate):
    name = body.name.strip().replace(" ", "_")
    role = body.role.strip().lower()
    if role not in ("inviter", "outreach"):
        raise HTTPException(status_code=400, detail="role: inviter или outreach")
    if not name:
        raise HTTPException(status_code=400, detail="Укажите имя аккаунта")
    async with async_session_factory() as db:
        exists = (
            await db.execute(select(Account).where(Account.name == name))
        ).scalar_one_or_none()
        if exists:
            raise HTTPException(status_code=400, detail=f"Аккаунт '{name}' уже есть")
        acc = Account(name=name, role=role)
        db.add(acc)
        await db.commit()
        await db.refresh(acc)
        return _account_item(acc)


@router.delete("/accounts/{account_id}")
async def api_delete_account(account_id: int):
    async with async_session_factory() as db:
        acc = await db.get(Account, account_id)
        if not acc:
            raise HTTPException(status_code=404, detail="Не найден")
        if invite_service:
            await invite_service._pool.drop_client(acc.name)  # noqa: SLF001
        if outreach_service:
            await outreach_service._pool.drop_client(acc.name)  # noqa: SLF001
        await db.delete(acc)
        await db.commit()
    return {"ok": True}


@router.post("/accounts/{account_id}/auth/send-code")
async def api_send_code(account_id: int, body: AuthSendCode):
    async with async_session_factory() as db:
        try:
            result = await auth_service.send_code(db, account_id, body.phone)
            await db.commit()
            return result
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/auth/verify-code")
async def api_verify_code(account_id: int, body: AuthVerifyCode):
    async with async_session_factory() as db:
        try:
            result = await auth_service.verify_code(db, account_id, body.code)
            await db.commit()
            return result
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/auth/verify-password")
async def api_verify_password(account_id: int, body: AuthVerifyPassword):
    async with async_session_factory() as db:
        try:
            result = await auth_service.verify_password(db, account_id, body.password)
            await db.commit()
            return result
        except ValueError as exc:
            await db.rollback()
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            await db.rollback()
            raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/accounts/{account_id}/logout")
async def api_logout_account(account_id: int):
    async with async_session_factory() as db:
        acc = await db.get(Account, account_id)
        if not acc:
            raise HTTPException(status_code=404, detail="Не найден")
        if invite_service:
            await invite_service._pool.drop_client(acc.name)  # noqa: SLF001
        if outreach_service:
            await outreach_service._pool.drop_client(acc.name)  # noqa: SLF001
        acc.session_string = None
        acc.is_authorized = False
        acc.last_error = None
        acc.updated_at = datetime.utcnow()
        await db.commit()
    return {"ok": True}


@router.post("/targets/import", response_model=ImportResponse)
async def api_import_targets(file: UploadFile = File(...)):
    content = await file.read()
    name = (file.filename or "").lower()
    if name and not name.endswith((".csv", ".txt", ".xls", ".xlsx")):
        raise HTTPException(status_code=400, detail="Поддерживаются файлы: CSV, TXT, XLS, XLSX")
    try:
        async with async_session_factory() as db:
            res = await import_targets_file(db, content, filename=file.filename)
            await db.commit()
            return res
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать файл: {exc}") from exc


@router.get("/targets", response_model=list[TargetItem])
async def api_targets(limit: int = 200, only_pending: bool = False):
    limit = max(1, min(2000, int(limit)))
    async with async_session_factory() as db:
        q = select(InviteTarget).order_by(InviteTarget.id.desc()).limit(limit)
        if only_pending:
            q = q.where(
                InviteTarget.is_invited.is_(False),
                InviteTarget.is_skipped.is_(False),
            )
        res = await db.execute(q)
        rows = res.scalars().all()
        return [
            TargetItem(
                id=r.id,
                username=r.username,
                user_id=r.user_id,
                is_invited=r.is_invited,
                invited_at=r.invited_at,
                is_skipped=bool(getattr(r, "is_skipped", False)),
                is_messaged=bool(getattr(r, "is_messaged", False)),
                messaged_at=getattr(r, "messaged_at", None),
                outreach_error=getattr(r, "outreach_error", None),
                attempts=r.attempts,
                last_error=r.last_error,
                created_at=r.created_at,
            )
            for r in rows
        ]


@router.get("/logs", response_model=list[LogItem])
async def api_logs(limit: int = 200):
    limit = max(1, min(2000, int(limit)))
    async with async_session_factory() as db:
        res = await db.execute(select(InviteLog).order_by(InviteLog.id.desc()).limit(limit))
        rows = res.scalars().all()
        return [
            LogItem(
                id=r.id,
                created_at=r.created_at,
                inviter_session=r.inviter_session,
                target_label=r.target_label,
                status=r.status,
                error_text=r.error_text,
            )
            for r in rows
        ]


@router.post("/targets/reset")
async def api_reset_targets():
    async with async_session_factory() as db:
        res = await db.execute(select(InviteTarget))
        for t in res.scalars().all():
            t.is_invited = False
            t.invited_at = None
            t.is_skipped = False
            t.is_messaged = False
            t.messaged_at = None
            t.outreach_error = None
            t.last_error = None
            t.attempts = 0
        await db.commit()
    return {"ok": True, "reset_at": datetime.utcnow().isoformat()}


@router.post("/targets/{target_id}/skip")
async def api_skip_target(target_id: int):
    async with async_session_factory() as db:
        t = await db.get(InviteTarget, target_id)
        if not t:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        t.is_skipped = True
        if not t.last_error:
            t.last_error = "skipped_manual"
        await db.commit()
    return {"ok": True}


@router.delete("/targets/{target_id}")
async def api_delete_target(target_id: int):
    async with async_session_factory() as db:
        t = await db.get(InviteTarget, target_id)
        if not t:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        await db.delete(t)
        await db.commit()
    return {"ok": True}


@router.post("/targets/{target_id}/sync-inbox")
async def api_sync_target_inbox(target_id: int):
    """Отправить уже заинвайченного/отписанного пользователя в Operator Inbox."""
    async with async_session_factory() as db:
        t = await db.get(InviteTarget, target_id)
        if not t:
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        if not t.is_messaged:
            raise HTTPException(status_code=400, detail="Сначала нужна отписка (dm)")

        settings = await get_runtime_settings(db)
        outreach_names = [s.strip() for s in settings.outreach_sessions if s.strip()]
        session_name = outreach_names[0] if outreach_names else "outreach1"

        log = (
            await db.execute(
                select(InviteLog)
                .where(
                    InviteLog.target_label == (f"@{t.username}" if t.username else str(t.user_id)),
                    InviteLog.status == "outreach_ok",
                )
                .order_by(InviteLog.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if log:
            session_name = log.inviter_session

        if not t.user_id and not t.username:
            raise HTTPException(status_code=400, detail="Нет user_id/username")

        body = (settings.outreach_message or "").strip() or "—"
        ok = await sync_outreach_to_inbox(
            session_name=session_name,
            peer_telegram_user_id=int(t.user_id or 0),
            username=t.username,
            first_name=None,
            body=body,
            telegram_message_id=f"backfill-{target_id}",
            sent_at=(t.messaged_at or datetime.utcnow()).isoformat() + "Z",
        )
        if not ok:
            raise HTTPException(
                status_code=502,
                detail="Не удалось синхронизировать с inbox — проверьте INV_CONNECTOR_API_URL и INV_CONNECTOR_SYNC_SECRET",
            )
    return {"ok": True}


@router.post("/targets/reset-outreach")
async def api_reset_outreach():
    """Сбросить только статусы отписки (инвайты сохраняются)."""
    async with async_session_factory() as db:
        res = await db.execute(select(InviteTarget).where(InviteTarget.is_invited.is_(True)))
        for t in res.scalars().all():
            t.is_messaged = False
            t.messaged_at = None
            t.outreach_error = None
        await db.commit()
    return {"ok": True}


@router.get("/analytics/invited", response_model=InvitedActivityResponse)
async def api_invited_activity(
    sort: Literal["total", "messages", "reactions", "invited_at", "username", "last_active"] = "total",
    invited_only: bool = True,
):
    """Активность приглашённых в чате (сообщения/реакции из ShadowChat)."""
    async with async_session_factory() as db:
        return await get_invited_activity(db, sort=sort, invited_only=invited_only)


@router.post("/analytics/backfill")
async def api_activity_backfill():
    """Пересчитать активность из истории чата verdi114 в ShadowChat."""
    try:
        return await trigger_activity_backfill()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
