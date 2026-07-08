from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text(), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)


class Account(Base):
    """Аккаунт Telethon: StringSession в БД, вход по телефону+коду."""

    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("name", name="uq_accounts_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="inviter")  # inviter|outreach
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_string: Mapped[str | None] = mapped_column(Text(), nullable=True)
    is_authorized: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)


class InviteTarget(Base):
    __tablename__ = "invite_targets"
    __table_args__ = (
        UniqueConstraint("username", name="uq_invite_targets_username"),
        UniqueConstraint("user_id", name="uq_invite_targets_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_invited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    is_skipped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # cold outreach (отписка) — только outreach-аккаунтами, отдельно от инвайтеров
    is_messaged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    messaged_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    outreach_error: Mapped[str | None] = mapped_column(Text(), nullable=True)

    last_error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)


class InviteLog(Base):
    __tablename__ = "invite_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, default=datetime.utcnow)

    inviter_session: Mapped[str] = mapped_column(String(128), nullable=False)
    target_label: Mapped[str] = mapped_column(String(256), nullable=False)

    status: Mapped[str] = mapped_column(String(32), nullable=False)  # success|error|skipped|outreach_ok|outreach_err
    error_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
