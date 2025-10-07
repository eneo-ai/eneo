from typing import Any, Optional
from uuid import UUID

import sqlalchemy as sa
from pydantic import HttpUrl
from sqlalchemy import cast, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from intric.database.repositories.base import BaseRepositoryDelegate
from intric.database.tables.module_table import Modules
from intric.database.tables.tenant_table import Tenants
from intric.main import exceptions
from intric.main.models import ModelId
from intric.tenants.tenant import TenantBase, TenantInDB, TenantUpdate


class TenantRepository:
    def __init__(self, session: AsyncSession):
        self.delegate = BaseRepositoryDelegate(
            session,
            Tenants,
            TenantInDB,
            with_options=[selectinload(Tenants.modules)],
        )
        self.session = session

    async def add(self, tenant: TenantBase) -> TenantInDB:
        try:
            return await self.delegate.add(tenant)
        except IntegrityError as e:
            raise exceptions.UniqueException("Tenant name already exists.") from e

    async def get(self, id: UUID) -> TenantInDB:
        return await self.delegate.get(id)

    async def get_all_tenants(self, domain: str | None = None):
        if domain is not None:
            return await self.delegate.filter_by(conditions={Tenants.domain: domain})

        return await self.delegate.get_all()

    async def add_modules(self, list_of_module_ids: list[ModelId], tenant_id: UUID):
        module_ids = [module.id for module in list_of_module_ids]
        module_stmt = sa.select(Modules).filter(Modules.id.in_(module_ids))
        modules = await self.session.scalars(module_stmt)

        tenant_stmt = (
            sa.select(Tenants)
            .where(Tenants.id == tenant_id)
            .options(selectinload(Tenants.modules))
        )
        tenant = await self.session.scalar(tenant_stmt)

        tenant.modules = modules.all()

        return TenantInDB.model_validate(tenant)

    async def update_tenant(self, tenant: TenantUpdate) -> TenantInDB:
        return await self.delegate.update(tenant)

    async def delete_tenant_by_id(self, id: UUID) -> TenantInDB:
        return await self.delegate.delete(id)

    async def set_privacy_policy(
        self, privacy_policy: Optional[HttpUrl], tenant_id: UUID
    ) -> TenantInDB:
        privacy_policy = str(privacy_policy) if privacy_policy is not None else None
        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(privacy_policy=privacy_policy)
            .returning(Tenants)
            .options(selectinload(Tenants.modules))
        )

        return await self.delegate.get_model_from_query(stmt)

    async def get_tenant_from_zitadel_org_id(self, zitadel_org_id: str) -> TenantInDB:
        return await self.delegate.get_by(
            conditions={Tenants.zitadel_org_id: zitadel_org_id}
        )

    async def update_api_credential(
        self,
        tenant_id: UUID,
        provider: str,
        credential: dict[str, Any],
    ) -> TenantInDB:
        """Update or add API credential using JSONB set operation.

        Uses PostgreSQL's jsonb_set function to efficiently update a single
        provider's credentials without loading/modifying/saving the entire JSONB object.

        Args:
            tenant_id: The UUID of the tenant
            provider: The provider name (e.g., "openai", "azure", "anthropic")
            credential: The credential dictionary containing api_key and optional fields

        Returns:
            Updated TenantInDB instance with refreshed api_credentials
        """
        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                api_credentials=func.jsonb_set(
                    Tenants.api_credentials,
                    [provider.lower()],
                    cast(credential, JSONB),
                    True,  # create_if_missing
                )
            )
            .returning(Tenants)
            .options(selectinload(Tenants.modules))
        )
        return await self.delegate.get_model_from_query(stmt)

    async def delete_api_credential(
        self,
        tenant_id: UUID,
        provider: str,
    ) -> TenantInDB:
        """Remove API credential using JSONB delete operator.

        Uses PostgreSQL's JSONB #- operator to efficiently remove a single
        provider's credentials from the JSONB object.

        Args:
            tenant_id: The UUID of the tenant
            provider: The provider name to remove (e.g., "openai", "azure")

        Returns:
            Updated TenantInDB instance with refreshed api_credentials
        """
        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                api_credentials=Tenants.api_credentials.op("#-")(
                    cast([provider.lower()], postgresql.ARRAY(sa.Text))
                )
            )
            .returning(Tenants)
            .options(selectinload(Tenants.modules))
        )
        return await self.delegate.get_model_from_query(stmt)

    async def get_api_credentials_masked(
        self,
        tenant_id: UUID,
    ) -> dict[str, str]:
        """Get credentials with masked keys (last 4 chars only).

        Retrieves all API credentials for a tenant and masks the api_key values
        to show only the last 4 characters. Safe for displaying in UI.

        Args:
            tenant_id: The UUID of the tenant

        Returns:
            Dictionary of provider -> masked key (e.g., {"openai": "...xyz1"})
            Empty dict if no credentials exist
        """
        stmt = sa.select(Tenants.api_credentials).where(Tenants.id == tenant_id)
        result = await self.session.execute(stmt)
        credentials = result.scalar_one()

        if not credentials:
            return {}

        masked = {}
        for provider, cred in credentials.items():
            # Handle both dict format and legacy string format
            if isinstance(cred, dict):
                api_key = cred.get("api_key", "")
            else:
                api_key = str(cred)

            # Mask the key - show last 4 chars or "***" for short keys
            if len(api_key) > 4:
                masked[provider] = f"...{api_key[-4:]}"
            else:
                masked[provider] = "***"

        return masked
