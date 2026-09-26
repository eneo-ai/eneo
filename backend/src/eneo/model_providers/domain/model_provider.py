from datetime import date, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from eneo.model_providers.domain.connection_check import (
    ConnectionCheck,
    ConnectionCheckError,
    ConnectionCheckStatus,
)
from eneo.model_providers.domain.provider_api import (
    configured_endpoint,
    connection_check_supported,
)

if TYPE_CHECKING:
    from eneo.database.tables.model_providers_table import ModelProviders


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
        key_expires_on: date | None = None,
        connection_check: ConnectionCheck | None = None,
    ):
        super().__init__()
        self.id = id
        self.tenant_id = tenant_id
        self.name = name
        self.provider_type = provider_type  # "openai", "azure", "anthropic"
        self.credentials = credentials  # Encrypted in DB
        self.config = config  # Additional config like endpoints
        self.is_active = is_active
        self.created_at = created_at
        self.updated_at = updated_at
        # Entered by an admin: few provider APIs report when a key expires.
        self.key_expires_on = key_expires_on
        # The latest check against the stored credentials; None until one runs.
        self.connection_check = connection_check

    @classmethod
    def create_from_db(cls, provider_db: "ModelProviders") -> "ModelProvider":
        """Create domain entity from database model."""
        connection_check = None
        if provider_db.connection_status is not None:
            assert provider_db.connection_checked_at is not None
            connection_check = ConnectionCheck(
                status=ConnectionCheckStatus(provider_db.connection_status),
                checked_at=provider_db.connection_checked_at,
                error=(
                    ConnectionCheckError.parse(provider_db.connection_error)
                    if provider_db.connection_error
                    else None
                ),
            )
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
            key_expires_on=provider_db.key_expires_on,
            connection_check=connection_check,
        )

    @property
    def connection_check_supported(self) -> bool:
        return connection_check_supported(
            self.provider_type.lower(), configured_endpoint(self.config)
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary (for API responses)."""
        check = self.connection_check
        return {
            "id": str(self.id),
            "tenant_id": str(self.tenant_id),
            "name": self.name,
            "provider_type": self.provider_type,
            "config": self.config,
            "is_active": self.is_active,
            "key_expires_on": self.key_expires_on,
            "connection_check": (
                {
                    "status": check.status,
                    "checked_at": check.checked_at,
                    "error": check.error,
                }
                if check is not None
                else None
            ),
            "connection_check_supported": self.connection_check_supported,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # Credentials are not included; the stored API key may be
            # ciphertext, so its display hint comes from
            # ModelProviderService.masked_api_key.
        }
