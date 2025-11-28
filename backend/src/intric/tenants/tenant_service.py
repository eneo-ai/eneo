from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from intric.main.exceptions import NotFoundException
from intric.main.models import ModelId
from intric.tenants.crawler_settings_helper import get_all_crawler_settings
from intric.tenants.masking import mask_api_key
from intric.tenants.provider_field_config import validate_provider_credentials
from intric.tenants.tenant import (
    TenantBase,
    TenantInDB,
    TenantUpdate,
    TenantUpdatePublic,
)
from intric.tenants.tenant_repo import TenantRepository

if TYPE_CHECKING:
    from intric.ai_models.completion_models.completion_models_repo import (
        CompletionModelsRepository,
    )
    from intric.ai_models.embedding_models.embedding_models_repo import (
        AdminEmbeddingModelsService,
    )
    from intric.transcription_models.infrastructure import (
        TranscriptionModelEnableService,
    )


class TenantService:
    def __init__(
        self,
        repo: TenantRepository,
        completion_model_repo: "CompletionModelsRepository",
        embedding_model_repo: "AdminEmbeddingModelsService",
        transcription_model_enable_service: "TranscriptionModelEnableService",
    ):
        self.repo = repo
        self.completion_model_repo = completion_model_repo
        self.embedding_model_repo = embedding_model_repo
        self.transcription_models_enable_service = transcription_model_enable_service

    @staticmethod
    def _validate(tenant: TenantInDB | None, id: UUID):
        if not tenant:
            raise NotFoundException(f"Tenant {id} not found")

    async def get_all_tenants(self, domain: str | None) -> list[TenantInDB]:
        return await self.repo.get_all_tenants(domain=domain)

    async def get_tenant_by_id(self, id: UUID) -> TenantInDB:
        tenant = await self.repo.get(id)
        self._validate(tenant, id)

        return tenant

    async def create_tenant(self, tenant: TenantBase) -> TenantInDB:
        tenant_in_db = await self.repo.add(tenant)

        # Note: Models are now managed via API/UI by admins
        # New tenants start with no pre-enabled models

        return tenant_in_db

    async def delete_tenant(self, tenant_id: UUID) -> TenantInDB:
        tenant = await self.get_tenant_by_id(tenant_id)
        self._validate(tenant, tenant_id)

        return await self.repo.delete_tenant_by_id(tenant_id)

    async def update_tenant(self, tenant_update: TenantUpdatePublic, id: UUID) -> TenantInDB:
        tenant = await self.get_tenant_by_id(id)
        self._validate(tenant, id)

        tenant_update = TenantUpdate(**tenant_update.model_dump(exclude_unset=True), id=tenant.id)
        return await self.repo.update_tenant(tenant_update)

    async def add_modules(self, list_of_module_ids: list[ModelId], tenant_id: UUID):
        return await self.repo.add_modules(list_of_module_ids, tenant_id)

    async def set_credential(
        self,
        tenant_id: UUID,
        provider: str,
        api_key: str,
        endpoint: str | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        strict_mode: bool = True,
    ) -> dict[str, Any]:
        """
        Set or update tenant API credentials for a specific provider.

        Args:
            tenant_id: UUID of the tenant
            provider: LLM provider name
            api_key: API key for the provider
            endpoint: Optional endpoint (required for some providers)
            api_version: Optional API version (required for some providers)
            deployment_name: Optional deployment name (required for some providers)
            strict_mode: Whether tenant_credentials_enabled (strict mode)

        Returns:
            Dict containing:
                - tenant_id: UUID
                - provider: str
                - masked_key: str
                - set_at: datetime

        Raises:
            NotFoundException: If tenant not found
            ValueError: If validation fails
        """
        # Validate tenant exists
        tenant = await self.repo.get(tenant_id)
        self._validate(tenant, tenant_id)

        # Create a simple validation object
        class CredentialData:
            def __init__(self, api_key, endpoint, api_version, deployment_name):
                self.api_key = api_key
                self.endpoint = endpoint
                self.api_version = api_version
                self.deployment_name = deployment_name

        credential_data = CredentialData(api_key, endpoint, api_version, deployment_name)

        # Validate provider-specific fields
        validation_errors = validate_provider_credentials(
            provider, credential_data, strict_mode
        )

        if validation_errors:
            raise ValueError(
                f"Credential validation failed for provider '{provider}': "
                + "; ".join(validation_errors)
            )

        # Build credential dict
        credential: dict[str, Any] = {"api_key": api_key}

        if endpoint:
            credential["endpoint"] = endpoint
        if api_version:
            credential["api_version"] = api_version
        if deployment_name:
            credential["deployment_name"] = deployment_name

        # Update credential and retrieve latest tenant snapshot
        updated_tenant = await self.repo.update_api_credential(
            tenant_id=tenant_id,
            provider=provider,
            credential=credential,
        )

        # Extract timestamp from stored credential
        provider_key = provider.lower()
        stored_credential = (
            updated_tenant.api_credentials.get(provider_key, {})
            if updated_tenant and updated_tenant.api_credentials
            else {}
        )

        timestamp_raw = (
            stored_credential.get("set_at")
            if isinstance(stored_credential, dict)
            else None
        )

        try:
            set_at = (
                datetime.fromisoformat(timestamp_raw)
                if timestamp_raw
                else datetime.now(timezone.utc)
            )
            if set_at.tzinfo is None:
                set_at = set_at.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            set_at = datetime.now(timezone.utc)

        masked_key = mask_api_key(api_key)

        return {
            "tenant_id": tenant_id,
            "provider": provider,
            "masked_key": masked_key,
            "set_at": set_at,
        }

    async def delete_credential(
        self,
        tenant_id: UUID,
        provider: str,
    ) -> dict[str, Any]:
        """
        Delete tenant API credentials for a specific provider.

        Args:
            tenant_id: UUID of the tenant
            provider: LLM provider name

        Returns:
            Dict containing:
                - tenant_id: UUID
                - provider: str

        Raises:
            NotFoundException: If tenant not found
        """
        # Validate tenant exists
        tenant = await self.repo.get(tenant_id)
        self._validate(tenant, tenant_id)

        # Delete credential
        await self.repo.delete_api_credential(tenant_id=tenant_id, provider=provider)

        return {
            "tenant_id": tenant_id,
            "provider": provider,
        }

    async def list_credentials(
        self,
        tenant_id: UUID,
    ) -> list[dict[str, Any]]:
        """
        List all configured API credentials for a tenant.

        Returns masked keys, encryption status, and provider-specific configuration
        (without sensitive data).

        Args:
            tenant_id: UUID of the tenant

        Returns:
            List of credential info dicts containing:
                - provider: str
                - masked_key: str
                - configured_at: datetime
                - encryption_status: str ("encrypted" or "plaintext")
                - config: dict (provider-specific fields excluding sensitive data)

        Raises:
            NotFoundException: If tenant not found
        """
        # Validate tenant exists
        tenant = await self.repo.get(tenant_id)
        self._validate(tenant, tenant_id)

        # Get credentials with metadata (masked keys + encryption status)
        credentials_metadata = await self.repo.get_api_credentials_with_metadata(
            tenant_id
        )

        # Build credential info list
        credentials: list[dict[str, Any]] = []
        tenant_credentials = tenant.api_credentials or {}

        for provider, metadata in credentials_metadata.items():
            credential_data = tenant_credentials.get(provider, {})
            config: dict[str, Any] = {}
            configured_at: datetime = tenant.updated_at

            if isinstance(credential_data, dict):
                # Extract config (all fields except sensitive ones)
                config = {
                    k: v
                    for k, v in credential_data.items()
                    if k not in {"api_key", "encrypted_at", "set_at"}
                }

                # Extract timestamp
                timestamp_candidate = metadata.get("set_at") or credential_data.get("set_at")
                if not timestamp_candidate:
                    timestamp_candidate = credential_data.get("encrypted_at")

                if isinstance(timestamp_candidate, str):
                    try:
                        configured_at = datetime.fromisoformat(timestamp_candidate)
                    except ValueError:
                        configured_at = tenant.updated_at

            credentials.append({
                "provider": provider,
                "masked_key": metadata["masked_key"],
                "configured_at": configured_at,
                "encryption_status": metadata["encryption_status"],
                "config": config,
            })

        return credentials

    async def update_crawler_settings(
        self,
        tenant_id: UUID,
        settings: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Update crawler settings for a tenant (partial update).

        Uses atomic JSONB merge at DB level to prevent race conditions.

        Args:
            tenant_id: UUID of the tenant
            settings: Settings to update (only provided keys are changed)

        Returns:
            Dict containing:
                - tenant_id: UUID
                - settings: dict (merged with defaults)
                - overrides: list[str] (keys that have tenant-specific values)
                - updated_at: datetime

        Raises:
            NotFoundException: If tenant not found
        """
        # Validate tenant exists
        tenant = await self.repo.get(tenant_id)
        self._validate(tenant, tenant_id)

        # Early return if no settings provided
        if not settings:
            return await self.get_crawler_settings(tenant_id)

        # Atomic merge at DB level (prevents race conditions)
        updated_tenant = await self.repo.update_crawler_settings(
            tenant_id=tenant_id,
            crawler_settings=settings,
        )

        # Build response with defaults filled in using the helper
        effective_settings = get_all_crawler_settings(updated_tenant.crawler_settings)

        return {
            "tenant_id": tenant_id,
            "settings": effective_settings,
            "overrides": list(updated_tenant.crawler_settings.keys()),
            "updated_at": updated_tenant.updated_at,
        }

    async def get_crawler_settings(
        self,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        """
        Get effective crawler settings for a tenant.

        Returns merged view: tenant overrides + environment defaults.

        Args:
            tenant_id: UUID of the tenant

        Returns:
            Dict containing:
                - tenant_id: UUID
                - settings: dict (effective settings)
                - overrides: list[str] (keys with tenant-specific values)
                - updated_at: datetime | None

        Raises:
            NotFoundException: If tenant not found
        """
        # Validate tenant exists
        tenant = await self.repo.get(tenant_id)
        self._validate(tenant, tenant_id)

        # Get tenant overrides
        overrides = tenant.crawler_settings or {}

        # Use helper to merge with env defaults (single source of truth)
        effective_settings = get_all_crawler_settings(overrides)

        return {
            "tenant_id": tenant_id,
            "settings": effective_settings,
            "overrides": list(overrides.keys()),
            "updated_at": tenant.updated_at if overrides else None,
        }

    async def delete_crawler_settings(
        self,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        """
        Delete all tenant crawler settings, reverting to defaults.

        Args:
            tenant_id: UUID of the tenant

        Returns:
            Dict containing:
                - tenant_id: UUID
                - deleted_keys: list[str] (keys that were removed)

        Raises:
            NotFoundException: If tenant not found
        """
        # Validate tenant exists
        tenant = await self.repo.get(tenant_id)
        self._validate(tenant, tenant_id)

        # Get keys before deletion
        deleted_keys = list((tenant.crawler_settings or {}).keys())

        # Clear settings using dedicated method
        await self.repo.clear_crawler_settings(tenant_id=tenant_id)

        return {
            "tenant_id": tenant_id,
            "deleted_keys": deleted_keys,
        }
