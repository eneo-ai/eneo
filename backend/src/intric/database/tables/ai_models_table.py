from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from intric.database.tables.base_class import BasePublic
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityClassificationsTable,
)
from intric.database.tables.tenant_table import Tenants


class CompletionModels(BasePublic):
    name: Mapped[str] = mapped_column()
    nickname: Mapped[str] = mapped_column()
    open_source: Mapped[Optional[bool]] = mapped_column()
    token_limit: Mapped[int] = mapped_column()
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
    __tablename__ = "completion_model_usage_stats"
    
    # Foreign keys
    model_id: Mapped[UUID] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="CASCADE"), 
        nullable=False,
        index=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"), 
        nullable=False,
        index=True
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
        DateTime(timezone=True), 
        server_default=func.now()
    )
    
    # Relationships
    completion_model: Mapped[CompletionModels] = relationship()
    tenant: Mapped["Tenants"] = relationship()
    
    __table_args__ = (
        UniqueConstraint('model_id', 'tenant_id', name='uq_model_tenant_stats'),
        Index('idx_usage_stats_model_tenant', 'model_id', 'tenant_id'),
        Index('idx_usage_stats_updated', 'last_updated'),
        Index('idx_usage_stats_total_usage', 'total_usage'),
    )
