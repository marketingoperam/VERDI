from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RuntimeSettings(BaseModel):
    chat_link: str = Field(default="", description="Ссылка на чат/канал (t.me/...)")
    min_delay_seconds: int = Field(default=45, ge=0, le=86400)
    daily_limit: int = Field(default=50, ge=0, le=100000)

    # legacy names kept for UI slots — account names from DB
    inviter_sessions: list[str] = Field(default_factory=list)
    outreach_sessions: list[str] = Field(default_factory=list)

    outreach_enabled: bool = Field(default=False)
    outreach_message: str = Field(
        default="Привет! Добавили вас в чат — напишите, если есть вопросы.",
        description="Текст холодной отписки после инвайта",
    )
    outreach_delay_seconds: int = Field(default=60, ge=0, le=86400)
    outreach_daily_limit: int = Field(
        default=20,
        ge=0,
        le=100000,
        description="Лимит отписок в день на один outreach-аккаунт",
    )


class StatusResponse(BaseModel):
    running: bool
    configured: bool
    last_tick_at: datetime | None = None
    invited_today: int
    daily_limit: int
    queue_total: int
    queue_remaining: int
    outreach_running: bool = False
    outreach_pending: int = 0
    outreach_sent_today: int = 0
    sessions_ready: int
    sessions_expected: int
    outreach_ready: int = 0
    outreach_expected: int = 0
    blockers: list[str] = Field(default_factory=list)
    session_files: list[str] = Field(default_factory=list)
    has_api_credentials: bool = False


class TargetItem(BaseModel):
    id: int
    username: str | None
    user_id: int | None
    is_invited: bool
    invited_at: datetime | None
    is_skipped: bool = False
    is_messaged: bool = False
    messaged_at: datetime | None = None
    outreach_error: str | None = None
    attempts: int
    last_error: str | None
    created_at: datetime


class ImportResponse(BaseModel):
    inserted: int
    skipped_duplicates: int
    errors: int


class LogItem(BaseModel):
    id: int
    created_at: datetime
    inviter_session: str
    target_label: str
    status: str
    error_text: str | None


class AccountItem(BaseModel):
    id: int
    name: str
    role: str
    phone: str | None = None
    username: str | None = None
    telegram_user_id: int | None = None
    is_authorized: bool
    is_active: bool
    last_error: str | None = None


class AccountCreate(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    role: str = Field(description="inviter | outreach")


class AuthSendCode(BaseModel):
    phone: str


class AuthVerifyCode(BaseModel):
    code: str


class AuthVerifyPassword(BaseModel):
    password: str
