"""add embedding usage and cost snapshots to crawl runs

Revision ID: 202605181000
Revises: 202605170900
Create Date: 2026-05-18 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "202605181000"
down_revision: Union[str, None] = "202605170900"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CRAWL_RUNS_TENANT_CREATED_AT_INDEX = "idx_crawl_runs_tenant_created_at"
CRAWL_RUNS_TENANT_WEBSITE_CREATED_AT_INDEX = (
    "idx_crawl_runs_tenant_website_created_at"
)
CRAWL_RUNS_EMBEDDING_USAGE_SOURCE_CHECK = (
    "ck_crawl_runs_embedding_usage_source"
)


def upgrade() -> None:
    op.add_column(
        "embedding_models",
        sa.Column(
            "input_cost_per_token",
            sa.Numeric(20, 12),
            nullable=True,
            comment="USD input cost per token for provider-reported usage",
        ),
    )
    op.add_column(
        "embedding_models",
        sa.Column(
            "output_cost_per_token",
            sa.Numeric(20, 12),
            nullable=True,
            comment="USD output cost per token; unused by embeddings but kept rate-card compatible",
        ),
    )
    op.add_column(
        "crawl_runs",
        sa.Column(
            "embedding_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("embedding_models.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("embedding_model_name_snapshot", sa.Text(), nullable=True),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("embedding_model_litellm_name_snapshot", sa.Text(), nullable=True),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("embedding_model_provider_snapshot", sa.Text(), nullable=True),
    )
    op.add_column(
        "crawl_runs",
        sa.Column(
            "embedding_input_cost_per_token_snapshot",
            sa.Numeric(20, 12),
            nullable=True,
        ),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("embedding_input_tokens", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("embedding_usage_source", sa.Text(), nullable=True),
    )
    op.add_column(
        "crawl_runs",
        sa.Column("embedding_total_cost_usd", sa.Numeric(20, 12), nullable=True),
    )
    op.create_check_constraint(
        CRAWL_RUNS_EMBEDDING_USAGE_SOURCE_CHECK,
        "crawl_runs",
        "embedding_usage_source IS NULL OR embedding_usage_source IN ('provider_reported', 'missing')",
    )

    with op.get_context().autocommit_block():
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {CRAWL_RUNS_TENANT_CREATED_AT_INDEX}
            ON crawl_runs (tenant_id, created_at)
            """
        )
        op.execute(
            f"""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS {CRAWL_RUNS_TENANT_WEBSITE_CREATED_AT_INDEX}
            ON crawl_runs (tenant_id, website_id, created_at)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS {CRAWL_RUNS_TENANT_WEBSITE_CREATED_AT_INDEX}"
        )
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS {CRAWL_RUNS_TENANT_CREATED_AT_INDEX}"
        )

    op.drop_constraint(
        CRAWL_RUNS_EMBEDDING_USAGE_SOURCE_CHECK,
        "crawl_runs",
        type_="check",
    )
    op.drop_column("crawl_runs", "embedding_total_cost_usd")
    op.drop_column("crawl_runs", "embedding_usage_source")
    op.drop_column("crawl_runs", "embedding_input_tokens")
    op.drop_column("crawl_runs", "embedding_input_cost_per_token_snapshot")
    op.drop_column("crawl_runs", "embedding_model_provider_snapshot")
    op.drop_column("crawl_runs", "embedding_model_litellm_name_snapshot")
    op.drop_column("crawl_runs", "embedding_model_name_snapshot")
    op.drop_column("crawl_runs", "embedding_model_id")
    op.drop_column("embedding_models", "output_cost_per_token")
    op.drop_column("embedding_models", "input_cost_per_token")
