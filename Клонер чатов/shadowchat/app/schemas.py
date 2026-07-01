from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceChatCreate(BaseModel):
    telegram_chat_id: int
    title: str = ""
    is_active: bool = True
    mirror_chat_id: int | None = None


class SourceChatUpdate(BaseModel):
    title: str | None = None
    is_active: bool | None = None
    mirror_chat_id: int | None = None


class SourceChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_chat_id: int
    title: str
    is_active: bool
    mirror_chat_id: int | None
    created_at: datetime


class MirrorChatCreate(BaseModel):
    telegram_chat_id: int
    title: str = ""
    is_active: bool = True
    mode: Literal["safe", "profile_sync"] = "safe"


class MirrorChatUpdate(BaseModel):
    title: str | None = None
    is_active: bool | None = None
    mode: Literal["safe", "profile_sync"] | None = None


class MirrorChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_chat_id: int
    title: str
    is_active: bool
    mode: str
    created_at: datetime


class EmployeeCreate(BaseModel):
    telegram_user_id: int
    first_name: str = ""
    last_name: str | None = None
    username: str | None = None
    is_active: bool = True
    consent_signed: bool = False
    is_muted: bool = False


class EmployeeUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    is_active: bool | None = None
    consent_signed: bool | None = None
    is_muted: bool | None = None


class EmployeeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    telegram_user_id: int
    first_name: str
    last_name: str | None
    username: str | None
    avatar_hash: str | None
    is_active: bool
    consent_signed: bool
    is_muted: bool
    updated_at: datetime


class SessionCreate(BaseModel):
    session_name: str
    is_active: bool = True


class SessionUpdate(BaseModel):
    assigned_employee_id: int | None = None
    is_active: bool | None = None
    is_fallback: bool | None = None
    binding_mode: Literal["permanent", "fallback"] | None = None
    unassign_employee: bool = False


class SessionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_name: str
    session_type: str
    api_id: int
    assigned_employee_id: int | None
    is_active: bool
    is_fallback: bool
    binding_mode: str
    last_profile_sync_at: datetime | None
    last_used_at: datetime | None


class SyncLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_type: str
    source_chat_id: int | None
    source_message_id: int | None
    mirror_message_id: int | None
    status: str
    error_text: str | None
    created_at: datetime


class SettingsResponse(BaseModel):
    profile_sync_enabled: bool
    profile_sync_interval_hours: int
    delete_mode: str
    ignore_bots: bool
    ignore_service_messages: bool
    max_media_size_mb: int
    message_filter_mode: str
    min_message_length: int


class SettingsUpdate(BaseModel):
    profile_sync_enabled: bool | None = None
    profile_sync_interval_hours: int | None = None
    delete_mode: Literal["hard_delete", "soft_delete"] | None = None
    ignore_bots: bool | None = None
    ignore_service_messages: bool | None = None
    max_media_size_mb: int | None = None
    message_filter_mode: Literal["all", "text_only", "min_length"] | None = None
    min_message_length: int | None = Field(None, ge=0)


class HealthResponse(BaseModel):
    status: str
    database: str
    redis: str
    listener: str


class ChatPairCreate(BaseModel):
    title: str
    source_telegram_chat_id: int
    mirror_telegram_chat_id: int
    mode: Literal["safe", "profile_sync"] = "safe"
    is_active: bool = True


class ChatPairResponse(BaseModel):
    source_id: int
    source_telegram_chat_id: int
    source_title: str
    source_is_active: bool
    mirror_id: int
    mirror_telegram_chat_id: int
    mirror_title: str
    mirror_mode: str
    mirror_is_active: bool
    created_at: datetime


class SetupStep(BaseModel):
    id: str
    title: str
    description: str
    done: bool
    action: str | None = None


class SetupStatusResponse(BaseModel):
    ready: bool
    progress_percent: int
    steps: list[SetupStep]


class DashboardStats(BaseModel):
    source_chats: int
    mirror_chats: int
    active_pairs: int
    employees: int
    sessions: int
    sessions_assigned: int
    messages_mirrored_today: int
    errors_today: int


class SessionDetailResponse(SessionResponse):
    employee_name: str | None = None
    employee_telegram_id: int | None = None
    is_authorized: bool = False


class SessionAuthSendCodeRequest(BaseModel):
    phone: str
    api_id: int | None = None
    api_hash: str | None = None


class SessionAuthCodeRequest(BaseModel):
    code: str


class SessionAuthPasswordRequest(BaseModel):
    password: str


class SessionAuthStatusResponse(BaseModel):
    status: str
    phone: str | None = None
    first_name: str | None = None
    username: str | None = None
    telegram_user_id: int | None = None
    api_id: int | None = None
    api_hash: str | None = None
    qr_url: str | None = None


class SessionImportStringRequest(BaseModel):
    session_name: str
    session_string: str
    api_id: int | None = None
    api_hash: str | None = None


class SessionImportResponse(BaseModel):
    session_id: int
    session_name: str
    status: str
    telegram_user_id: int | None = None
    first_name: str | None = None
    username: str | None = None
    phone: str | None = None
    verify_warning: str | None = None


class DashboardResponse(BaseModel):
    stats: DashboardStats
    setup: SetupStatusResponse
    health: HealthResponse
    recent_logs: list[SyncLogResponse]
