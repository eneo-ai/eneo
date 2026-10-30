from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.actors.actors.space_actor import SpaceRole
from eneo.flows.api.flow_assistant_router import (
    create_flow_assistant,
    delete_flow_assistant,
    get_flow_assistant,
    update_flow_assistant,
)
from eneo.flows.api.flow_models import (
    FlowAssistantCreateRequest,
    FlowAssistantPatchRequest,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import UnauthorizedException
from eneo.roles.permissions import Permission
from tests.unittests.flows.test_flow_router import (
    _enable_space_access,
    _flow,
    _request,
    _user,
)


def _assistant_context(case):
    container = MagicMock()
    user = _user()
    flow = _flow(uuid4())
    flow.tenant_id = user.tenant_id
    flow.published_version = None
    flow.owner_user_id = user.id if case == "draft_owner" else uuid4()
    if case == "legacy_creator":
        flow.owner_user_id = None
        flow.created_by_user_id = user.id
    container.user.return_value = user
    permissions = [Permission.FLOWS]
    if case == "tenant_admin":
        permissions.append(Permission.ADMIN)
    actor = _enable_space_access(container, user_permissions=permissions)
    actor.get_current_role.return_value = {
        "space_owner": SpaceRole.OWNER,
        "space_admin": SpaceRole.ADMIN,
    }.get(case, SpaceRole.EDITOR)
    assistant = SimpleNamespace(
        id=uuid4(),
        name="Step assistant",
        space_id=flow.space_id,
        type=SimpleNamespace(value="assistant"),
        published=False,
    )
    service = AsyncMock()
    service.get_flow.return_value = flow
    service.create_flow_assistant.return_value = (assistant, [])
    service.update_flow_assistant.return_value = (assistant, [], 8)
    service.get_flow_assistant.return_value = (assistant, [])
    container.flow_service.return_value = service
    container.assistant_assembler.return_value.from_assistant_to_model.return_value = (
        MagicMock(**{"model_dump.return_value": {"id": str(assistant.id)}})
    )
    container.audit_service.return_value = AsyncMock()
    return container, flow, assistant


async def _mutate(operation, container, flow, assistant):
    args = {"id": flow.id, "request": _request(), "container": container}
    if operation == "create":
        return await create_flow_assistant(
            **args, assistant_in=FlowAssistantCreateRequest(name="Step assistant")
        )
    if operation == "update":
        return await update_flow_assistant(
            **args,
            assistant_id=assistant.id,
            assistant_in=FlowAssistantPatchRequest(name="Updated assistant"),
        )
    return await delete_flow_assistant(**args, assistant_id=assistant.id)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["create", "update", "delete"])
@pytest.mark.parametrize(
    "case, allowed",
    [
        ("draft_owner", True),
        ("legacy_creator", True),
        ("tenant_admin", True),
        ("space_owner", True),
        ("space_editor", False),
        ("space_admin", False),
    ],
)
async def test_assistant_mutation_cannot_bypass_the_draft_owner_rule(
    operation, case, allowed
):
    # Mutant: authorize assistant writes on space edit permission alone.
    container, flow, assistant = _assistant_context(case)
    service = container.flow_service.return_value
    if allowed:
        await _mutate(operation, container, flow, assistant)
        getattr(service, f"{operation}_flow_assistant").assert_awaited_once()
    else:
        with pytest.raises(UnauthorizedException) as exc:
            await _mutate(operation, container, flow, assistant)
        assert exc.value.code == FlowApiErrorCode.OWNER_REQUIRED.value
        for method in (
            service.create_flow_assistant,
            service.update_flow_assistant,
            service.delete_flow_assistant,
        ):
            method.assert_not_awaited()
        container.audit_service.return_value.log.assert_not_awaited()
        container.audit_service.return_value.log_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_reading_an_assistant_does_not_inherit_the_mutation_owner_rule():
    # Mutant: impose draft ownership on the existing editor read endpoint.
    container, flow, assistant = _assistant_context("space_editor")
    await get_flow_assistant(
        id=flow.id,
        assistant_id=assistant.id,
        request=_request(),
        container=container,
    )
    container.flow_service.return_value.get_flow_assistant.assert_awaited_once_with(
        flow_id=flow.id,
        assistant_id=assistant.id,
    )
