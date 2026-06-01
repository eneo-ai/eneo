from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic
from intric.database.tables.model_providers_table import ModelProviders
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationsTable,
)
from intric.database.tables.tenant_table import Tenants


class CompletionModels(BasePublic):
    name: Mapped[str] = mapped_column()
    nickname: Mapped[str] = mapped_column()
    open_source: Mapped[Optional[bool]] = mapped_column()
    max_input_tokens: Mapped[int] = mapped_column()
    max_output_tokens: Mapped[int] = mapped_column()
    is_deprecated: Mapped[bool] = mapped_column(server_default="False")
    nr_billion_parameters: Mapped[Optional[int]] = mapped_column()
    hf_link: Mapped[Optional[str]] = mapped_column()

    family: Mapped[str] = mapped_column()
    stability: Mapped[str] = mapped_column()
    hosting: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    deployment_name: Mapped[Optional[str]] = mapped_column()
    org: Mapped[Optional[str]] = mapped_column()
    vision: Mapped[bool] = mapped_column(server_default="False")
    reasoning: Mapped[bool] = mapped_column(server_default="False")
    supports_tool_calling: Mapped[bool] = mapped_column(server_default="False")
    base_url: Mapped[Optional[str]] = mapped_column()
    litellm_model_name: Mapped[Optional[str]] = mapped_column()
    model_kwargs_capabilities: Mapped[Optional[dict[str, object]]] = mapped_column(
        JSONB, nullable=True
    )

    # Indicative USD ratecard. NULL = unknown / not applicable. Stored at high
    # precision because frontier-model prices live in the 1e-7 USD/token range.
    # Numeric(20, 12) = 8 integer digits → cap is < 10^8 USD/token. The frontend
    # admin form lets users enter cost per million tokens, so its input cap is
    # the same number * 10^6 (= MAX_COST_INPUT in
    # frontend/apps/web/src/routes/(app)/admin/models/AddWizard/models/draft.ts).
    # Keep the two in sync if either side changes.
    input_cost_per_token: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 12), nullable=True
    )
    output_cost_per_token: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 12), nullable=True
    )

    # Tenant model support: NULL = global model, NOT NULL = tenant-specific model
    tenant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=True, index=True
    )
    provider_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("model_providers.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Settings (previously in separate completion_model_settings table)
    is_enabled: Mapped[bool] = mapped_column(server_default="True")
    is_default: Mapped[bool] = mapped_column(server_default="False")
    security_classification_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(SecurityClassificationsTable.id, ondelete="SET NULL"), nullable=True
    )
    security_classification: Mapped[Optional["SecurityClassificationsTable"]] = (
        relationship(back_populates="completion_models")
    )
    provider: Mapped[Optional[ModelProviders]] = relationship()

    # Lifecycle: migration tracking and soft-delete
    migrated_to_model_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("completion_models.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    # Stored as TIMESTAMPTZ in Postgres; the column was created via TIMESTAMPTZ
    # but the SQLAlchemy mapping forgot `timezone=True`, which generated
    # `::TIMESTAMP WITHOUT TIME ZONE` casts on UPDATE and crashed asyncpg
    # whenever a tz-aware UTC datetime was assigned (the soft-delete path).
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        CheckConstraint(
            "(tenant_id IS NULL AND provider_id IS NULL) OR (tenant_id IS NOT NULL AND provider_id IS NOT NULL)",
            name="ck_completion_models_tenant_provider",
        ),
    )


class TranscriptionModels(BasePublic):
    name: Mapped[str] = mapped_column()
    model_name: Mapped[str] = mapped_column()
    open_source: Mapped[Optional[bool]] = mapped_column()
    is_deprecated: Mapped[bool] = mapped_column(server_default="False")
    hf_link: Mapped[Optional[str]] = mapped_column()
    family: Mapped[str] = mapped_column()
    stability: Mapped[str] = mapped_column()
    hosting: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    org: Mapped[Optional[str]] = mapped_column()
    base_url: Mapped[str] = mapped_column()

    # USD per minute of audio processed. NULL = unknown / self-hosted.
    # Numeric(20, 6) = 14 integer digits → cap is < 10^14 USD/minute, matching
    # MAX_COST_INPUT in the frontend admin form (see
    # frontend/apps/web/src/routes/(app)/admin/models/AddWizard/models/draft.ts).
    cost_per_minute: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 6), nullable=True
    )

    # Tenant model support: NULL = global model, NOT NULL = tenant-specific model
    tenant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=True, index=True
    )
    provider_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("model_providers.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Settings (previously in separate transcription_model_settings table)
    is_enabled: Mapped[bool] = mapped_column(server_default="True")
    is_default: Mapped[bool] = mapped_column(server_default="False")
    security_classification_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(SecurityClassificationsTable.id, ondelete="SET NULL"), nullable=True
    )
    security_classification: Mapped[Optional["SecurityClassificationsTable"]] = (
        relationship(back_populates="transcription_models")
    )

    __table_args__ = (
        CheckConstraint(
            "(tenant_id IS NULL AND provider_id IS NULL) OR (tenant_id IS NOT NULL AND provider_id IS NOT NULL)",
            name="ck_transcription_models_tenant_provider",
        ),
    )


class EmbeddingModels(BasePublic):
    name: Mapped[str] = mapped_column()
    nickname: Mapped[Optional[str]] = mapped_column()
    open_source: Mapped[bool] = mapped_column()
    dimensions: Mapped[Optional[int]] = mapped_column()
    max_input: Mapped[Optional[int]] = mapped_column()
    max_batch_size: Mapped[Optional[int]] = mapped_column()
    is_deprecated: Mapped[bool] = mapped_column(server_default="False")
    hf_link: Mapped[Optional[str]] = mapped_column()

    family: Mapped[str] = mapped_column()
    stability: Mapped[str] = mapped_column()
    hosting: Mapped[str] = mapped_column()
    description: Mapped[Optional[str]] = mapped_column()
    org: Mapped[Optional[str]] = mapped_column()
    litellm_model_name: Mapped[Optional[str]] = mapped_column()

    # Indicative USD ratecard. Output cost is almost always zero for embeddings
    # but kept for shape parity with completion models. Same Numeric(20, 12)
    # cap as completion models — see CompletionModels.input_cost_per_token.
    input_cost_per_token: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 12), nullable=True
    )
    output_cost_per_token: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(20, 12), nullable=True
    )

    # Tenant model support: NULL = global model, NOT NULL = tenant-specific model
    tenant_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=True, index=True
    )
    provider_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey("model_providers.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Settings (previously in separate embedding_model_settings table)
    is_enabled: Mapped[bool] = mapped_column(server_default="True")
    is_default: Mapped[bool] = mapped_column(server_default="False")
    security_classification_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(SecurityClassificationsTable.id, ondelete="SET NULL"), nullable=True
    )
    security_classification: Mapped[Optional["SecurityClassificationsTable"]] = (
        relationship(back_populates="embedding_models")
    )

    __table_args__ = (
        CheckConstraint(
            "(tenant_id IS NULL AND provider_id IS NULL) OR (tenant_id IS NOT NULL AND provider_id IS NOT NULL)",
            name="ck_embedding_models_tenant_provider",
        ),
    )


class CompletionModelUsageStats(BasePublic):
    """Pre-aggregated usage statistics for completion models per tenant."""

    __tablename__ = "completion_model_usage_stats"  # type: ignore[assignment]

    # Foreign keys
    model_id: Mapped[UUID] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), nullable=False, index=True
    )

    # Pre-calculated counts
    assistants_count: Mapped[int] = mapped_column(default=0)
    apps_count: Mapped[int] = mapped_column(default=0)
    services_count: Mapped[int] = mapped_column(default=0)
    questions_count: Mapped[int] = mapped_column(default=0)
    assistant_templates_count: Mapped[int] = mapped_column(default=0)
    app_templates_count: Mapped[int] = mapped_column(default=0)
    spaces_count: Mapped[int] = mapped_column(default=0)
    total_usage: Mapped[int] = mapped_column(default=0)

    # Metadata
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    completion_model: Mapped[CompletionModels] = relationship()
    tenant: Mapped["Tenants"] = relationship()

    __table_args__ = (
        UniqueConstraint("model_id", "tenant_id", name="uq_model_tenant_stats"),
        Index("idx_usage_stats_model_tenant", "model_id", "tenant_id"),
        Index("idx_usage_stats_updated", "last_updated"),
        Index("idx_usage_stats_total_usage", "total_usage"),
    )
