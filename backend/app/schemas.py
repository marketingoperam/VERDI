from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class CompetitorBase(BaseModel):
    name: str
    region: str | None = None
    brand_keywords: list[str] = Field(default_factory=list)
    money_keywords: list[str] = Field(default_factory=list)
    google_queries: list[str] = Field(default_factory=list)
    yandex_queries: list[str] = Field(default_factory=list)
    vk_domains: list[str] = Field(default_factory=list)
    vk_owner_ids: list[str] = Field(default_factory=list)
    telegram_channels: list[str] = Field(default_factory=list)
    is_active: bool = True


class CompetitorCreate(CompetitorBase):
    pass


class CompetitorUpdate(BaseModel):
    name: str | None = None
    region: str | None = None
    brand_keywords: list[str] | None = None
    money_keywords: list[str] | None = None
    google_queries: list[str] | None = None
    yandex_queries: list[str] | None = None
    vk_domains: list[str] | None = None
    vk_owner_ids: list[str] | None = None
    telegram_channels: list[str] | None = None
    is_active: bool | None = None


class CompetitorOut(CompetitorBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    entity_type: str | None = None
    offer: str | None = None
    cta: str | None = None
    pain_points: list[str] | None = None
    tone: str | None = None
    hooks: list[str] | None = None
    intent: str | None = None
    sentiment: str | None = None
    summary: str | None = None
    is_competitor_related: bool | None = None
    model_used: str | None = None
    analyzed_at: datetime | None = None


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    competitor_id: int | None
    competitor_name: str | None = None
    source: str
    result_type: str
    external_id: str | None
    title: str | None
    raw_text: str | None
    snippet: str | None
    url: str | None
    author_name: str | None
    channel_name: str | None
    position: int | None
    views: int | None
    likes: int | None
    reposts: int | None
    comments: int | None
    published_at: datetime | None
    collected_at: datetime
    is_irrelevant: bool
    analysis: AnalysisOut | None = None


class FindingFilters(BaseModel):
    source: str | None = None
    competitor_id: int | None = None
    result_type: str | None = None
    tone: str | None = None
    has_cta: bool | None = None
    keyword: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    q: str | None = None
    limit: int = 50
    offset: int = 0


class SettingsOut(BaseModel):
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    google_api_key: str | None = None
    google_cx: str | None = None
    yandex_api_key: str | None = None
    yandex_folder_id: str | None = None
    vk_access_token: str | None = None
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    monitor_interval_hours: int = 6
    google_enabled: bool = True
    yandex_enabled: bool = True
    vk_enabled: bool = True
    telegram_enabled: bool = True


class SettingsUpdate(BaseModel):
    ai_base_url: str | None = None
    ai_api_key: str | None = None
    ai_model: str | None = None
    google_api_key: str | None = None
    google_cx: str | None = None
    yandex_api_key: str | None = None
    yandex_folder_id: str | None = None
    vk_access_token: str | None = None
    telegram_api_id: int | None = None
    telegram_api_hash: str | None = None
    monitor_interval_hours: int | None = None
    google_enabled: bool | None = None
    yandex_enabled: bool | None = None
    vk_enabled: bool | None = None
    telegram_enabled: bool | None = None


class SearchRunResponse(BaseModel):
    task_id: str
    collector: str
    message: str


class AnalyticsSummary(BaseModel):
    total_24h: int
    google_24h: int
    yandex_24h: int
    vk_24h: int
    telegram_24h: int
    by_competitor: list[dict]


class AnalyticsTrends(BaseModel):
    daily: list[dict]


class AIAnalysisResult(BaseModel):
    entity_type: Literal["ad", "mention", "organic_result", "post"]
    offer: str | None = None
    cta: str | None = None
    pain_points: list[str] = Field(default_factory=list)
    tone: str | None = None
    hooks: list[str] = Field(default_factory=list)
    intent: str | None = None
    sentiment: str | None = None
    summary: str | None = None
    is_competitor_related: bool = False
