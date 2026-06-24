from unittest.mock import AsyncMock
from uuid import uuid4

from intric.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyScope,
)
from intric.governance_policy.infrastructure.governance_policy_repo_impl import (
    GovernancePolicyRepoImpl,
)


async def test_create_empty_returns_existing_policy_when_insert_conflicts():
    tenant_id = uuid4()
    existing = GovernancePolicy(
        id=uuid4(), tenant_id=tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )

    repo = GovernancePolicyRepoImpl(session=AsyncMock())
    repo.session.scalar = AsyncMock(return_value=None)
    repo.get_by_tenant = AsyncMock(return_value=existing)  # type: ignore[method-assign]

    result = await repo.create_empty(
        tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )

    assert result is existing
    repo.get_by_tenant.assert_awaited_once_with(
        tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )
