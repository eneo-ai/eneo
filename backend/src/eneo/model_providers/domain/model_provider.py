from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

if TYPE_CHECKING:
    from eneo.database.tables.model_providers_table import ModelProviders

# Returned in place of a secret header value or fallback. Never a real value;
# a write that submits it back is rejected (see ModelProviderService).
MASKED_HEADER_VALUE = "********"


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
        outbound_headers: list[dict[str, Any]] | None = None,
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
        # Stored form: `secret` entries hold encrypted value/fallback.
        self.outbound_headers = outbound_headers or []

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
            outbound_headers=provider_db.outbound_headers,
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
            "outbound_headers": [
                _public_header(header) for header in self.outbound_headers
            ],
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


def _public_header(header: dict[str, Any]) -> dict[str, Any]:
    """A stored header as an admin may see it: secret value and fallback masked."""
    secret = bool(header.get("secret"))
    fallback = header.get("fallback")
    return {
        "id": header["id"],
        "name": header["name"],
        "value": MASKED_HEADER_VALUE if secret else header["value"],
        "encoding": header.get("encoding", "percent"),
        "secret": secret,
        "on_missing": header.get("on_missing", "omit"),
        "fallback": (
            None if fallback is None else MASKED_HEADER_VALUE if secret else fallback
        ),
        "classification": header.get("classification"),
    }
