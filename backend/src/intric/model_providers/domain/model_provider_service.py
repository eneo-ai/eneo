from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID, uuid4

from intric.main.exceptions import NameCollisionException
from intric.model_providers.domain.model_provider import ModelProvider
from intric.model_providers.infrastructure.model_provider_repository import (
    ModelProviderRepository,
)
from intric.settings.encryption_service import EncryptionService

if TYPE_CHECKING:
    pass


class ModelProviderService:
    """Service for managing model providers with credential encryption."""

    def __init__(self, repository: ModelProviderRepository, encryption: EncryptionService):
        self.repository = repository
        self.encryption = encryption

    def _encrypt_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """Encrypt sensitive credential fields."""
        encrypted_creds = credentials.copy()

        # Encrypt API key if present
        if "api_key" in encrypted_creds and encrypted_creds["api_key"]:
            encrypted_creds["api_key"] = self.encryption.encrypt(encrypted_creds["api_key"])

        # Add more credential fields here if needed in the future
        # e.g., client_secret, access_token, etc.

        return encrypted_creds

    def _decrypt_credentials(self, credentials: dict[str, Any]) -> dict[str, Any]:
        """Decrypt sensitive credential fields."""
        decrypted_creds = credentials.copy()

        # Decrypt API key if present
        if "api_key" in decrypted_creds and decrypted_creds["api_key"]:
            decrypted_creds["api_key"] = self.encryption.decrypt(decrypted_creds["api_key"])

        return decrypted_creds

    async def get_all(self, active_only: bool = False) -> list[ModelProvider]:
        """Get all providers for the tenant."""
        return await self.repository.all(active_only=active_only)

    async def get_by_id(self, provider_id: UUID) -> ModelProvider:
        """Get a provider by ID."""
        return await self.repository.get_by_id(provider_id)

    async def create(
        self,
        tenant_id: UUID,
        name: str,
        provider_type: str,
        credentials: dict[str, Any],
        config: dict[str, Any],
        is_active: bool = True,
    ) -> ModelProvider:
        """Create a new provider."""
        # Check for duplicate names
        existing = await self.repository.get_by_name(name)
        if existing is not None:
            raise NameCollisionException(f"Provider with name '{name}' already exists")

        # Encrypt credentials before storing
        encrypted_credentials = self._encrypt_credentials(credentials)

        # Create domain entity
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        provider = ModelProvider(
            id=uuid4(),
            tenant_id=tenant_id,
            name=name,
            provider_type=provider_type,
            credentials=encrypted_credentials,
            config=config,
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )

        return await self.repository.create(provider)

    async def update(
        self,
        provider_id: UUID,
        name: Optional[str] = None,
        provider_type: Optional[str] = None,
        credentials: Optional[dict[str, Any]] = None,
        config: Optional[dict[str, Any]] = None,
        is_active: Optional[bool] = None,
    ) -> ModelProvider:
        """Update an existing provider."""
        # Get existing provider
        provider = await self.repository.get_by_id(provider_id)

        # Check for duplicate names if name is being changed
        if name is not None and name != provider.name:
            existing = await self.repository.get_by_name(name)
            if existing is not None:
                raise NameCollisionException(f"Provider with name '{name}' already exists")
            provider.name = name

        # Update fields if provided
        if provider_type is not None:
            provider.provider_type = provider_type

        if credentials is not None:
            provider.credentials = self._encrypt_credentials(credentials)

        if config is not None:
            provider.config = config

        if is_active is not None:
            provider.is_active = is_active

        return await self.repository.update(provider)

    async def delete(self, provider_id: UUID) -> None:
        """Delete a provider.

        Raises:
            ValueError: If the provider has models attached to it
        """
        # Check if provider has any models
        model_count = await self.repository.count_models_for_provider(provider_id)
        if model_count > 0:
            raise ValueError(
                f"Cannot delete provider: {model_count} model(s) are using this provider. "
                "Delete the models first."
            )

        await self.repository.delete(provider_id)

    async def get_decrypted_credentials(self, provider_id: UUID) -> dict[str, Any]:
        """Get decrypted credentials for a provider (for internal use only)."""
        provider = await self.repository.get_by_id(provider_id)
        return self._decrypt_credentials(provider.credentials)
