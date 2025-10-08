from typing import TYPE_CHECKING, Optional
from intric.main.config import Settings, get_settings
from intric.tenants.tenant import TenantInDB
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.settings.encryption_service import EncryptionService

logger = get_logger(__name__)


class CredentialResolver:
    """
    Strict credential resolution (no silent fallback):
    1. Tenant has credential for provider? → Use it exclusively
    2. No tenant credential? → Use global env var
    3. Neither exists? → Raise ValueError
    """

    def __init__(
        self,
        tenant: Optional[TenantInDB] = None,
        settings: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
    ):
        self.tenant = tenant
        self.settings = settings or get_settings()
        self.encryption = encryption_service

    def get_api_key(self, provider: str) -> str:
        """Get API key with decryption support and strict resolution."""
        provider_lower = provider.lower()

        # Check tenant-specific credential first
        if self.tenant and self.tenant.api_credentials:
            tenant_cred = self.tenant.api_credentials.get(provider_lower)
            if tenant_cred:
                # Extract api_key with type validation
                if isinstance(tenant_cred, str):
                    api_key = tenant_cred
                elif isinstance(tenant_cred, dict):
                    api_key = tenant_cred.get("api_key")
                else:
                    logger.error(
                        f"Invalid credential format for provider {provider}",
                        extra={
                            "tenant_id": str(self.tenant.id),
                            "tenant_name": self.tenant.name,
                            "provider": provider,
                            "credential_type": type(tenant_cred).__name__,
                        },
                    )
                    raise ValueError(
                        f"Invalid credential format for provider '{provider}'. "
                        f"Expected string or dict, got {type(tenant_cred).__name__}."
                    )

                # Decrypt if needed
                if self.encryption and api_key:
                    try:
                        api_key = self.encryption.decrypt(api_key)
                    except ValueError as e:
                        logger.error(
                            f"Failed to decrypt credential for provider {provider}: {e}",
                            extra={
                                "tenant_id": str(self.tenant.id),
                                "provider": provider,
                            },
                        )
                        raise ValueError(
                            f"Failed to decrypt credential for provider '{provider}'. "
                            f"Encryption key may be incorrect or data corrupted."
                        )

                logger.info(
                    "Credential resolved successfully",
                    extra={
                        "tenant_id": str(self.tenant.id),
                        "tenant_name": self.tenant.name,
                        "provider": provider,
                        "credential_source": "tenant",
                        "metric_name": "credential.tenant.resolved",
                        "metric_value": 1,
                    },
                )
                return api_key

        # Fallback to global (only if tenant has NO credential for this provider)
        env_map = {
            "openai": self.settings.openai_api_key,
            "anthropic": self.settings.anthropic_api_key,
            "azure": self.settings.azure_api_key,
            "berget": self.settings.berget_api_key,
            "mistral": self.settings.mistral_api_key,
            "ovhcloud": self.settings.ovhcloud_api_key,
            "vllm": self.settings.vllm_api_key,
        }

        global_key = env_map.get(provider_lower)
        if global_key:
            logger.info(
                "Credential resolved successfully",
                extra={
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                    "tenant_name": self.tenant.name if self.tenant else "N/A",
                    "provider": provider,
                    "credential_source": "global",
                    "metric_name": "credential.global.resolved",
                    "metric_value": 1,
                },
            )
            return global_key

        # No credential available
        logger.error(
            f"No credential configured for provider {provider}",
            extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "provider": provider,
            },
        )

        # Provide helpful error message based on whether tenant credentials are enabled
        if self.settings.tenant_credentials_enabled and self.tenant:
            tenant_id = self.tenant.id
            error_msg = (
                f"No API key configured for provider '{provider}'. "
                f"Tenant-specific credentials are enabled. "
                f"Please configure {provider.upper()} credentials via:\n"
                f"PUT /api/v1/sysadmin/tenants/{tenant_id}/credentials/{provider}"
            )
        else:
            error_msg = (
                f"No API key configured for provider '{provider}'. "
                f"Please set the global environment variable for {provider.upper()} API key."
            )

        raise ValueError(error_msg)

    def get_credential_field(
        self,
        provider: str,
        field: str,
        fallback: Optional[str] = None,
        decrypt: bool = False,
    ) -> Optional[str]:
        """
        Get any field from tenant credentials with fallback to global settings.

        IMPORTANT: Same strict logic as get_api_key():
        - If tenant HAS credential for provider → use exclusively (no fallback even if field invalid)
        - If tenant has NO credential for provider → use fallback

        Args:
            provider: Provider name (azure, vllm, openai, etc.)
            field: Field name (api_key, endpoint, api_version, deployment_name, etc.)
            fallback: Global setting to use if tenant has NO credential for provider
            decrypt: Whether to decrypt value (True for api_key fields)

        Returns:
            Field value from tenant credential or fallback, or None if neither exists

        Examples:
            # Get tenant-specific or global VLLM endpoint
            endpoint = resolver.get_credential_field("vllm", "endpoint", settings.vllm_model_url)

            # Get tenant-specific or global API key (with decryption)
            api_key = resolver.get_credential_field("azure", "api_key", settings.azure_api_key, decrypt=True)
        """
        provider_lower = provider.lower()

        # Check if tenant has ANY credential for this provider
        if self.tenant and self.tenant.api_credentials:
            tenant_cred = self.tenant.api_credentials.get(provider_lower)
            if tenant_cred:
                # Tenant HAS credential for provider → get field from it
                # (NO fallback to global, even if field is missing/invalid)
                if isinstance(tenant_cred, dict):
                    value = tenant_cred.get(field)
                    if value:
                        # Decrypt if requested
                        if decrypt and self.encryption:
                            try:
                                value = self.encryption.decrypt(value)
                            except ValueError as e:
                                logger.error(
                                    f"Failed to decrypt {field} for {provider}",
                                    extra={
                                        "tenant_id": str(self.tenant.id),
                                        "provider": provider,
                                        "field": field,
                                    },
                                )
                                raise ValueError(
                                    f"Failed to decrypt {field} for provider '{provider}'. "
                                    f"Encryption key may be incorrect or data corrupted."
                                )

                        logger.info(
                            f"Credential field '{field}' resolved from tenant",
                            extra={
                                "tenant_id": str(self.tenant.id),
                                "tenant_name": self.tenant.name,
                                "provider": provider,
                                "field": field,
                                "source": "tenant",
                            },
                        )
                        return value

                # Tenant has credential but field missing → return None (no fallback)
                logger.debug(
                    f"Tenant has {provider} credential but '{field}' field missing",
                    extra={
                        "tenant_id": str(self.tenant.id),
                        "provider": provider,
                        "field": field,
                    },
                )
                return None

        # Tenant has NO credential for this provider → fallback allowed
        if fallback:
            logger.info(
                f"Credential field '{field}' resolved from global settings",
                extra={
                    "provider": provider,
                    "field": field,
                    "source": "global",
                },
            )
            return fallback

        return None
