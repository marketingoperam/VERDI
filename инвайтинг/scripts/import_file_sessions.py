import asyncio
from datetime import datetime

from sqlalchemy import select, update
from telethon import TelegramClient
from telethon.sessions import StringSession

from app.config import get_settings
from app.db import async_session_factory, engine
from app.models import Account, AppSetting, Base, InviteTarget

NAMES = ["inviter_01", "inviter_02", "inviter_03", "inviter_04", "inviter_05"]


async def convert_one(path_name: str):
    s = get_settings()
    file_client = TelegramClient(f"sessions/{path_name}", s.tg_api_id, s.tg_api_hash)
    await file_client.connect()
    if not await file_client.is_user_authorized():
        await file_client.disconnect()
        raise RuntimeError(f"{path_name} not authorized on file")
    me = await file_client.get_me()
    string = StringSession.save(file_client.session)
    await file_client.disconnect()
    return string, me


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    imported: list[str] = []
    async with async_session_factory() as db:
        for name in NAMES:
            string, me = await convert_one(name)
            res = await db.execute(select(Account).where(Account.name == name))
            acc = res.scalar_one_or_none()
            now = datetime.utcnow()
            if acc is None:
                acc = Account(name=name, role="inviter", created_at=now, updated_at=now)
                db.add(acc)
            acc.role = "inviter"
            acc.session_string = string
            acc.is_authorized = True
            acc.is_active = True
            acc.telegram_user_id = int(me.id) if me else None
            acc.username = getattr(me, "username", None)
            acc.phone = getattr(me, "phone", None)
            acc.last_error = None
            acc.updated_at = now
            imported.append(f"{name}: {me.id} @{getattr(me, 'username', None)}")

        row = await db.get(AppSetting, "inviter_sessions")
        val = ",".join(NAMES)
        if row is None:
            db.add(AppSetting(key="inviter_sessions", value=val, updated_at=datetime.utcnow()))
        else:
            row.value = val
            row.updated_at = datetime.utcnow()

        await db.execute(
            update(InviteTarget).values(
                is_invited=False,
                invited_at=None,
                last_error=None,
                attempts=0,
            )
        )
        await db.commit()

    print("IMPORTED:")
    for line in imported:
        print(line)


if __name__ == "__main__":
    asyncio.run(main())
