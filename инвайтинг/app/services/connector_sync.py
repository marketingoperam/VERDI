"""Синхронизация холодной отписки с VERDI Operator Inbox."""

from __future__ import annotations

import structlog
import httpx

from app.config import get_settings

logger = structlog.get_logger()


async def sync_outreach_to_inbox(
    *,
    session_name: str,
    peer_telegram_user_id: int,
    username: str | None,
    first_name: str | None,
    body: str,
    telegram_message_id: str | int,
    sent_at: str,
) -> bool:
    settings = get_settings()
    base = (settings.connector_api_url or "").strip().rstrip("/")
    secret = (settings.connector_sync_secret or "").strip()
    if not base or not secret:
        logger.debug("connector_sync_skipped", reason="not_configured")
        return False

    payload = {
        "sessionName": session_name,
        "peerTelegramUserId": str(peer_telegram_user_id),
        "externalChatId": str(peer_telegram_user_id),
        "username": username,
        "firstName": first_name,
        "body": body,
        "telegramMessageId": str(telegram_message_id),
        "sentAt": sent_at,
    }
    headers = {"X-Invite-Sync-Secret": secret, "Content-Type": "application/json"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.post(
                f"{base}/api/integrations/inviting/outreach",
                json=payload,
                headers=headers,
            )
        if res.status_code >= 400:
            logger.warning(
                "connector_sync_failed",
                status=res.status_code,
                body=res.text[:300],
                session=session_name,
                peer=peer_telegram_user_id,
            )
            return False
        data = res.json()
        logger.info(
            "connector_sync_ok",
            session=session_name,
            peer=peer_telegram_user_id,
            conversation_id=data.get("conversationId"),
            imported=data.get("imported"),
        )
        return True
    except Exception as exc:
        logger.warning("connector_sync_error", error=str(exc), session=session_name)
        return False
