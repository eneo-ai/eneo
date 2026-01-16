from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from intric.database.tables.model_providers_table import ModelProviders


class ModelProvider:
    """Domain entity for a tenant-specific AI model provider instance."""

    def __init__(
        self,
        id: UUID,
        tenant_id: UUID,
        name: str,
        provider_type: str,
        credentials: dict[str, Any],
        config: dict[str, Any],
        is_active: bool,
        created_at: datetime,
        updated_at: datetime,
    ):
        self.id = id
        self.tenant_id = tenant_id
        self.name = name
        self.provider_type = provider_type  # "openai", "azure", "anthropic"
        self.credentials = credentials  # Encrypted in DB
        self.config = config  # Additional config like endpoints
        self.is_active = is_active
        self.created_at = created_at
        self.updated_at = updated_at

    @classmethod
    def create_from_db(cls, provider_db: "ModelProviders") -> "ModelProvider":
        """Create domain entity from database model."""
        return cls(
            id=provider_db.id,
            tenant_id=provider_db.tenant_id,
            name=provider_db.name,
            provider_type=provider_db.provider_type,
            credentials=provider_db.credentials,
            config=provider_db.config,
            is_active=provider_db.is_active,
            created_at=provider_db.created_at,
            updated_at=provider_db.updated_at,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (for API responses)."""
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "name": self.name,
            "provider_type": self.provider_type,
            "config": self.config,
            "is_active": self.is_active,
            "masked_api_key": self._get_masked_api_key(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # Note: credentials are NOT included in the public dict
        }

    def _get_masked_api_key(self) -> str | None:
        """Return masked API key for display, or None if not configured."""
        api_key = self.credentials.get("api_key")
        if not api_key:
            return None
        return f"...{api_key[-4:]}" if len(api_key) >= 4 else "****"
