"""One fail-closed tenant gate for every flow interaction surface."""

from uuid import UUID

from eneo.feature_flag.feature_flag_service import FeatureFlagService
from eneo.main.exceptions import NotFoundException

FLOW_FEATURE = "flows_core"


async def require_flows_enabled(service: FeatureFlagService, tenant_id: UUID) -> None:
    if not await service.check_is_feature_enabled(FLOW_FEATURE, tenant_id=tenant_id):
        raise NotFoundException()
