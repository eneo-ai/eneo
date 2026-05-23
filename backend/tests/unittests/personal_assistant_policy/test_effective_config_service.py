from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from intric.personal_assistant_policy.application.effective_config_service import (
    EffectiveConfigService,
)
from intric.personal_assistant_policy.domain.personal_assistant_policy import (
    PersonalAssistantPolicy,
)


async def test_resolve_for_filters_disabled_mcp_servers_before_resolver():
    tenant_id = uuid4()
    enabled_server_id = uuid4()
    disabled_server_id = uuid4()

    policy = PersonalAssistantPolicy(id=uuid4(), tenant_id=tenant_id)
    policy.set_mcp_restriction(
        enabled=True, ids=[enabled_server_id, disabled_server_id]
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

    cfg = await service.resolve_for(SimpleNamespace(is_default=True))

    assert cfg.mcp_enforced is True
    assert [server.id for server in cfg.available_mcp_servers] == [enabled_server_id]
