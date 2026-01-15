"""Feature flag domain class"""

from uuid import UUID


class FeatureFlag:
    def __init__(
        self,
        name: str,
        feature_id: UUID | None = None,
        tenant_ids: set = set(),
        is_enabled_globally: bool = False,
        description: str | None = None,
    ):
        self.feature_id = feature_id
        self.name = name
        self.tenant_ids = tenant_ids
        self.is_enabled_globally = is_enabled_globally
        self.description = description

    def is_enabled(self, tenant_id: UUID | None) -> bool:
        enabled = self.is_enabled_globally or tenant_id in self.tenant_ids
        return enabled

    def disable_tenant(self, tenant_id: UUID) -> None:
        # Use discard() instead of remove() to make this operation idempotent
        # remove() raises KeyError if tenant not in set, discard() is safe
        self.tenant_ids.discard(tenant_id)

    def enable_tenant(self, tenant_id: UUID) -> None:
        self.tenant_ids.add(tenant_id)
