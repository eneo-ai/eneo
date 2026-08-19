from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from eneo.database.tables.ai_models_table import CompletionModels
from eneo.database.tables.service_principals_table import ServicePrincipals
from eneo.database.tables.token_usage_table import ProviderTokenUsages
from eneo.database.tables.users_table import Users


class ProviderTokenUsageTenantMismatchError(ValueError):
    pass


class ProviderTokenUsageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def record(
        self,
        *,
        tenant_id: UUID,
        principal_user_id: UUID | None,
        principal_service_id: UUID | None,
        completion_model_id: UUID,
        source_type: str,
        source_id: UUID,
        input_tokens: int | None,
        output_tokens: int | None,
        occurred_at: datetime,
    ) -> None:
        if (principal_user_id is None) == (principal_service_id is None):
            raise ValueError("Provider usage requires exactly one principal identity.")
        if input_tokens is not None and input_tokens < 0:
            raise ValueError("Provider input token usage cannot be negative.")
        if output_tokens is not None and output_tokens < 0:
            raise ValueError("Provider output token usage cannot be negative.")

        model_is_in_tenant = await self.session.scalar(
            sa.select(sa.literal(True)).where(
                CompletionModels.id == completion_model_id,
                CompletionModels.tenant_id == tenant_id,
            )
        )
        principal_table = Users if principal_user_id is not None else ServicePrincipals
        principal_id = principal_user_id or principal_service_id
        principal_is_in_tenant = await self.session.scalar(
            sa.select(sa.literal(True)).where(
                principal_table.id == principal_id,
                principal_table.tenant_id == tenant_id,
            )
        )
        if model_is_in_tenant is not True or principal_is_in_tenant is not True:
            raise ProviderTokenUsageTenantMismatchError(
                "Provider usage model and principal must belong to its tenant."
            )

        await self.session.execute(
            insert(ProviderTokenUsages)
            .values(
                tenant_id=tenant_id,
                principal_user_id=principal_user_id,
                principal_service_id=principal_service_id,
                completion_model_id=completion_model_id,
                source_type=source_type,
                source_id=source_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                occurred_at=occurred_at,
            )
            .on_conflict_do_nothing(
                constraint="uq_provider_token_usages_source",
            )
        )
