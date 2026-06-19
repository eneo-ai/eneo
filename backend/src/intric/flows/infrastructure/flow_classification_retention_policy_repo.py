from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from intric.database.tables.flow_classification_retention_policy_table import (
    FlowClassificationRetentionPolicies,
)
from intric.database.tables.security_classifications_table import SecurityClassification
from intric.flows.domain.flow_classification_retention_policy import (
    FlowClassificationRetentionPolicy,
)


def _to_domain(
    record: FlowClassificationRetentionPolicies,
) -> FlowClassificationRetentionPolicy:
    return FlowClassificationRetentionPolicy(
        tenant_id=record.tenant_id,
        security_classification_id=record.security_classification_id,
        data_retention_days=record.data_retention_days,
    )


class FlowClassificationRetentionPolicyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_for_tenant(
        self, *, tenant_id: UUID
    ) -> list[FlowClassificationRetentionPolicy]:
        stmt = (
            sa.select(FlowClassificationRetentionPolicies)
            .join(
                SecurityClassification,
                sa.and_(
                    SecurityClassification.id
                    == FlowClassificationRetentionPolicies.security_classification_id,
                    SecurityClassification.tenant_id
                    == FlowClassificationRetentionPolicies.tenant_id,
                ),
            )
            .where(FlowClassificationRetentionPolicies.tenant_id == tenant_id)
            .order_by(
                SecurityClassification.security_level,
                FlowClassificationRetentionPolicies.security_classification_id,
            )
        )
        result = await self.session.scalars(stmt)
        return [_to_domain(record) for record in result.all()]

    async def get(
        self, *, tenant_id: UUID, security_classification_id: UUID
    ) -> FlowClassificationRetentionPolicy | None:
        record = await self.session.get(
            FlowClassificationRetentionPolicies,
            {
                "tenant_id": tenant_id,
                "security_classification_id": security_classification_id,
            },
        )
        if record is None:
            return None
        return _to_domain(record)

    async def security_classification_exists(
        self, *, tenant_id: UUID, security_classification_id: UUID
    ) -> bool:
        stmt = sa.select(SecurityClassification.id).where(
            SecurityClassification.id == security_classification_id,
            SecurityClassification.tenant_id == tenant_id,
        )
        return await self.session.scalar(stmt) is not None

    async def upsert(
        self, policy: FlowClassificationRetentionPolicy
    ) -> FlowClassificationRetentionPolicy:
        stmt = (
            insert(FlowClassificationRetentionPolicies)
            .values(
                tenant_id=policy.tenant_id,
                security_classification_id=policy.security_classification_id,
                data_retention_days=policy.data_retention_days,
            )
            .on_conflict_do_update(
                index_elements=["tenant_id", "security_classification_id"],
                set_={
                    "data_retention_days": policy.data_retention_days,
                    "updated_at": sa.func.now(),
                },
            )
            .returning(FlowClassificationRetentionPolicies)
        )
        record = (await self.session.scalars(stmt)).one()
        return _to_domain(record)

    async def delete(
        self, *, tenant_id: UUID, security_classification_id: UUID
    ) -> bool:
        stmt = (
            sa.delete(FlowClassificationRetentionPolicies)
            .where(
                FlowClassificationRetentionPolicies.tenant_id == tenant_id,
                FlowClassificationRetentionPolicies.security_classification_id
                == security_classification_id,
            )
            .returning(FlowClassificationRetentionPolicies.security_classification_id)
        )
        deleted_id = await self.session.scalar(stmt)
        return deleted_id is not None
