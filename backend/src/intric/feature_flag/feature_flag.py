"""Feature flag domain class"""

from uuid import UUID


class FeatureFlag:
    def __init__(
        self,
        name: str,
        feature_id: UUID | None = None,
        tenant_ids: set | None = None,
        disabled_tenant_ids: set | None = None,
        is_enabled_globally: bool = False,
        description: str | None = None,
    ):
        self.feature_id = feature_id
        self.name = name
        self.tenant_ids = tenant_ids if tenant_ids is not None else set()
        self.disabled_tenant_ids = disabled_tenant_ids if disabled_tenant_ids is not None else set()
        self.is_enabled_globally = is_enabled_globally
        self.description = description

    def is_enabled(self, tenant_id: UUID | None) -> bool:
        """Check if feature is enabled for a tenant.

        Tenant preferences (from tenant_feature_flags table) override global setting.
        If tenant has explicit preference, that is used. Otherwise falls back to global default.

        Args:
            tenant_id: The tenant to check, or None

        Returns:
            True if enabled for this tenant, False otherwise
        """
        # Check if tenant has explicit preference
        if tenant_id in self.tenant_ids:
            return True
        if tenant_id in self.disabled_tenant_ids:
            return False
        # No preference: use global default
        return self.is_enabled_globally

    def enable_tenant(self, tenant_id: UUID) -> None:
        """Set tenant preference to enabled.

        Creates/updates a tenant_feature_flags record with enabled=true.

        Args:
            tenant_id: The tenant to enable
        """
        self.tenant_ids.add(tenant_id)
        self.disabled_tenant_ids.discard(tenant_id)

    def disable_tenant(self, tenant_id: UUID) -> None:
        """Set tenant preference to disabled.

        Creates/updates a tenant_feature_flags record with enabled=false.

        Args:
            tenant_id: The tenant to disable
        """
        self.disabled_tenant_ids.add(tenant_id)
        self.tenant_ids.discard(tenant_id)
