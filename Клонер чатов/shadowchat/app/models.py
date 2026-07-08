from datetime import datetime
from enum import Enum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class MirrorMode(str, Enum):
    SAFE = "safe"
    PROFILE_SYNC = "profile_sync"


class SessionType(str, Enum):
    BOT = "bot"
    USER = "user"


class BindingMode(str, Enum):
    PERMANENT = "permanent"
    FALLBACK = "fallback"


class DeleteMode(str, Enum):
    HARD_DELETE = "hard_delete"
    SOFT_DELETE = "soft_delete"


class SourceChat(Base):
    __tablename__ = "source_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    route_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mirror_chat_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mirror_chats.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mirror_chat: Mapped["MirrorChat | None"] = relationship("MirrorChat", back_populates="source_chats")


class MirrorChat(Base):
    __tablename__ = "mirror_chats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    mirror_username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), default=MirrorMode.SAFE.value, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    source_chats: Mapped[list["SourceChat"]] = relationship("SourceChat", back_populates="mirror_chat")


class Employee(Base):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    avatar_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consent_signed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped["SessionPool | None"] = relationship(
        "SessionPool", back_populates="assigned_employee", uselist=False
    )


class SessionPool(Base):
    __tablename__ = "session_pool"
    __table_args__ = (
        UniqueConstraint("assigned_employee_id", name="uq_session_assigned_employee"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    session_type: Mapped[str] = mapped_column(String(16), default=SessionType.USER.value, nullable=False)
    api_id: Mapped[int] = mapped_column(Integer, nullable=False)
    api_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    bot_token: Mapped[str | None] = mapped_column(String(128), nullable=True)
    assigned_employee_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("employees.id"), nullable=True, unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    binding_mode: Mapped[str] = mapped_column(
        String(16), default=BindingMode.PERMANENT.value, nullable=False
    )
    last_profile_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    session_string: Mapped[str | None] = mapped_column(Text, nullable=True)

    assigned_employee: Mapped["Employee | None"] = relationship(
        "Employee", back_populates="session"
    )


class MessageMap(Base):
    __tablename__ = "message_map"
    __table_args__ = (
        Index("ix_message_map_source", "source_chat_id", "source_message_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_chat_id: Mapped[int] = mapped_column(Integer, ForeignKey("source_chats.id"), nullable=False)
    source_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mirror_chat_id: Mapped[int] = mapped_column(Integer, ForeignKey("mirror_chats.id"), nullable=False)
    mirror_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_sender_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    session_pool_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("session_pool.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_chat_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mirror_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserActivity(Base):
    __tablename__ = "user_activity"
    __table_args__ = (
        UniqueConstraint("mirror_chat_id", "telegram_user_id", name="uq_activity_mirror_user"),
        Index("ix_user_activity_mirror", "mirror_chat_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    mirror_chat_id: Mapped[int] = mapped_column(Integer, ForeignKey("mirror_chats.id"), nullable=False)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str] = mapped_column(String(128), default="", nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AppSettings(Base):
    """Runtime settings stored in DB (overrides env defaults)."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
