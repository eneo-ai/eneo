from intric.database.tables.feature_flag_table import (
    GlobalFeatureFlag,
    TenantFeatureFlag,
)
from intric.feature_flag.feature_flag import FeatureFlag


class FeatureFlagFactory:
    @classmethod
    def create_domain_feature_flag(
        cls,
        global_feature_flag: GlobalFeatureFlag,
        tenant_feature_flags: list[TenantFeatureFlag],
    ) -> FeatureFlag:
        tenant_ids = set()
        disabled_tenant_ids = set()

        if tenant_feature_flags:
            for tf in tenant_feature_flags:
                if tf.enabled:
                    tenant_ids.add(tf.tenant_id)
                else:
                    disabled_tenant_ids.add(tf.tenant_id)

        return FeatureFlag(
            feature_id=global_feature_flag.id,
            name=global_feature_flag.name,
            tenant_ids=tenant_ids,
            disabled_tenant_ids=disabled_tenant_ids,
            is_enabled_globally=global_feature_flag.enabled,
            description=global_feature_flag.description,
        )
