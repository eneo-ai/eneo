import os
from typing import TYPE_CHECKING, Optional
from intric.main.config import Settings, get_settings
from intric.tenants.tenant import TenantInDB
from intric.main.logging import get_logger

if TYPE_CHECKING:
    from intric.settings.encryption_service import EncryptionService

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
        self.tenant = tenant
        self.settings = settings or get_settings()
        self.encryption = encryption_service
        self._source_cache: dict[str, str] = {}

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
            "gdm": self.settings.gdm_api_key,
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
            tenant_cred = self.tenant.api_credentials.get(provider_lower)
            if tenant_cred:
                # Tenant HAS credential for provider → get field from it
                # (NO fallback to global, even if field is missing/invalid)
                if isinstance(tenant_cred, dict):
                    value = tenant_cred.get(field)
                    if value not in (None, ""):
                        # Decrypt if requested
                        if decrypt and self.encryption and self.encryption.is_active():
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

    def get_federation_config(self) -> dict:
        """
        Get federation config with strict resolution based on federation_per_tenant_enabled flag.

        Resolution logic:
        - federation_per_tenant_enabled=true (multi-tenant mode):
          1. Tenant has federation_config in DB? → Use it exclusively (decrypt client_secret)
          2. No tenant federation_config? → ERROR (strict mode, no fallback to env)

        - federation_per_tenant_enabled=false (single-tenant mode):
          1. ONLY use global OIDC_* env vars (ignore DB config even if present)
          2. No env vars? → ERROR

        Returns:
            dict: Federation config with decrypted client_secret

        Raises:
            ValueError: No IdP configured (strict mode or no env vars in single-tenant mode)
        """
        # SINGLE-TENANT MODE (federation_per_tenant_enabled=false):
        # ONLY use environment variables, never check database
        if not self.settings.federation_per_tenant_enabled:
            if self.settings.oidc_discovery_endpoint and self.settings.oidc_client_secret:
                config = {
                    "provider": "mobilityguard",  # Legacy global provider
                    "discovery_endpoint": self.settings.oidc_discovery_endpoint,
                    "client_id": self.settings.oidc_client_id,
                    "client_secret": self.settings.oidc_client_secret,
                    "tenant_id": self.settings.oidc_tenant_id,
                    "scopes": ["openid", "email", "profile"],
                }

                logger.info(
                    "Federation config resolved from global OIDC environment variables (single-tenant mode)",
                    extra={
                        "credential_source": "global",
                        "mode": "single-tenant",
                        "federation_per_tenant_enabled": False,
                        "metric_name": "federation.global.resolved",
                        "metric_value": 1,
                    },
                )
                return config

            # No global env vars configured
            logger.error(
                "No global OIDC configuration found (federation_per_tenant_enabled=false)",
                extra={
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                    "mode": "single-tenant",
                },
            )
            raise ValueError(
                "No identity provider configured. "
                "federation_per_tenant_enabled is false, so only global OIDC_* environment variables are used. "
                "Please set OIDC_DISCOVERY_ENDPOINT, OIDC_CLIENT_ID, and OIDC_CLIENT_SECRET in your .env file."
            )

        # MULTI-TENANT MODE (federation_per_tenant_enabled=true):
        # Check tenant-specific federation config in database
        if self.tenant and self.tenant.federation_config:
            config = self.tenant.federation_config.copy()

            # Decrypt client_secret if present
            if (
                self.encryption
                and self.encryption.is_active()
                and config.get("client_secret")
            ):
                raw_secret = config["client_secret"]

                if not self.encryption.is_encrypted(raw_secret):
                    logger.error(
                        "Federation client_secret missing encryption envelope",
                        extra={
                            "tenant_id": str(self.tenant.id),
                            "tenant_name": self.tenant.name,
                            "provider": config.get("provider"),
                        },
                    )
                    raise ValueError(
                        f"Federation client_secret for tenant '{self.tenant.name}' is not encrypted. "
                        "Delete the credential and upload a new value after confirming ENCRYPTION_KEY is configured."
                    )

                try:
                    config["client_secret"] = self.encryption.decrypt(raw_secret)
                except ValueError as e:
                    logger.error(
                        "Failed to decrypt federation client_secret",
                        extra={
                            "tenant_id": str(self.tenant.id),
                            "tenant_name": self.tenant.name,
                            "provider": config.get("provider"),
                            "error": str(e),
                        },
                    )
                    raise ValueError(
                        "Failed to decrypt federation config. Encryption key may be incorrect or data corrupted. "
                        "Rotate the tenant credential by removing and re-adding it with the active encryption key."
                    )

            logger.info(
                f"Federation config resolved for tenant {self.tenant.name} (provider: {config.get('provider')})",
                extra={
                    "tenant_id": str(self.tenant.id),
                    "tenant_name": self.tenant.name,
                    "provider": config.get("provider"),
                    "credential_source": "tenant",
                    "federation_per_tenant_enabled": True,
                    "metric_name": "federation.tenant.resolved",
                    "metric_value": 1,
                },
            )
            return config

        # Strict mode: When federation_per_tenant_enabled=true, each tenant MUST configure their own
        if self.settings.federation_per_tenant_enabled and self.tenant:
            logger.error(
                f"No federation config found for tenant {self.tenant.name} (strict mode)",
                extra={
                    "tenant_id": str(self.tenant.id),
                    "tenant_name": self.tenant.name,
                    "mode": "strict",
                    "federation_per_tenant_enabled": True,
                },
            )
            raise ValueError(
                f"No identity provider configured for tenant '{self.tenant.name}'. "
                f"federation_per_tenant_enabled is true - each tenant must configure their own IdP in the database. "
                f"Please configure federation via:\n"
                f"PUT /api/v1/sysadmin/tenants/{self.tenant.id}/federation"
            )

        # No configuration available (shouldn't reach here, but defensive)
        logger.error(
            "No federation config available",
            extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "federation_per_tenant_enabled": self.settings.federation_per_tenant_enabled,
            },
        )
        raise ValueError(
            "No identity provider configured. "
            "Please configure tenant-specific federation or set global OIDC_* environment variables."
        )

    def get_redirect_uri(self) -> str:
        """
        Get redirect_uri for OIDC flows.

        Universal resolution for single-tenant and multi-tenant:
        1. Tenant federation_config.canonical_public_origin (multi-tenant)
        2. Global settings.public_origin (single-tenant fallback)
        3. Error if neither configured

        The canonical_public_origin can be ANY externally-reachable URL:
        - Proxy URL: https://m00-https-eneo-test.login.sundsvall.se
        - Clean URL: https://sundsvall.eneo.se
        - Whatever works for that tenant's network topology!

        Returns:
            str: Complete redirect_uri (origin + path)

        Raises:
            ValueError: No public origin configured

        Examples:
            # Single-tenant mode
            resolver = CredentialResolver(tenant=None, settings=settings)
            uri = resolver.get_redirect_uri()
            # Returns: https://{settings.public_origin}/login/callback

            # Multi-tenant mode
            resolver = CredentialResolver(tenant=tenant_obj, settings=settings)
            uri = resolver.get_redirect_uri()
            # Returns: https://{tenant.federation_config.canonical_public_origin}/login/callback
        """
        # Get federation config (handles tenant/global resolution)
        try:
            federation_config = self.get_federation_config()
        except ValueError as e:
            logger.error(
                "Cannot compute redirect_uri: federation config missing or invalid",
                extra={
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                    "error": str(e),
                },
            )
            raise ValueError(
                f"Cannot compute redirect_uri: {e}. "
                "Ensure OIDC configuration is set up correctly."
            ) from e

        # Check tenant-specific origin in federation_config
        origin = federation_config.get("canonical_public_origin")

        # Fallback to global public_origin (single-tenant mode)
        # Explicit check for None or empty/whitespace strings
        if origin is None or not origin.strip():
            origin = self.settings.public_origin

        # Normalize origin by stripping whitespace
        if isinstance(origin, str):
            origin = origin.strip()

        if not origin:
            # Context-aware error message
            if self.settings.federation_per_tenant_enabled and self.tenant:
                # Strict mode: tenant MUST configure their own origin
                logger.error(
                    f"No canonical_public_origin configured for tenant {self.tenant.name} (strict mode)",
                    extra={
                        "tenant_id": str(self.tenant.id),
                        "tenant_name": self.tenant.name,
                        "mode": "strict",
                    },
                )
                raise ValueError(
                    f"No public origin configured for tenant '{self.tenant.name}'. "
                    f"Federation per tenant is enabled - each tenant must configure canonical_public_origin. "
                    f"Please configure via:\n"
                    f"PUT /api/v1/sysadmin/tenants/{self.tenant.id}/federation\n"
                    f'Body: {{"canonical_public_origin": "https://your-tenant.eneo.se"}}'
                )
            else:
                # Single-tenant mode: need global config
                tenant_context = f" for tenant '{self.tenant.name}'" if self.tenant else ""
                logger.error(
                    f"No public origin configured{tenant_context}",
                    extra={
                        "tenant_id": str(self.tenant.id) if self.tenant else None,
                    },
                )
                raise ValueError(
                    "No public origin configured. "
                    "Please set PUBLIC_ORIGIN environment variable in your .env file. "
                    "Example: PUBLIC_ORIGIN=https://eneo.sundsvall.se"
                )

        # Origin should already be validated and normalized by Settings/Tenant validators
        # But double-check HTTPS as defense in depth (allow http://localhost for development)
        is_localhost = origin.startswith("http://localhost") or origin.startswith("http://127.0.0.1")
        if not origin.startswith("https://") and not is_localhost:
            logger.error(
                f"Public origin must be HTTPS: {origin}",
                extra={
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                    "origin": origin,
                },
            )
            raise ValueError(
                f"Public origin must be an https:// URL for security (or http://localhost for development). Got: {origin}"
            )

        # Normalize: strip trailing slash (defense in depth)
        origin = origin.rstrip("/")

        # Get redirect path (support customization per tenant)
        redirect_path = federation_config.get("redirect_path", "/login/callback")

        redirect_uri = f"{origin}{redirect_path}"

        logger.info(
            "Redirect URI resolved successfully",
            extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None,
                "tenant_name": self.tenant.name if self.tenant else "single-tenant",
                "redirect_uri": redirect_uri,
                "source": "tenant" if federation_config.get("canonical_public_origin") else "global",
                "metric_name": "oidc.redirect_uri.resolved",
                "metric_value": 1,
            },
        )

        return redirect_uri
