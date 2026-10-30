from datetime import datetime
from typing import Optional
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.base_class import BasePublic
from eneo.database.tables.service_principals_table import ServicePrincipals
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.users_table import Users


class ProviderTokenUsages(BasePublic):
    """One idempotent platform usage row per completed provider request."""

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey(Tenants.id, ondelete="CASCADE"),
        nullable=False,
    )
    principal_user_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(Users.id, ondelete="RESTRICT"),
    )
    principal_service_id: Mapped[Optional[UUID]] = mapped_column(
        ForeignKey(ServicePrincipals.id, ondelete="RESTRICT"),
    )
    completion_model_id: Mapped[UUID] = mapped_column(
        ForeignKey(CompletionModels.id, ondelete="RESTRICT"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    source_id: Mapped[UUID] = mapped_column(nullable=False)
    input_tokens: Mapped[Optional[int]] = mapped_column()
    output_tokens: Mapped[Optional[int]] = mapped_column()
    occurred_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_id",
            name="uq_provider_token_usages_source",
        ),
        CheckConstraint(
            "length(source_type) > 0",
            name="ck_provider_token_usages_source_type_nonempty",
        ),
        CheckConstraint(
            "input_tokens IS NULL OR input_tokens >= 0",
            name="ck_provider_token_usages_input_nonnegative",
        ),
        CheckConstraint(
            "output_tokens IS NULL OR output_tokens >= 0",
            name="ck_provider_token_usages_output_nonnegative",
        ),
        CheckConstraint(
            "num_nonnulls(principal_user_id, principal_service_id) = 1",
            name="ck_provider_token_usages_principal_identity",
        ),
        Index(
            "ix_provider_token_usages_tenant_occurred",
            "tenant_id",
            "occurred_at",
        ),
        Index(
            "ix_provider_token_usages_completion_model_id",
            "completion_model_id",
        ),
    )
