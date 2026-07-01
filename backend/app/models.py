from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Competitor(Base):
    __tablename__ = "competitors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    region: Mapped[str | None] = mapped_column(String(50))
    brand_keywords: Mapped[list | None] = mapped_column(JSON)
    money_keywords: Mapped[list | None] = mapped_column(JSON)
    google_queries: Mapped[list | None] = mapped_column(JSON)
    yandex_queries: Mapped[list | None] = mapped_column(JSON)
    vk_domains: Mapped[list | None] = mapped_column(JSON)
    vk_owner_ids: Mapped[list | None] = mapped_column(JSON)
    telegram_channels: Mapped[list | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    findings: Mapped[list["Finding"]] = relationship(back_populates="competitor")


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    competitor_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("competitors.id"))
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    result_type: Mapped[str] = mapped_column(String(30), nullable=False)
    external_id: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    raw_text: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    author_name: Mapped[str | None] = mapped_column(Text)
    channel_name: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)
    views: Mapped[int | None] = mapped_column(Integer)
    likes: Mapped[int | None] = mapped_column(Integer)
    reposts: Mapped[int | None] = mapped_column(Integer)
    comments: Mapped[int | None] = mapped_column(Integer)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    collected_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    is_irrelevant: Mapped[bool] = mapped_column(Boolean, default=False)

    competitor: Mapped["Competitor | None"] = relationship(back_populates="findings")
    analysis: Mapped["FindingAnalysis | None"] = relationship(
        back_populates="finding", uselist=False
    )

    __table_args__ = (
        Index("ix_findings_source_external_id", "source", "external_id"),
        Index("ix_findings_content_hash", "content_hash"),
    )


class FindingAnalysis(Base):
    __tablename__ = "finding_analysis"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(Integer, ForeignKey("findings.id"), unique=True)
    entity_type: Mapped[str | None] = mapped_column(String(30))
    offer: Mapped[str | None] = mapped_column(Text)
    cta: Mapped[str | None] = mapped_column(Text)
    pain_points: Mapped[list | None] = mapped_column(JSON)
    tone: Mapped[str | None] = mapped_column(String(50))
    hooks: Mapped[list | None] = mapped_column(JSON)
    intent: Mapped[str | None] = mapped_column(String(50))
    sentiment: Mapped[str | None] = mapped_column(String(20))
    summary: Mapped[str | None] = mapped_column(Text)
    is_competitor_related: Mapped[bool | None] = mapped_column(Boolean)
    model_used: Mapped[str | None] = mapped_column(Text)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    finding: Mapped["Finding"] = relationship(back_populates="analysis")


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collector_name: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str | None] = mapped_column(String(20))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    items_collected: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(Text)


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    ai_base_url: Mapped[str | None] = mapped_column(Text)
    ai_api_key: Mapped[str | None] = mapped_column(Text)
    ai_model: Mapped[str | None] = mapped_column(Text)
    google_api_key: Mapped[str | None] = mapped_column(Text)
    google_cx: Mapped[str | None] = mapped_column(Text)
    yandex_api_key: Mapped[str | None] = mapped_column(Text)
    yandex_folder_id: Mapped[str | None] = mapped_column(Text)
    vk_access_token: Mapped[str | None] = mapped_column(Text)
    telegram_api_id: Mapped[int | None] = mapped_column(Integer)
    telegram_api_hash: Mapped[str | None] = mapped_column(Text)
    monitor_interval_hours: Mapped[int] = mapped_column(Integer, default=6)
    google_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    yandex_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    vk_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    telegram_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
