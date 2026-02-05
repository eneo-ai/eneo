from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import HttpUrl
from sqlalchemy import cast as sa_cast, func
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
from intric.tenants.masking import mask_api_key
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
        """Create new tenant with auto-generated slug.

        If the tenant doesn't have a slug, it will be auto-generated from the name.
        This ensures all new tenants have slugs for federation routing.
        """
        try:
            # Add tenant first to get ID
            tenant_in_db = await self.delegate.add(tenant)

            # Auto-generate slug if not provided
            if not tenant_in_db.slug:
                logger.info(
                    f"Auto-generating slug for tenant {tenant_in_db.name}",
                    extra={"tenant_id": str(tenant_in_db.id)},
                )
                slug = await self.generate_slug_for_tenant(tenant_in_db.id)

                # Update tenant with generated slug
                stmt = (
                    sa.update(Tenants)
                    .where(Tenants.id == tenant_in_db.id)
                    .values(slug=slug, updated_at=datetime.now(timezone.utc))
                    .returning(Tenants)
                    .options(selectinload(Tenants.modules))
                )
                tenant_in_db = await self.delegate.get_model_from_query(stmt)
                logger.info(
                    f"Generated slug '{slug}' for tenant {tenant_in_db.name}",
                    extra={"tenant_id": str(tenant_in_db.id), "slug": slug},
                )

            return tenant_in_db
        except IntegrityError as e:
            raise exceptions.UniqueException("Tenant name already exists.") from e

    async def get(self, id: UUID) -> TenantInDB:
        return cast(TenantInDB, await self.delegate.get(id))

    async def get_all_tenants(self, domain: str | None = None) -> list[TenantInDB]:
        if domain is not None:
            return cast(
                list[TenantInDB],
                await self.delegate.filter_by(conditions={Tenants.domain: domain}),
            )

        return cast(list[TenantInDB], await self.delegate.get_all())

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
        if tenant is None:
            raise exceptions.NotFoundException("Tenant not found.")

        tenant.modules = list(modules.all())

        return TenantInDB.model_validate(tenant)

    async def update_tenant(self, tenant: TenantUpdate) -> TenantInDB:
        return cast(TenantInDB, await self.delegate.update(tenant))

    async def update_api_key_policy(
        self,
        tenant_id: UUID,
        policy_updates: dict[str, Any],
    ) -> TenantInDB:
        tenant = await self.get(tenant_id)
        policy = dict(tenant.api_key_policy or {})
        policy.update(policy_updates)

        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(api_key_policy=policy, updated_at=datetime.now(timezone.utc))
            .returning(Tenants)
            .options(selectinload(Tenants.modules))
        )
        model = await self.delegate.get_model_from_query(stmt)
        return cast(TenantInDB, model)

    async def delete_tenant_by_id(self, id: UUID) -> TenantInDB:
        return cast(TenantInDB, await self.delegate.delete(id))

    async def set_privacy_policy(
        self, privacy_policy: Optional[HttpUrl], tenant_id: UUID
    ) -> TenantInDB:
        privacy_policy_value = (
            str(privacy_policy) if privacy_policy is not None else None
        )
        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(privacy_policy=privacy_policy_value)
            .returning(Tenants)
            .options(selectinload(Tenants.modules))
        )

        model = await self.delegate.get_model_from_query(stmt)
        return cast(TenantInDB, model)

    async def get_tenant_from_zitadel_org_id(self, zitadel_org_id: str) -> TenantInDB:
        return cast(
            TenantInDB,
            await self.delegate.get_by(
                conditions={Tenants.zitadel_org_id: zitadel_org_id}
            ),
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
        set_at = datetime.now(timezone.utc).isoformat()
        credential_to_store["set_at"] = set_at
        if (
            self.encryption
            and self.encryption.is_active()
            and "api_key" in credential_to_store
        ):
            original_key = credential_to_store["api_key"]
            credential_to_store["api_key"] = self.encryption.encrypt(original_key)
            credential_to_store["encrypted_at"] = datetime.now(timezone.utc).isoformat()
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
                    sa_cast(credential_to_store, JSONB),
                    True,  # create_if_missing
                )
            )
            .returning(Tenants)
            .options(selectinload(Tenants.modules))
        )
        model = await self.delegate.get_model_from_query(stmt)
        return cast(TenantInDB, model)

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
                    sa_cast([provider.lower()], postgresql.ARRAY(sa.Text))
                )
            )
            .returning(Tenants)
            .options(selectinload(Tenants.modules))
        )
        model = await self.delegate.get_model_from_query(stmt)
        return cast(TenantInDB, model)

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
                except ValueError as e:
                    logger.warning(
                        f"Failed to decrypt credential for provider {provider} during masking",
                        extra={
                            "tenant_id": str(tenant_id),
                            "provider": provider,
                            "error": str(e),
                        },
                    )
                    # Continue with masking the encrypted value
                    # This handles legacy plaintext credentials gracefully

            # Mask the key - show last 4 chars or "***" for short keys
            masked[provider] = mask_api_key(api_key)

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
            masked_key = mask_api_key(api_key)

            metadata[provider] = {
                "masked_key": masked_key,
                "encryption_status": encryption_status,
                "set_at": cred.get("set_at") if isinstance(cred, dict) else None,
            }

        return metadata

    async def get_by_slug(self, slug: str) -> Optional[TenantInDB]:
        """Get tenant by slug (for URL-based routing).

        Args:
            slug: The URL-safe slug identifier

        Returns:
            TenantInDB if found, None otherwise
        """
        stmt = (
            sa.select(Tenants)
            .where(Tenants.slug == slug)
            .options(selectinload(Tenants.modules))
        )
        result = await self.session.execute(stmt)
        tenant = result.scalar_one_or_none()

        if tenant:
            return TenantInDB.model_validate(tenant)
        return None

    async def generate_slug_for_tenant(self, tenant_id: UUID) -> str:
        """Generate URL-safe slug from tenant name.

        This method:
        1. Converts tenant name to lowercase
        2. Removes special characters
        3. Replaces spaces with hyphens
        4. Ensures uniqueness by appending counter if needed
        5. Validates against slug rules (max 63 chars, no leading/trailing hyphens)

        Args:
            tenant_id: UUID of the tenant

        Returns:
            str: Generated unique slug

        Raises:
            ValueError: If tenant not found
        """
        import re

        tenant = await self.get(tenant_id)
        if not tenant:
            raise ValueError(f"Tenant {tenant_id} not found")

        # Convert to lowercase, remove special chars, replace spaces
        slug = tenant.name.lower()
        slug = re.sub(r"[^a-z0-9\s-]", "", slug)  # Remove special chars
        slug = re.sub(r"\s+", "-", slug)  # Replace spaces with hyphens
        slug = re.sub(r"-+", "-", slug)  # Collapse multiple hyphens
        slug = slug.strip("-")  # Remove leading/trailing hyphens

        # Ensure uniqueness (leave room for suffix)
        base_slug = slug[:60]  # Leave room for counter suffix
        counter = 0
        while True:
            check_slug = f"{base_slug}-{counter}" if counter > 0 else base_slug
            existing = await self.get_by_slug(check_slug)
            if not existing or existing.id == tenant_id:
                # Update tenant with generated slug
                stmt = (
                    sa.update(Tenants)
                    .where(Tenants.id == tenant_id)
                    .values(slug=check_slug, updated_at=datetime.now(timezone.utc))
                )
                await self.session.execute(stmt)
                logger.info(
                    f"Generated and saved slug '{check_slug}' for tenant {tenant.name}"
                )
                return check_slug
            counter += 1

    async def update_federation_config(
        self,
        tenant_id: UUID,
        federation_config: dict[str, Any],
    ) -> None:
        """Set or update federation config for tenant.

        IMPORTANT: client_secret must be encrypted BEFORE calling this method.

        Args:
            tenant_id: The UUID of the tenant
            federation_config: Complete federation configuration dict with encrypted client_secret
        """
        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                federation_config=federation_config,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def delete_federation_config(self, tenant_id: UUID) -> None:
        """Remove federation config for tenant.

        Args:
            tenant_id: The UUID of the tenant
        """
        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                federation_config={},
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self.session.execute(stmt)
        await self.session.commit()

    async def get_federation_config_with_metadata(
        self, tenant_id: UUID
    ) -> Optional[dict[str, Any]]:
        """Get federation config with metadata (for admin API responses).

        Returns configuration with masked client_secret for safe display in UI.

        Args:
            tenant_id: The UUID of the tenant

        Returns:
            dict with keys:
            - provider: str
            - client_id: str (unmasked)
            - masked_secret: str (last 4 chars)
            - issuer: str
            - allowed_domains: list[str]
            - encrypted_at: str (ISO timestamp)
            - encryption_status: "encrypted" | "plaintext"

            None if tenant has no federation config
        """
        stmt = sa.select(Tenants.federation_config).where(Tenants.id == tenant_id)
        result = await self.session.execute(stmt)
        config = result.scalar_one()

        if not config:
            return None

        # Mask client_secret
        client_secret = config.get("client_secret", "")
        if len(client_secret) > 4:
            masked_secret = f"...{client_secret[-4:]}"
        else:
            masked_secret = "***"

        # Detect encryption status
        # Check for Fernet encryption prefix (enc:fernet:v1:...)
        if client_secret.startswith("enc:fernet:v"):
            encryption_status = "encrypted"
        elif client_secret and not client_secret.startswith("enc:"):
            encryption_status = "plaintext"
        else:
            encryption_status = "plaintext"  # Fallback for empty or unknown format

        return {
            "provider": config.get("provider"),
            "client_id": config.get("client_id"),
            "masked_secret": masked_secret,
            "issuer": config.get("issuer"),
            "allowed_domains": config.get("allowed_domains", []),
            "encrypted_at": config.get("encrypted_at"),
            "encryption_status": encryption_status,
        }

    async def get_all_active(self) -> list[TenantInDB]:
        """Get all active tenants for tenant selector.

        Returns:
            List of active TenantInDB instances
        """
        from intric.tenants.tenant import TenantState

        stmt = (
            sa.select(Tenants)
            .where(Tenants.state == TenantState.ACTIVE.value)
            .options(selectinload(Tenants.modules))
        )
        result = await self.session.execute(stmt)
        tenants = result.scalars().all()

        return [TenantInDB.model_validate(tenant) for tenant in tenants]

    async def update_crawler_settings(
        self,
        tenant_id: UUID,
        crawler_settings: dict[str, Any],
    ) -> TenantInDB:
        """Atomically merge crawler settings for a tenant.

        Uses PostgreSQL's || operator to merge JSONB objects atomically,
        preventing lost-update race conditions when concurrent updates occur.
        Only provided keys are updated; existing keys are preserved.

        Args:
            tenant_id: The UUID of the tenant
            crawler_settings: Partial crawler settings dict to merge

        Returns:
            Updated TenantInDB instance
        """
        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                crawler_settings=func.coalesce(
                    Tenants.crawler_settings, sa_cast({}, JSONB)
                ).op("||")(sa_cast(crawler_settings, JSONB)),
                updated_at=datetime.now(timezone.utc),
            )
            .returning(Tenants)
            .options(selectinload(Tenants.modules))
        )
        model = await self.delegate.get_model_from_query(stmt)
        return cast(TenantInDB, model)

    async def clear_crawler_settings(
        self,
        tenant_id: UUID,
    ) -> TenantInDB:
        """Clear all crawler settings for a tenant, reverting to defaults.

        Args:
            tenant_id: The UUID of the tenant

        Returns:
            Updated TenantInDB instance
        """
        stmt = (
            sa.update(Tenants)
            .where(Tenants.id == tenant_id)
            .values(
                crawler_settings={},
                updated_at=datetime.now(timezone.utc),
            )
            .returning(Tenants)
            .options(selectinload(Tenants.modules))
        )
        model = await self.delegate.get_model_from_query(stmt)
        return cast(TenantInDB, model)
