import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from eneo.governance_policy.application.effective_config_service import (
    EffectiveConfigService,
)
from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyMcpServer,
    PolicyScope,
)
from eneo.skills.domain.skill import ResolvedSkillBinding, SkillBindingSource


async def test_resolve_for_filters_disabled_mcp_servers_before_resolver():
    tenant_id = uuid4()
    enabled_server_id = uuid4()
    disabled_server_id = uuid4()

    policy = GovernancePolicy(
        id=uuid4(), tenant_id=tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )
    policy.set_mcp_restriction(
        enabled=True,
        servers=[
            PolicyMcpServer(mcp_server_id=enabled_server_id),
            PolicyMcpServer(mcp_server_id=disabled_server_id),
        ],
    )

    service = EffectiveConfigService(
        user=SimpleNamespace(tenant_id=tenant_id),
        policy_repo=AsyncMock(get_by_tenant=AsyncMock(return_value=policy)),
        prompt_library_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(
            get_available_completion_models=AsyncMock(return_value=[])
        ),
        mcp_server_settings_service=AsyncMock(
            get_available_mcp_servers=AsyncMock(
                return_value=[
                    SimpleNamespace(
                        id=enabled_server_id,
                        is_enabled=True,
                    ),
                    SimpleNamespace(
                        id=disabled_server_id,
                        is_enabled=False,
                    ),
                ]
            )
        ),
        skill_repo=AsyncMock(list_policy_bindings=AsyncMock(return_value=[])),
    )

    cfg = await service.resolve_for(
        SimpleNamespace(is_default=True), space_is_personal=True
    )

    assert cfg.mcp_enforced is True
    assert [server.id for server in cfg.available_mcp_servers] == [enabled_server_id]


async def test_resolve_for_all_restrictions_disabled_skips_catalog_fetches():
    # An all-disabled policy row exists for any tenant whose admin merely opened
    # the config page. The resolver never reads the catalogs in that case, so we
    # must not pay the full-table scans on every chat/preflight/space read.
    tenant_id = uuid4()
    policy = GovernancePolicy(
        id=uuid4(), tenant_id=tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )

    completion_model_crud_service = AsyncMock(
        get_available_completion_models=AsyncMock(return_value=[])
    )
    mcp_server_settings_service = AsyncMock(
        get_available_mcp_servers=AsyncMock(return_value=[])
    )
    prompt_library_repo = AsyncMock()

    service = EffectiveConfigService(
        user=SimpleNamespace(tenant_id=tenant_id),
        policy_repo=AsyncMock(get_by_tenant=AsyncMock(return_value=policy)),
        prompt_library_repo=prompt_library_repo,
        completion_model_crud_service=completion_model_crud_service,
        mcp_server_settings_service=mcp_server_settings_service,
        skill_repo=AsyncMock(list_policy_bindings=AsyncMock(return_value=[])),
    )

    cfg = await service.resolve_for(
        SimpleNamespace(is_default=True), space_is_personal=True
    )

    assert cfg.models_enforced is False
    assert cfg.mcp_enforced is False
    completion_model_crud_service.get_available_completion_models.assert_not_called()
    mcp_server_settings_service.get_available_mcp_servers.assert_not_called()
    prompt_library_repo.get.assert_not_called()


async def test_resolve_for_non_personal_space_short_circuits_before_repos():
    policy_repo = AsyncMock()
    service = EffectiveConfigService(
        user=SimpleNamespace(tenant_id=uuid4()),
        policy_repo=policy_repo,
        prompt_library_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        mcp_server_settings_service=AsyncMock(),
        skill_repo=AsyncMock(list_policy_bindings=AsyncMock(return_value=[])),
    )

    cfg = await service.resolve_for(
        SimpleNamespace(is_default=True), space_is_personal=False
    )

    assert cfg.models_enforced is False
    assert cfg.mcp_enforced is False
    policy_repo.get_by_tenant.assert_not_called()


async def test_resolve_for_loads_exact_governance_skill_revisions():
    tenant_id = uuid4()
    policy = GovernancePolicy(
        id=uuid4(), tenant_id=tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )
    binding = ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=uuid4(),
        slug="payroll",
        revision_number=3,
        current_revision_number=3,
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the payroll handbook.",
        content_digest="a" * 64,
        position=0,
        source=SkillBindingSource.ORGANIZATION,
    )
    skill_repo = AsyncMock(list_policy_bindings=AsyncMock(return_value=[binding]))
    service = EffectiveConfigService(
        user=SimpleNamespace(tenant_id=tenant_id),
        policy_repo=AsyncMock(get_by_tenant=AsyncMock(return_value=policy)),
        prompt_library_repo=AsyncMock(),
        completion_model_crud_service=AsyncMock(),
        mcp_server_settings_service=AsyncMock(),
        skill_repo=skill_repo,
    )

    cfg = await service.resolve_for(
        SimpleNamespace(is_default=True), space_is_personal=True
    )

    assert cfg.governance_skill_bindings == (binding,)
    skill_repo.list_policy_bindings.assert_awaited_once_with(policy_id=policy.id)


async def test_resolve_for_does_not_overlap_request_scoped_repository_calls():
    tenant_id = uuid4()
    prompt_id = uuid4()
    policy = GovernancePolicy(
        id=uuid4(), tenant_id=tenant_id, scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )
    policy.set_prompt_enforcement(enabled=True, prompt_library_id=prompt_id)
    binding = ResolvedSkillBinding(
        skill_id=uuid4(),
        skill_revision_id=uuid4(),
        current_revision_id=uuid4(),
        skill_space_id=uuid4(),
        slug="payroll",
        revision_number=1,
        current_revision_number=1,
        display_name="Payroll",
        description="Answers payroll questions",
        instructions="Use the payroll handbook.",
        content_digest="a" * 64,
        position=0,
        source=SkillBindingSource.ORGANIZATION,
    )
    active_calls = 0
    peak_active_calls = 0

    async def guarded_result(value):
        nonlocal active_calls, peak_active_calls
        active_calls += 1
        peak_active_calls = max(peak_active_calls, active_calls)
        await asyncio.sleep(0)
        active_calls -= 1
        return value

    async def get_prompt(**_):
        return await guarded_result(SimpleNamespace(text="Enforced prompt"))

    async def list_policy_bindings(**_):
        return await guarded_result([binding])

    service = EffectiveConfigService(
        user=SimpleNamespace(tenant_id=tenant_id),
        policy_repo=AsyncMock(get_by_tenant=AsyncMock(return_value=policy)),
        prompt_library_repo=AsyncMock(get=AsyncMock(side_effect=get_prompt)),
        completion_model_crud_service=AsyncMock(),
        mcp_server_settings_service=AsyncMock(),
        skill_repo=AsyncMock(
            list_policy_bindings=AsyncMock(side_effect=list_policy_bindings)
        ),
    )

    cfg = await service.resolve_for(
        SimpleNamespace(is_default=True), space_is_personal=True
    )

    assert cfg.enforced_prompt_text == "Enforced prompt"
    assert cfg.governance_skill_bindings == (binding,)
    assert peak_active_calls == 1
