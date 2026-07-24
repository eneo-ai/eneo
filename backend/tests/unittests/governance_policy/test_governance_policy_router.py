from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyScope,
)
from eneo.governance_policy.presentation.governance_policy_models import (
    GovernancePolicyUpdate,
    McpRestrictionInput,
    ModelsRestrictionInput,
    SkillsPolicyInput,
)
from eneo.governance_policy.presentation.governance_policy_router import (
    update_governance_policy,
)


def _api_key_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/admin/governance-policy/",
            "headers": [],
        }
    )
    request.state.api_key = MagicMock()
    return request


def _session_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "PUT",
            "path": "/admin/governance-policy/",
            "headers": [],
        }
    )


async def test_governance_router_rejects_api_key_skill_facet_before_service_call():
    container = MagicMock()

    with pytest.raises(HTTPException) as exc_info:
        await update_governance_policy(
            payload=GovernancePolicyUpdate(skills=SkillsPolicyInput(bindings=[])),
            request=_api_key_request(),
            container=container,
        )

    assert exc_info.value.status_code == 403
    assert "session token" in str(exc_info.value.detail)
    container.governance_policy_service.assert_not_called()


async def test_governance_router_keeps_api_key_access_to_non_skill_facets():
    service = MagicMock()
    service.get_policy_for_update = AsyncMock(
        side_effect=RuntimeError("non-Skill update reached the existing service")
    )
    container = MagicMock()
    container.governance_policy_service.return_value = service

    with pytest.raises(RuntimeError, match="non-Skill update reached"):
        await update_governance_policy(
            payload=GovernancePolicyUpdate(
                models_restriction=ModelsRestrictionInput(enabled=False)
            ),
            request=_api_key_request(),
            container=container,
        )

    service.get_policy_for_update.assert_awaited_once()


async def test_mcp_only_update_skips_personal_baseline_scan():
    policy = GovernancePolicy(
        id=uuid4(),
        tenant_id=uuid4(),
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
    )
    service = MagicMock()
    service.get_policy_for_update = AsyncMock(return_value=policy)
    service.get_skill_bindings = AsyncMock(return_value=[])
    service.get_skill_binding_projections = AsyncMock(return_value=[])
    service.update_policy = AsyncMock(return_value=policy)
    assistant_service = MagicMock()
    assistant_service.assert_personal_default_governance_context_fit = AsyncMock()
    assembler = MagicMock()
    container = MagicMock()
    container.governance_policy_service.return_value = service
    container.governance_policy_assembler.return_value = assembler
    container.assistant_service.return_value = assistant_service

    await update_governance_policy(
        payload=GovernancePolicyUpdate(
            mcp_restriction=McpRestrictionInput(enabled=False)
        ),
        request=_session_request(),
        container=container,
    )

    assistant_service.assert_personal_default_governance_context_fit.assert_not_awaited()
