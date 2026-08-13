from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.governance_policy.application.governance_policy_service import (
    GovernancePolicyService,
)
from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyCompletionModel,
    PolicyScope,
)
from eneo.main.exceptions import BadRequestException
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


def _reasoning_model(
    *options: str,
    model_id=None,
    provider_id=None,
) -> SimpleNamespace:
    supported = SupportedModelKwargs(
        reasoning_effort=ModelKwargCapability(
            supported=True,
            control="select",
            options=list(options),
        )
    )
    return SimpleNamespace(
        id=model_id or uuid4(),
        provider_id=provider_id,
        can_access=True,
        get_supported_model_kwargs=lambda: supported,
    )


async def test_update_policy_accepts_reasoning_default_supported_by_a_model():
    tenant_id = uuid4()
    policy = GovernancePolicy(
        id=uuid4(),
        tenant_id=tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
    )
    repo = AsyncMock()
    repo.get_by_tenant_for_update.return_value = policy
    repo.save.return_value = policy
    completion_models = AsyncMock()
    completion_models.get_available_completion_models.return_value = [
        _reasoning_model("low", "medium", "high")
    ]
    service = GovernancePolicyService(
        user=_admin(tenant_id),
        repo=repo,
        completion_model_crud_service=completion_models,
        mcp_server_settings_service=AsyncMock(),
        prompt_library_service=AsyncMock(),
        model_provider_repository=AsyncMock(),
        skill_service=AsyncMock(),
        space_service=AsyncMock(),
    )

    result = await service.update_policy(reasoning_policy=("medium", True))

    assert result is policy
    assert policy.default_reasoning_effort == "medium"
    assert policy.allow_user_reasoning_effort is True
    repo.save.assert_awaited_once()


async def test_update_policy_rejects_reasoning_default_unsupported_by_models():
    tenant_id = uuid4()
    policy = GovernancePolicy(
        id=uuid4(),
        tenant_id=tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
    )
    repo = AsyncMock()
    repo.get_by_tenant_for_update.return_value = policy
    completion_models = AsyncMock()
    completion_models.get_available_completion_models.return_value = [
        _reasoning_model("low", "medium", "high")
    ]
    service = GovernancePolicyService(
        user=_admin(tenant_id),
        repo=repo,
        completion_model_crud_service=completion_models,
        mcp_server_settings_service=AsyncMock(),
        prompt_library_service=AsyncMock(),
        model_provider_repository=AsyncMock(),
        skill_service=AsyncMock(),
        space_service=AsyncMock(),
    )

    with pytest.raises(
        BadRequestException,
        match="not supported by an allowed model",
    ):
        await service.update_policy(reasoning_policy=("max", False))

    repo.save.assert_not_awaited()


async def test_update_policy_rejects_reasoning_default_excluded_by_same_update():
    tenant_id = uuid4()
    allowed_model = _reasoning_model("low")
    excluded_model = _reasoning_model("high")
    policy = GovernancePolicy(
        id=uuid4(),
        tenant_id=tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
    )
    repo = AsyncMock()
    repo.get_by_tenant_for_update.return_value = policy
    completion_models = AsyncMock()
    completion_models.get_available_completion_models.return_value = [
        allowed_model,
        excluded_model,
    ]
    service = GovernancePolicyService(
        user=_admin(tenant_id),
        repo=repo,
        completion_model_crud_service=completion_models,
        mcp_server_settings_service=AsyncMock(),
        prompt_library_service=AsyncMock(),
        model_provider_repository=AsyncMock(),
        skill_service=AsyncMock(),
        space_service=AsyncMock(),
    )

    with pytest.raises(
        BadRequestException,
        match="not supported by an allowed model",
    ):
        await service.update_policy(
            models_restriction=(
                True,
                [PolicyCompletionModel(allowed_model.id)],
                [],
            ),
            reasoning_policy=("high", False),
        )

    repo.save.assert_not_awaited()


async def test_update_policy_rejects_model_narrowing_that_excludes_reasoning_default():
    tenant_id = uuid4()
    allowed_model = _reasoning_model("low")
    excluded_model = _reasoning_model("high")
    policy = GovernancePolicy(
        id=uuid4(),
        tenant_id=tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
        reasoning_policy_configured=True,
        default_reasoning_effort="high",
    )
    repo = AsyncMock()
    repo.get_by_tenant_for_update.return_value = policy
    completion_models = AsyncMock()
    completion_models.get_available_completion_models.return_value = [
        allowed_model,
        excluded_model,
    ]
    service = GovernancePolicyService(
        user=_admin(tenant_id),
        repo=repo,
        completion_model_crud_service=completion_models,
        mcp_server_settings_service=AsyncMock(),
        prompt_library_service=AsyncMock(),
        model_provider_repository=AsyncMock(),
        skill_service=AsyncMock(),
        space_service=AsyncMock(),
    )

    with pytest.raises(
        BadRequestException,
        match="not supported by an allowed model",
    ):
        await service.update_policy(
            models_restriction=(
                True,
                [PolicyCompletionModel(allowed_model.id)],
                [],
            )
        )

    repo.save.assert_not_awaited()


async def test_update_policy_accepts_reasoning_default_supported_by_allowed_model():
    tenant_id = uuid4()
    allowed_model = _reasoning_model("low")
    excluded_model = _reasoning_model("high")
    policy = GovernancePolicy(
        id=uuid4(),
        tenant_id=tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
    )
    repo = AsyncMock()
    repo.get_by_tenant_for_update.return_value = policy
    repo.save.return_value = policy
    completion_models = AsyncMock()
    completion_models.get_available_completion_models.return_value = [
        allowed_model,
        excluded_model,
    ]
    service = GovernancePolicyService(
        user=_admin(tenant_id),
        repo=repo,
        completion_model_crud_service=completion_models,
        mcp_server_settings_service=AsyncMock(),
        prompt_library_service=AsyncMock(),
        model_provider_repository=AsyncMock(),
        skill_service=AsyncMock(),
        space_service=AsyncMock(),
    )

    result = await service.update_policy(
        models_restriction=(
            True,
            [PolicyCompletionModel(allowed_model.id)],
            [],
        ),
        reasoning_policy=("low", False),
    )

    assert result.default_reasoning_effort == "low"
    repo.save.assert_awaited_once()


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
