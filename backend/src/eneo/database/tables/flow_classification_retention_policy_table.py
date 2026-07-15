from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, PrimaryKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from eneo.data_retention.constants import MAX_RETENTION_DAYS, MIN_RETENTION_DAYS
from eneo.database.tables.base_class import BaseCrossReference

FLOW_CLASSIFICATION_RETENTION_POLICY_DAYS_RANGE_CHECK = (
    "data_retention_days IS NULL OR "
    f"(data_retention_days >= {MIN_RETENTION_DAYS} "
    f"AND data_retention_days <= {MAX_RETENTION_DAYS})"
)
FLOW_CLASSIFICATION_MINIMUM_RETENTION_DAYS_RANGE_CHECK = (
    "minimum_retention_days IS NULL OR "
    f"(minimum_retention_days >= {MIN_RETENTION_DAYS} "
    f"AND minimum_retention_days <= {MAX_RETENTION_DAYS})"
)
FLOW_CLASSIFICATION_RETENTION_POLICY_HAS_VALUE_CHECK = (
    "data_retention_days IS NOT NULL OR minimum_retention_days IS NOT NULL OR no_purge"
)


class FlowClassificationRetentionPolicies(BaseCrossReference):
    """Stores classification-scoped Flow retention windows. Writer: FlowClassificationRetentionPolicyRepository. Purpose: tighten Flow run-history purge horizons by tenant security classification."""

    tenant_id: Mapped[UUID] = mapped_column(nullable=False)
    security_classification_id: Mapped[UUID] = mapped_column(nullable=False)
    data_retention_days: Mapped[int | None] = mapped_column(nullable=True)
    minimum_retention_days: Mapped[int | None] = mapped_column(nullable=True)
    no_purge: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default=sa.false(),
    )

    __table_args__ = (
        PrimaryKeyConstraint(
            "tenant_id",
            "security_classification_id",
            name="pk_flow_classification_retention_policies",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
            name="fk_flow_classification_retention_policies_tenant",
        ),
        ForeignKeyConstraint(
            ["security_classification_id", "tenant_id"],
            ["security_classifications.id", "security_classifications.tenant_id"],
            ondelete="CASCADE",
            name="fk_flow_classification_retention_policies_classification_tenant",
        ),
        CheckConstraint(
            FLOW_CLASSIFICATION_RETENTION_POLICY_DAYS_RANGE_CHECK,
            name="ck_flow_classification_retention_policy_days_range",
        ),
        CheckConstraint(
            FLOW_CLASSIFICATION_MINIMUM_RETENTION_DAYS_RANGE_CHECK,
            name="ck_flow_classification_retention_policy_minimum_days_range",
        ),
        CheckConstraint(
            FLOW_CLASSIFICATION_RETENTION_POLICY_HAS_VALUE_CHECK,
            name="ck_flow_classification_retention_policy_has_value",
        ),
    )
