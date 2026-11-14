import os
from typing import TYPE_CHECKING, Optional, cast

from eneo.main.config import Settings, get_settings
from eneo.main.logging import get_logger
from eneo.tenants.tenant import TenantInDB

if TYPE_CHECKING:
    from eneo.settings.encryption_service import EncryptionService

logger = get_logger(__name__)


class CredentialResolver:
    """
    Credential resolution with strict multi-tenant enforcement:

    When TENANT_CREDENTIALS_ENABLED=true (multi-tenant mode):
    1. Tenant has credential for provider? → Use it exclusively
    2. No tenant credential? → ERROR (no fallback to global)

    When TENANT_CREDENTIALS_ENABLED=false (single-tenant mode):
    1. Tenant has credential for provider? → Use it exclusively
    2. No tenant credential? → Fallback to global env var
    3. Neither exists? → ERROR

    This prevents security/billing issues where tenants silently use shared credentials.
    """

    def __init__(
        self,
        tenant: Optional[TenantInDB] = None,
        settings: Optional[Settings] = None,
        encryption_service: Optional["EncryptionService"] = None,
    ):
        super().__init__()
        self.tenant = tenant
        self.settings = settings or get_settings()
        self.encryption = encryption_service
        self._source_cache: dict[str, str] = {}

    def get_api_key(self, provider: str) -> str:
        """Get API key with decryption support and strict resolution."""
        provider_lower = provider.lower()

        # Check tenant-specific credential first
        if self.tenant and self.tenant.api_credentials:
            api_credentials = cast(dict[str, object], self.tenant.api_credentials)
            tenant_cred = api_credentials.get(provider_lower)
            if tenant_cred:
                # Extract api_key with type validation
                api_key: Optional[str]
                if isinstance(tenant_cred, str):
                    api_key = tenant_cred
                elif isinstance(tenant_cred, dict):
                    raw = cast(dict[str, object], tenant_cred).get("api_key")
                    api_key = raw if isinstance(raw, str) else None
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
                if self.encryption and self.encryption.is_active() and api_key:
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

                self._source_cache[provider_lower] = "tenant"
                logger.debug(
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
                return api_key  # type: ignore[return-value]  # api_key may be None when dict credential lacks api_key field; caller treats missing key as unresolved

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
            "mistral": self.settings.mistral_api_key,
            "ovhcloud": self.settings.ovhcloud_api_key,
            "vllm": self.settings.vllm_api_key,
        }

        def _resolve_global_env_var(name: str) -> Optional[str]:
            value = env_map.get(name)
            if value:
                return value
            env_name = f"{name.upper()}_API_KEY"
            return os.getenv(env_name)

        global_key = _resolve_global_env_var(provider_lower)
        if global_key:
            self._source_cache[provider_lower] = "global"
            logger.debug(
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

        # No credential available anywhere (single-tenant mode only at this point)
        self._source_cache[provider_lower] = "missing"

        logger.error(
            f"No credential configured for provider {provider}",
            extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "provider": provider,
            },
        )
        raise ValueError(
            f"No API key configured for provider '{provider}'. "
            "Please set the global environment variable or contact your system administrator."
        )

    def uses_global_credentials(self, provider: str) -> bool:
        """Return True if the last resolved credential came from the global fallback."""
        provider_lower = provider.lower()
        return self._source_cache.get(provider_lower) == "global"

    def get_credential_field(
        self,
        provider: str,
        field: str,
        fallback: Optional[str] = None,
        decrypt: bool = False,
        required: bool = False,
    ) -> Optional[str]:
        """
        Get any field from tenant credentials with strict mode support.

        Distinguishes between required and optional credential fields to support
        provider-specific configurations. Critically, in strict mode (multi-tenant),
        NEVER falls back to global settings - this preserves tenant isolation.

        Resolution logic:
        1. If tenant HAS credential for provider:
           - If field exists: decrypt (if needed) and return it
           - If field missing and required=True: raise ValueError (strict enforcement)
           - If field missing and required=False:
             * Strict mode (tenant_credentials_enabled=true): return None (NO fallback)
             * Single-tenant mode: return fallback (allow global defaults)
        2. If tenant has NO credential:
           - If TENANT_CREDENTIALS_ENABLED=true: return None (strict mode, no fallback)
           - If TENANT_CREDENTIALS_ENABLED=false: return fallback (single-tenant mode)

        Args:
            provider: Provider name (azure, vllm, openai, etc.)
            field: Field name (api_key, endpoint, api_version, deployment_name, etc.)
            fallback: Default value to use if field is missing (None for truly optional)
            decrypt: Whether to decrypt value (True for sensitive fields like api_key)
            required: Whether this field is required for the provider. If False, allows
                     missing fields even in strict mode (for provider-specific optional fields).
                     Examples:
                     - OpenAI endpoint: required=False (endpoint not needed)
                     - vLLM endpoint: required=True (endpoint always needed)
                     - Azure api_version: required=False (can fallback to global)

        Returns:
            Field value from tenant credential, or fallback, or None

        Examples:
            # OpenAI endpoint (optional) - returns None without error
            endpoint = resolver.get_credential_field(
                "openai", "endpoint", fallback=None, required=False
            )

            # vLLM endpoint (required) - raises error if tenant has key but missing endpoint
            endpoint = resolver.get_credential_field(
                "vllm", "endpoint", fallback=settings.vllm_model_url, required=True
            )

            # Azure api_version (optional with fallback)
            api_version = resolver.get_credential_field(
                "azure", "api_version", fallback=settings.azure_api_version, required=False
            )
        """
        provider_lower = provider.lower()

        # Check if tenant has ANY credential for this provider
        if self.tenant and self.tenant.api_credentials:
            api_credentials = cast(dict[str, object], self.tenant.api_credentials)
            tenant_cred = api_credentials.get(provider_lower)
            if tenant_cred:
                # Tenant HAS credential for provider → get field from it
                # (NO fallback to global, even if field is missing/invalid)
                if isinstance(tenant_cred, dict):
                    cred_dict = cast(dict[str, object], tenant_cred)
                    raw_value = cred_dict.get(field)
                    value: Optional[str] = (
                        raw_value if isinstance(raw_value, str) else None
                    )
                    if value not in (None, ""):
                        # Decrypt if requested
                        if decrypt and self.encryption and self.encryption.is_active():
                            try:
                                value = self.encryption.decrypt(value)  # type: ignore[arg-type]  # value is str here (guarded by `not in (None, "")`)
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

                # Field is missing from tenant credentials
                if required:
                    # Required field missing → raise error (strict enforcement)
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
                else:
                    # Optional field missing
                    if self.settings.tenant_credentials_enabled and self.tenant:
                        # STRICT MODE (multi-tenant): NEVER fallback to global settings
                        # Return None to signal field is not configured for this tenant
                        logger.info(
                            f"Strict mode: Optional field '{field}' missing for provider {provider}; no fallback used",
                            extra={
                                "tenant_id": str(self.tenant.id),
                                "tenant_name": self.tenant.name,
                                "provider": provider,
                                "field": field,
                                "mode": "strict",
                            },
                        )
                        return None

                    # SINGLE-TENANT MODE: allow fallback to global settings
                    logger.info(
                        f"Single-tenant mode: Optional field '{field}' missing for provider {provider}, using provided fallback",
                        extra={
                            "provider": provider,
                            "field": field,
                            "fallback_used": fallback is not None,
                            "source": "fallback",
                            "mode": "single-tenant",
                        },
                    )
                    return fallback

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
