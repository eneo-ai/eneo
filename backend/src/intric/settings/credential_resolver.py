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
                    if value:
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
        Get federation config with strict resolution (EXACT same pattern as get_api_key).

        Resolution order:
        1. Tenant has federation_config? → Use it exclusively (decrypt client_secret)
        2. Strict mode (enabled + tenant exists) → ERROR (no fallback)
        3. Single-tenant mode → Fallback to global OIDC_* env vars
        4. No config anywhere → ERROR

        Returns:
            dict: Federation config with decrypted client_secret

        Raises:
            ValueError: No IdP configured (strict mode or no config anywhere)
        """
        # Check tenant-specific federation config first
        if self.tenant and self.tenant.federation_config:
            config = self.tenant.federation_config.copy()

            # Decrypt client_secret if present
            if self.encryption and config.get("client_secret"):
                try:
                    config["client_secret"] = self.encryption.decrypt(config["client_secret"])
                except ValueError as e:
                    logger.error(
                        f"Failed to decrypt federation client_secret: {e}",
                        extra={
                            "tenant_id": str(self.tenant.id),
                            "tenant_name": self.tenant.name,
                        },
                    )
                    raise ValueError(
                        "Failed to decrypt federation config. "
                        "Encryption key may be incorrect or data corrupted."
                    )

            logger.info(
                f"Federation config resolved for tenant {self.tenant.name} (provider: {config.get('provider')})",
                extra={
                    "tenant_id": str(self.tenant.id),
                    "tenant_name": self.tenant.name,
                    "provider": config.get("provider"),
                    "credential_source": "tenant",
                    "metric_name": "federation.tenant.resolved",
                    "metric_value": 1,
                },
            )
            return config

        # Strict mode: When federation enabled, each tenant MUST configure their own
        if self.settings.federation_per_tenant_enabled and self.tenant:
            logger.error(
                f"No federation config found for tenant {self.tenant.name} (strict mode)",
                extra={
                    "tenant_id": str(self.tenant.id),
                    "tenant_name": self.tenant.name,
                    "mode": "strict",
                },
            )
            raise ValueError(
                f"No identity provider configured for tenant '{self.tenant.name}'. "
                f"Federation per tenant is enabled - each tenant must configure their own IdP. "
                f"Please configure federation via:\n"
                f"PUT /api/v1/sysadmin/tenants/{self.tenant.id}/federation"
            )

        # Single-tenant mode: Fallback to global OIDC_* configuration
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
                "Federation config resolved from global OIDC environment variables",
                extra={
                    "credential_source": "global",
                    "mode": "single-tenant",
                    "metric_name": "federation.global.resolved",
                    "metric_value": 1,
                },
            )
            return config

        # No configuration available anywhere
        logger.error(
            "No federation config available for tenant or globally",
            extra={
                "tenant_id": str(self.tenant.id) if self.tenant else None,
            },
        )
        raise ValueError(
            "No identity provider configured. "
            "Please set global OIDC_* environment variables or configure tenant-specific federation."
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
        - Clean URL: https://stockholm.eneo.se
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
        # But double-check HTTPS as defense in depth
        if not origin.startswith("https://"):
            logger.error(
                f"Public origin must be HTTPS: {origin}",
                extra={
                    "tenant_id": str(self.tenant.id) if self.tenant else None,
                    "origin": origin,
                },
            )
            raise ValueError(
                f"Public origin must be an https:// URL for security. Got: {origin}"
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
