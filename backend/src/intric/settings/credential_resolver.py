from typing import Optional
from intric.main.config import Settings, get_settings
from intric.tenants.tenant import TenantInDB
from intric.main.logging import get_logger

logger = get_logger(__name__)


class CredentialResolver:
    """
    Strict credential resolution (no silent fallback):
    1. Tenant has credential for provider? → Use it exclusively
    2. No tenant credential? → Use global env var
    3. Neither exists? → Raise ValueError
    """

    def __init__(
        self, tenant: Optional[TenantInDB] = None, settings: Optional[Settings] = None
    ):
        self.tenant = tenant
        self.settings = settings or get_settings()

    def get_api_key(self, provider: str) -> str:
        """Get API key with strict resolution (no fallback if tenant key exists)"""
        provider_lower = provider.lower()

        # Check tenant-specific credential first
        if self.tenant and self.tenant.api_credentials:
            tenant_cred = self.tenant.api_credentials.get(provider_lower)
            if tenant_cred:
                api_key = (
                    tenant_cred
                    if isinstance(tenant_cred, str)
                    else tenant_cred.get("api_key")
                )
                logger.info(
                    "Credential resolved successfully",
                    extra={
                        "tenant_id": str(self.tenant.id),
                        "tenant_name": self.tenant.name,
                        "provider": provider,
                        "credential_source": "tenant",
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
        raise ValueError(
            f"No API key configured for provider '{provider}'. "
            f"Tenant must configure a credential or ensure global key is set."
        )
