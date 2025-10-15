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

        # Strict mode: When tenant credentials enabled, each tenant MUST configure their own
        # This prevents billing confusion (tenant thinks they use their own key, but actually use global)
        if self.settings.tenant_credentials_enabled and self.tenant:
            logger.error(
                f"No credential configured for provider {provider}",
                extra={
                    "tenant_id": str(self.tenant.id),
                    "tenant_name": self.tenant.name,
                    "provider": provider,
                    "mode": "strict",
                },
            )
            raise ValueError(
                f"No API key configured for provider '{provider}'. "
                f"Tenant-specific credentials are enabled - each tenant must configure their own credentials. "
                f"Please configure {provider.upper()} credentials via:\n"
                f"PUT /api/v1/sysadmin/tenants/{self.tenant.id}/credentials/{provider}"
            )

        # Single-tenant mode: Fallback to global .env configuration
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
                    "mode": "single-tenant",
                    "metric_name": "credential.global.resolved",
                    "metric_value": 1,
                },
            )
            return global_key

        # No credential available anywhere
        logger.error(
            f"No credential configured for provider {provider}",
            extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "provider": provider,
            },
        )
        raise ValueError(
            f"No API key configured for provider '{provider}'. "
            f"Please set the global environment variable for {provider.upper()} API key."
        )

    def get_credential_field(
        self,
        provider: str,
        field: str,
        fallback: Optional[str] = None,
        decrypt: bool = False,
    ) -> Optional[str]:
        """
        Get any field from tenant credentials with strict mode support.

        IMPORTANT: Same strict logic as get_api_key():
        - If tenant HAS credential for provider → use exclusively (no fallback even if field missing)
        - If tenant has NO credential AND TENANT_CREDENTIALS_ENABLED=true → NO fallback (strict mode)
        - If tenant has NO credential AND TENANT_CREDENTIALS_ENABLED=false → use fallback (single-tenant)

        Args:
            provider: Provider name (azure, vllm, openai, etc.)
            field: Field name (api_key, endpoint, api_version, deployment_name, etc.)
            fallback: Global setting to use in single-tenant mode only
            decrypt: Whether to decrypt value (True for api_key fields)

        Returns:
            Field value from tenant credential, or fallback (single-tenant only), or None

        Examples:
            # Get tenant-specific or global VLLM endpoint (single-tenant fallback)
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
                    if value not in (None, ""):
                        # Decrypt if requested
                        if decrypt and self.encryption:
                            try:
                                value = self.encryption.decrypt(value)
                            except ValueError:
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

                # Tenant has credential but required field missing → block fallback
                logger.error(
                    f"Missing required field '{field}' for provider {provider}",
                    extra={
                        "tenant_id": str(self.tenant.id),
                        "tenant_name": self.tenant.name,
                        "provider": provider,
                        "field": field,
                    },
                )
                raise ValueError(
                    f"Tenant credential for provider '{provider}' is missing required field '{field}'. "
                    f"Please configure the credential via PUT /api/v1/sysadmin/tenants/{self.tenant.id}/credentials/{provider}."
                )

        # Strict mode: When tenant credentials enabled, no fallback to global
        # This prevents tenants from silently using shared infrastructure when they expect their own
        if self.settings.tenant_credentials_enabled and self.tenant:
            logger.info(
                f"Strict mode: No {field} configured for provider {provider}",
                extra={
                    "tenant_id": str(self.tenant.id),
                    "tenant_name": self.tenant.name,
                    "provider": provider,
                    "field": field,
                    "mode": "strict",
                },
            )
            return None  # No fallback in strict mode

        # Single-tenant mode: Fallback to global allowed
        if fallback:
            logger.info(
                f"Credential field '{field}' resolved from global settings",
                extra={
                    "provider": provider,
                    "field": field,
                    "source": "global",
                    "mode": "single-tenant",
                },
            )
            return fallback

        return None
