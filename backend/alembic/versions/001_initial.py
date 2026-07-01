"""initial schema

Revision ID: 001
Revises:
Create Date: 2026-06-24
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "competitors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("region", sa.String(50)),
        sa.Column("brand_keywords", postgresql.ARRAY(sa.Text())),
        sa.Column("money_keywords", postgresql.ARRAY(sa.Text())),
        sa.Column("google_queries", postgresql.ARRAY(sa.Text())),
        sa.Column("yandex_queries", postgresql.ARRAY(sa.Text())),
        sa.Column("vk_domains", postgresql.ARRAY(sa.Text())),
        sa.Column("vk_owner_ids", postgresql.ARRAY(sa.Text())),
        sa.Column("telegram_channels", postgresql.ARRAY(sa.Text())),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("competitor_id", sa.Integer(), sa.ForeignKey("competitors.id")),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("result_type", sa.String(30), nullable=False),
        sa.Column("external_id", sa.Text()),
        sa.Column("title", sa.Text()),
        sa.Column("raw_text", sa.Text()),
        sa.Column("snippet", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("author_name", sa.Text()),
        sa.Column("channel_name", sa.Text()),
        sa.Column("position", sa.Integer()),
        sa.Column("views", sa.Integer()),
        sa.Column("likes", sa.Integer()),
        sa.Column("reposts", sa.Integer()),
        sa.Column("comments", sa.Integer()),
        sa.Column("published_at", sa.DateTime()),
        sa.Column("collected_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.Column("raw_json", postgresql.JSONB()),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("is_irrelevant", sa.Boolean(), server_default=sa.text("false")),
        sa.Column("search_vector", postgresql.TSVECTOR()),
    )
    op.create_index("ix_findings_source_external_id", "findings", ["source", "external_id"])
    op.create_index("ix_findings_content_hash", "findings", ["content_hash"])
    op.create_index(
        "ix_findings_search_vector",
        "findings",
        ["search_vector"],
        postgresql_using="gin",
    )
    op.create_table(
        "finding_analysis",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("finding_id", sa.BigInteger(), sa.ForeignKey("findings.id"), unique=True),
        sa.Column("entity_type", sa.String(30)),
        sa.Column("offer", sa.Text()),
        sa.Column("cta", sa.Text()),
        sa.Column("pain_points", postgresql.ARRAY(sa.Text())),
        sa.Column("tone", sa.String(50)),
        sa.Column("hooks", postgresql.ARRAY(sa.Text())),
        sa.Column("intent", sa.String(50)),
        sa.Column("sentiment", sa.String(20)),
        sa.Column("summary", sa.Text()),
        sa.Column("is_competitor_related", sa.Boolean()),
        sa.Column("model_used", sa.String(100)),
        sa.Column("analyzed_at", sa.DateTime(), server_default=sa.text("now()")),
    )
    op.create_table(
        "collector_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("collector_name", sa.String(50)),
        sa.Column("status", sa.String(20)),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
        sa.Column("items_collected", sa.Integer(), server_default=sa.text("0")),
        sa.Column("error_text", sa.Text()),
    )
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ai_base_url", sa.Text()),
        sa.Column("ai_api_key", sa.Text()),
        sa.Column("ai_model", sa.Text()),
        sa.Column("google_api_key", sa.Text()),
        sa.Column("google_cx", sa.Text()),
        sa.Column("yandex_api_key", sa.Text()),
        sa.Column("yandex_folder_id", sa.Text()),
        sa.Column("vk_access_token", sa.Text()),
        sa.Column("telegram_api_id", sa.Integer()),
        sa.Column("telegram_api_hash", sa.Text()),
        sa.Column("monitor_interval_hours", sa.Integer(), server_default=sa.text("6")),
        sa.Column("google_enabled", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("yandex_enabled", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("vk_enabled", sa.Boolean(), server_default=sa.text("true")),
        sa.Column("telegram_enabled", sa.Boolean(), server_default=sa.text("true")),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_table("collector_runs")
    op.drop_table("finding_analysis")
    op.drop_index("ix_findings_search_vector", table_name="findings")
    op.drop_index("ix_findings_content_hash", table_name="findings")
    op.drop_index("ix_findings_source_external_id", table_name="findings")
    op.drop_table("findings")
    op.drop_table("competitors")
