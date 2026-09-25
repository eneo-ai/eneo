from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request

from eneo.governance_policy.domain.governance_policy import (
    GovernancePolicy,
    PolicyScope,
)
from eneo.governance_policy.presentation.governance_policy_models import (
    FilePolicyInput,
    GovernancePolicyUpdate,
    McpRestrictionInput,
    ModelsRestrictionInput,
    ReasoningPolicyInput,
    SkillsPolicyInput,
)
from eneo.governance_policy.presentation.governance_policy_router import (
    _policy_changes,
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


async def test_mcp_only_update_revalidates_personal_skill_activation():
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

    assistant_service.assert_personal_default_governance_context_fit.assert_awaited_once()


async def test_file_policy_update_forwards_inline_flag_and_skips_context_fit():
    # Message uploads are not part of the persistent baseline the fit gate
    # checks, so the file policy never triggers that validation.
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
    container = MagicMock()
    container.governance_policy_service.return_value = service
    container.governance_policy_assembler.return_value = MagicMock()
    container.assistant_service.return_value = assistant_service

    await update_governance_policy(
        payload=GovernancePolicyUpdate(
            file_policy=FilePolicyInput(inline_file_text=False)
        ),
        request=_session_request(),
        container=container,
    )

    assert service.update_policy.await_args.kwargs["inline_file_text"] is False
    assistant_service.assert_personal_default_governance_context_fit.assert_not_awaited()


def test_policy_changes_records_file_policy_transitions():
    before = GovernancePolicy(
        id=uuid4(), tenant_id=uuid4(), scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT
    )
    after = GovernancePolicy(
        id=before.id,
        tenant_id=before.tenant_id,
        scope=PolicyScope.PERSONAL_DEFAULT_ASSISTANT,
        inline_file_text=False,
    )

    changes = _policy_changes(before, after, before_skills=[], after_skills=[])

    assert changes == {"inline_file_text": {"old": None, "new": False}}


async def test_reasoning_only_update_skips_unrelated_context_fit_validation():
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
    container = MagicMock()
    container.governance_policy_service.return_value = service
    container.governance_policy_assembler.return_value = MagicMock()
    container.assistant_service.return_value = assistant_service

    await update_governance_policy(
        payload=GovernancePolicyUpdate(
            reasoning_policy=ReasoningPolicyInput(
                default_effort=None,
                allow_user_override=True,
            )
        ),
        request=_session_request(),
        container=container,
    )

    assistant_service.assert_personal_default_governance_context_fit.assert_not_awaited()
