from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.governance_policy.application.governance_policy_service import (
    GovernancePolicyService,
)
from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyScope,
)
from eneo.roles.permissions import Permission


def _admin(tenant_id):
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = tenant_id
    user.permissions = {Permission.ADMIN}
    return user


async def test_update_policy_locks_row_before_reading_and_saving():
    tenant_id = uuid4()
    policy = GovernancePolicy(
        id=uuid4(),
        tenant_id=tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
    )
    repo = AsyncMock()
    repo.get_by_tenant_for_update.return_value = policy
    repo.save.return_value = policy
    service = GovernancePolicyService(
        user=_admin(tenant_id),
        repo=repo,
        completion_model_crud_service=AsyncMock(),
        mcp_server_settings_service=AsyncMock(),
        prompt_library_service=AsyncMock(),
        model_provider_repository=AsyncMock(),
    )

    result = await service.update_policy(
        prompt_enforcement=(False, None),
    )

    assert result is policy
    repo.get_by_tenant_for_update.assert_awaited_once_with(
        tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )
    repo.get_by_tenant.assert_not_called()
    repo.save.assert_awaited_once()


async def test_update_policy_creates_then_locks_missing_row():
    tenant_id = uuid4()
    policy = GovernancePolicy(
        id=uuid4(),
        tenant_id=tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
    )
    repo = AsyncMock()
    repo.get_by_tenant_for_update.side_effect = [None, policy]
    repo.save.return_value = policy
    service = GovernancePolicyService(
        user=_admin(tenant_id),
        repo=repo,
        completion_model_crud_service=AsyncMock(),
        mcp_server_settings_service=AsyncMock(),
        prompt_library_service=AsyncMock(),
        model_provider_repository=AsyncMock(),
    )

    await service.update_policy(prompt_enforcement=(False, None))

    repo.create_empty.assert_awaited_once_with(
        tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )
    assert repo.get_by_tenant_for_update.await_count == 2
