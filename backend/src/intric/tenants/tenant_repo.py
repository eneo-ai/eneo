from typing import TYPE_CHECKING, Any, Optional
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
from intric.main.logging import get_logger
from intric.main.models import ModelId
from intric.tenants.tenant import TenantBase, TenantInDB, TenantUpdate

if TYPE_CHECKING:
    from intric.settings.encryption_service import EncryptionService

logger = get_logger(__name__)


class TenantRepository:
    def __init__(
        self,
        session: AsyncSession,
        encryption_service: Optional["EncryptionService"] = None,
    ):
        self.delegate = BaseRepositoryDelegate(
            session,
            Tenants,
            TenantInDB,
            with_options=[selectinload(Tenants.modules)],
        )
        self.session = session
        self.encryption = encryption_service

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
        """Update or add API credential using JSONB set operation with encryption.

        Uses PostgreSQL's jsonb_set function to efficiently update a single
        provider's credentials without loading/modifying/saving the entire JSONB object.
        Encrypts the api_key field if encryption is active.

        Args:
            tenant_id: The UUID of the tenant
            provider: The provider name (e.g., "openai", "azure", "anthropic")
            credential: The credential dictionary containing api_key and optional fields

        Returns:
            Updated TenantInDB instance with refreshed api_credentials
        """
        # DEBUG: Log encryption state
        logger.info(
            f"DEBUG update_api_credential: encryption_service={self.encryption}, "
            f"is_active={self.encryption.is_active() if self.encryption else 'N/A'}, "
            f"has_api_key={'api_key' in credential}",
            extra={"tenant_id": str(tenant_id), "provider": provider},
        )

        # Encrypt api_key if encryption is active
        credential_to_store = credential.copy()  # Don't mutate the input
        if (
            self.encryption
            and self.encryption.is_active()
            and "api_key" in credential_to_store
        ):
            original_key = credential_to_store["api_key"]
            credential_to_store["api_key"] = self.encryption.encrypt(original_key)
            logger.info(
                f"Encrypted credential for provider {provider}",
                extra={"tenant_id": str(tenant_id), "provider": provider},
            )

        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                api_credentials=func.jsonb_set(
                    Tenants.api_credentials,
                    [provider.lower()],
                    cast(credential_to_store, JSONB),
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

        Retrieves all API credentials for a tenant, decrypts if needed, and masks
        the api_key values to show only the last 4 characters. Safe for displaying in UI.

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

            # Decrypt if needed BEFORE masking
            if self.encryption and api_key:
                try:
                    api_key = self.encryption.decrypt(api_key)
                except ValueError:
                    # If decryption fails, mask the encrypted value
                    # This handles legacy plaintext credentials gracefully
                    pass

            # Mask the key - show last 4 chars or "***" for short keys
            if len(api_key) > 4:
                masked[provider] = f"...{api_key[-4:]}"
            else:
                masked[provider] = "***"

        return masked

    async def get_api_credentials_with_metadata(
        self,
        tenant_id: UUID,
    ) -> dict[str, dict[str, str]]:
        """Get credentials with masked keys AND encryption status.

        Retrieves all API credentials for a tenant, detects encryption status,
        decrypts if needed, and masks the api_key values. Provides metadata
        about encryption state for security auditing.

        Args:
            tenant_id: The UUID of the tenant

        Returns:
            Dictionary of provider -> {"masked_key": "...xyz9", "encryption_status": "encrypted"}
            Empty dict if no credentials exist

        Example:
            {
                "openai": {
                    "masked_key": "...xyz9",
                    "encryption_status": "encrypted"
                },
                "azure": {
                    "masked_key": "...abc1",
                    "encryption_status": "plaintext"
                }
            }
        """
        stmt = sa.select(Tenants.api_credentials).where(Tenants.id == tenant_id)
        result = await self.session.execute(stmt)
        credentials = result.scalar_one()

        if not credentials:
            return {}

        metadata = {}
        for provider, cred in credentials.items():
            # Extract api_key from credential structure
            if isinstance(cred, dict):
                api_key = cred.get("api_key", "")
            else:
                api_key = str(cred)

            # Determine encryption status BEFORE decryption
            # Check for Fernet encryption prefix (enc:fernet:v1:...)
            if api_key.startswith("enc:fernet:v"):
                encryption_status = "encrypted"
            elif api_key and not api_key.startswith("enc:"):
                encryption_status = "plaintext"
            else:
                encryption_status = "plaintext"  # Fallback for empty or unknown format

            # Decrypt if needed
            if self.encryption and api_key:
                try:
                    api_key = self.encryption.decrypt(api_key)
                except ValueError:
                    # If decryption fails, keep the encrypted value for masking
                    # This handles legacy plaintext credentials gracefully
                    pass

            # Mask the key - show last 4 chars or "***" for short keys
            if len(api_key) > 4:
                masked_key = f"...{api_key[-4:]}"
            else:
                masked_key = "***"

            metadata[provider] = {
                "masked_key": masked_key,
                "encryption_status": encryption_status,
            }

        return metadata
