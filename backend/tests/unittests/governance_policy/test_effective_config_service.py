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
    )

    cfg = await service.resolve_for(
        SimpleNamespace(is_default=True), space_is_personal=False
    )

    assert cfg.models_enforced is False
    assert cfg.mcp_enforced is False
    policy_repo.get_by_tenant.assert_not_called()
