"""Forecast models catalog

The forecast model becomes a catalog model type, governed like the others
(enablement, security classification, display name) but created by Eneo:
``forecast_models`` holds one row per checkpoint a tool service runs, under a
``model_providers`` row of type ``eneo_tool_service`` that comes with the
deployment (no credentials or config: the URL and token stay in the
deployment's settings). ``mcp_servers.forecast_model_id`` is the model the
bundled Forecast source runs on, required on exactly those rows.

Existing Forecast sources are bound without asking the tool service: every
tenant with one gets the provider (unless it has one) and the ``default``
model, the checkpoint the deployment mounts today, enabled and unclassified.
Nothing else on the source changes; it keeps its own classification, which
wins over the model's.

The downgrade drops the column and the table, and removes the tool service
providers that no other model uses.

Revision ID: 202610221000
Revises: 202610201000
Create Date: 2026-10-21

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = "202610221000"
down_revision = "202610201000"
branch_labels = None
depends_on = None

PROVIDER_TYPE = "eneo_tool_service"
UNIQUE_INDEX = "uq_forecast_models_tenant_provider_name"
CONSTRAINT = "ck_mcp_servers_forecast_model"
FOREIGN_KEY = "fk_mcp_servers_forecast_model_id_forecast_models"
SOURCES = "http_auth_type = 'bundled' AND purpose = 'forecast'"


def upgrade() -> None:
    op.create_table(
        "forecast_models",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            primary_key=True,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("nickname", sa.String(), nullable=False),
        sa.Column("org", sa.String(), nullable=True),
        sa.Column("open_source", sa.Boolean(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "is_deprecated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "security_classification_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("deleted_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["model_providers.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["security_classification_id"],
            ["security_classifications.id"],
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_forecast_models_tenant_id", "forecast_models", ["tenant_id"])
    op.create_index(
        "ix_forecast_models_provider_id", "forecast_models", ["provider_id"]
    )
    op.create_index(
        UNIQUE_INDEX,
        "forecast_models",
        ["tenant_id", "provider_id", "name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.add_column(
        "mcp_servers",
        sa.Column("forecast_model_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        FOREIGN_KEY,
        "mcp_servers",
        "forecast_models",
        ["forecast_model_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_mcp_servers_forecast_model_id", "mcp_servers", ["forecast_model_id"]
    )

    # A tool service provider for every tenant with a Forecast source and none
    # yet. A tenant's own provider may hold the name already.
    op.execute(
        f"""
        INSERT INTO model_providers
            (tenant_id, name, provider_type, credentials, config, is_active)
        SELECT tenants.tenant_id,
               CASE
                 WHEN NOT EXISTS (
                   SELECT 1 FROM model_providers p
                   WHERE p.tenant_id = tenants.tenant_id
                     AND p.name = 'Eneo tool service')
                 THEN 'Eneo tool service'
                 WHEN NOT EXISTS (
                   SELECT 1 FROM model_providers p
                   WHERE p.tenant_id = tenants.tenant_id
                     AND p.name = 'Eneo tool service (built in)')
                 THEN 'Eneo tool service (built in)'
                 ELSE 'Eneo tool service (built in) '
                      || left(md5(random()::text), 8)
               END,
               '{PROVIDER_TYPE}', '{{}}'::jsonb, '{{}}'::jsonb, true
        FROM (SELECT DISTINCT tenant_id FROM mcp_servers WHERE {SOURCES}) tenants
        WHERE NOT EXISTS (
          SELECT 1 FROM model_providers p
          WHERE p.tenant_id = tenants.tenant_id
            AND p.provider_type = '{PROVIDER_TYPE}')
        """
    )
    # Its "default" model: the checkpoint the deployment runs today. Never
    # "the first checkpoint"; the tool service is not asked.
    op.execute(
        f"""
        INSERT INTO forecast_models
            (tenant_id, provider_id, name, nickname, org, open_source, is_enabled)
        SELECT DISTINCT ON (p.tenant_id)
               p.tenant_id, p.id, 'default', 'Timestral', 'Mistral AI', true, true
        FROM model_providers p
        WHERE p.provider_type = '{PROVIDER_TYPE}'
          AND p.tenant_id IN (SELECT tenant_id FROM mcp_servers WHERE {SOURCES})
        ORDER BY p.tenant_id, p.created_at, p.id
        """
    )
    op.execute(
        """
        UPDATE mcp_servers
        SET forecast_model_id = forecast_models.id
        FROM forecast_models
        WHERE forecast_models.tenant_id = mcp_servers.tenant_id
          AND mcp_servers.http_auth_type = 'bundled'
          AND mcp_servers.purpose = 'forecast'
        """
    )

    op.create_check_constraint(
        CONSTRAINT,
        "mcp_servers",
        f"({SOURCES}) = (forecast_model_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "mcp_servers", type_="check")
    op.drop_index("ix_mcp_servers_forecast_model_id", table_name="mcp_servers")
    op.drop_constraint(FOREIGN_KEY, "mcp_servers", type_="foreignkey")
    op.drop_column("mcp_servers", "forecast_model_id")

    op.drop_index(UNIQUE_INDEX, table_name="forecast_models")
    op.drop_index("ix_forecast_models_provider_id", table_name="forecast_models")
    op.drop_index("ix_forecast_models_tenant_id", table_name="forecast_models")
    op.drop_table("forecast_models")

    # Deleting a provider cascades to its models, so one that another model
    # type uses stays.
    op.execute(
        f"""
        DELETE FROM model_providers p
        WHERE p.provider_type = '{PROVIDER_TYPE}'
          AND NOT EXISTS (SELECT 1 FROM completion_models m WHERE m.provider_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM embedding_models m WHERE m.provider_id = p.id)
          AND NOT EXISTS (
            SELECT 1 FROM transcription_models m WHERE m.provider_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM image_models m WHERE m.provider_id = p.id)
          AND NOT EXISTS (SELECT 1 FROM rerank_models m WHERE m.provider_id = p.id)
        """
    )
