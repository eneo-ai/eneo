from uuid import UUID

from intric.feature_flag.feature_flag import FeatureFlag
from intric.feature_flag.feature_flag_repo import FeatureFlagRepository


class FeatureFlagService:
    def __init__(
        self,
        feature_flag_repo: FeatureFlagRepository,
    ):
        self.feature_flag_repo = feature_flag_repo

    async def create_feature_flag(
        self,
        name: str,
        description: str | None = None,
    ) -> FeatureFlag:
        feature_flag = FeatureFlag(name=name, description=description)
        return await self.feature_flag_repo.add(feature_flag)

    async def enable_tenant(
        self,
        feature_id: UUID,
        tenant_id: UUID,
    ) -> FeatureFlag:
        feature_flag = await self.feature_flag_repo.one(id=feature_id)
        feature_flag.enable_tenant(tenant_id=tenant_id)
        updated_feature_flag = await self.feature_flag_repo.update(feature_flag)
        return updated_feature_flag

    async def disable_tenant(
        self,
        feature_id: UUID,
        tenant_id: UUID,
    ) -> FeatureFlag:
        feature_flag = await self.feature_flag_repo.one(id=feature_id)
        feature_flag.disable_tenant(tenant_id=tenant_id)
        updated_feature_flag = await self.feature_flag_repo.update(feature_flag)
        return updated_feature_flag

    async def check_is_feature_enabled(
        self,
        feature_name: str,
        tenant_id: UUID | None = None,
    ) -> bool:
        return await self._check_feature_enabled_with_default(
            feature_name=feature_name,
            tenant_id=tenant_id,
            missing_default=False,
        )

    async def check_is_feature_enabled_fail_closed(
        self,
        feature_name: str,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Check feature state with fail-closed behavior on missing flag rows.

        Security-sensitive controls should use this when missing flag records
        must default to enabled.
        """
        return await self._check_feature_enabled_with_default(
            feature_name=feature_name,
            tenant_id=tenant_id,
            missing_default=True,
        )

    async def _check_feature_enabled_with_default(
        self,
        *,
        feature_name: str,
        tenant_id: UUID | None,
        missing_default: bool,
    ) -> bool:
        feature_flag = await self.feature_flag_repo.one_or_none(name=feature_name)
        if feature_flag is None:
            return missing_default
        return feature_flag.is_enabled(tenant_id=tenant_id)
