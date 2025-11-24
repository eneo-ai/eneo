from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

from intric.main.logging import get_logger
from intric.settings.encryption_service import EncryptionService

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class TenantModelCredentialResolver:
    """
    Credential resolver for tenant-specific models.

    Resolves credentials from model provider data.
    This is used when a model has a provider_id set, indicating it's a tenant-specific model.
    """

    def __init__(
        self,
        provider_id: UUID,
        provider_type: str,
        credentials: dict[str, Any],
        config: dict[str, Any],
        encryption_service: EncryptionService,
    ):
        self.provider_id = provider_id
        self.provider_type = provider_type
        self.encryption = encryption_service
        self._credentials = credentials
        self._config = config

    def get_api_key(self) -> str:
        """
        Get API key for the provider.
        """
        api_key = self._credentials.get("api_key")
        if not api_key:
            raise ValueError(
                f"No API key found in credentials for provider {self.provider_id}"
            )

        # Decrypt API key
        if self.encryption and self.encryption.is_active():
            try:
                api_key = self.encryption.decrypt(api_key)
            except ValueError as e:
                logger.error(
                    f"Failed to decrypt API key for provider {self.provider_id}: {e}",
                    extra={"provider_id": str(self.provider_id)},
                )
                raise ValueError(
                    f"Failed to decrypt API key for provider {self.provider_id}. "
                    "Encryption key may be incorrect or data corrupted."
                )

        logger.debug(
            "Tenant model credential resolved",
            extra={
                "provider_id": str(self.provider_id),
                "provider_type": self.provider_type,
                "credential_source": "tenant_model_provider",
            },
        )

        return api_key

    def get_credential_field(
        self,
        field: str,
        fallback: Optional[str] = None,
        decrypt: bool = False,
        required: bool = False,
    ) -> Optional[str]:
        """
        Get any field from provider credentials or config.

        First checks credentials dict, then config dict.
        """
        # Check credentials first
        value = self._credentials.get(field)

        # Check config if not in credentials
        if value is None and self._config:
            value = self._config.get(field)

        if value is not None and value != "":
            # Decrypt if requested
            if decrypt and self.encryption and self.encryption.is_active():
                try:
                    value = self.encryption.decrypt(value)
                except ValueError:
                    logger.error(
                        f"Failed to decrypt {field} for provider {self.provider_id}",
                        extra={
                            "provider_id": str(self.provider_id),
                            "field": field,
                        },
                    )
                    raise ValueError(
                        f"Failed to decrypt {field} for provider {self.provider_id}. "
                        "Encryption key may be incorrect or data corrupted."
                    )

            logger.debug(
                f"Credential field '{field}' resolved from tenant model provider",
                extra={
                    "provider_id": str(self.provider_id),
                    "field": field,
                    "source": "tenant_model_provider",
                },
            )
            return value

        # Field is missing
        if required:
            raise ValueError(
                f"Provider {self.provider_id} is missing required field '{field}'. "
                "Please update the provider configuration."
            )

        # Return fallback for optional fields
        logger.debug(
            f"Field '{field}' not found for provider {self.provider_id}, using fallback",
            extra={
                "provider_id": str(self.provider_id),
                "field": field,
                "has_fallback": fallback is not None,
            },
        )
        return fallback

    def uses_global_credentials(self) -> bool:
        """Always returns False for tenant models - they never use global credentials."""
        return False
