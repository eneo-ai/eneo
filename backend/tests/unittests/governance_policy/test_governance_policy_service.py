from types import SimpleNamespace
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
from eneo.skills.domain.skill import SkillBindingIntent, SkillBindingReference


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
        skill_service=AsyncMock(),
        space_service=AsyncMock(),
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
        skill_service=AsyncMock(),
        space_service=AsyncMock(),
    )

    await service.update_policy(prompt_enforcement=(False, None))

    repo.create_empty.assert_awaited_once_with(
        tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )
    assert repo.get_by_tenant_for_update.await_count == 2


async def test_update_policy_replaces_exact_organization_skill_bindings():
    tenant_id = uuid4()
    policy = GovernancePolicy(
        id=uuid4(),
        tenant_id=tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
    )
    repo = AsyncMock()
    repo.get_by_tenant_for_update.return_value = policy
    repo.save.return_value = policy
    organization_space_id = uuid4()
    space_service = AsyncMock(
        get_or_create_tenant_space=AsyncMock(
            return_value=SimpleNamespace(id=organization_space_id)
        )
    )
    skill_service = AsyncMock()
    service = GovernancePolicyService(
        user=_admin(tenant_id),
        repo=repo,
        completion_model_crud_service=AsyncMock(),
        mcp_server_settings_service=AsyncMock(),
        prompt_library_service=AsyncMock(),
        model_provider_repository=AsyncMock(),
        skill_service=skill_service,
        space_service=space_service,
    )
    references = [
        SkillBindingReference(skill_id=uuid4(), skill_revision_id=uuid4()),
        SkillBindingReference(skill_id=uuid4(), skill_revision_id=uuid4()),
    ]

    intents = [SkillBindingIntent(reference=reference) for reference in references]

    result = await service.update_policy(
        prompt_enforcement=(False, None),
        skill_intents=intents,
    )

    assert result is policy
    skill_service.replace_governance_bindings.assert_awaited_once_with(
        policy_id=policy.id,
        organization_space_id=organization_space_id,
        intents=intents,
    )
