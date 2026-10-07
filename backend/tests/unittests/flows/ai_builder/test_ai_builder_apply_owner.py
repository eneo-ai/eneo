"""Mutant: Builder apply omits the ordinary draft-owner gate before its writer."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from eneo.actors.actor_factory import ActorFactory
from eneo.actors.actor_manager import ActorManager
from eneo.flows.ai_builder.ai_builder_api_models import ApplyResultResponse
from eneo.flows.ai_builder.ai_builder_domain_models import (
    BuilderSession,
    SessionStatus,
    TargetKind,
)
from eneo.flows.api.flow_ai_builder_router import (
    AIBuilderEnvelopedError,
    ai_builder_enveloped_error_handler,
    router,
)
from eneo.flows.domain.flow import Flow
from eneo.roles.permissions import Permission
from eneo.spaces.api.space_models import SpaceMember
from eneo.spaces.space import Space
from tests.unit.api_key_test_utils import flatten_routes


@pytest.mark.parametrize(
    "role,owns_draft,legacy_creator,tenant_admin,target_kind,status",
    [
        ("editor", False, False, False, TargetKind.EDIT, 403),
        ("admin", False, False, False, TargetKind.EDIT, 403),
        ("editor", True, False, False, TargetKind.EDIT, 200),
        ("editor", False, True, False, TargetKind.EDIT, 200),
        ("editor", False, False, True, TargetKind.EDIT, 200),
        ("owner", False, False, False, TargetKind.EDIT, 200),
        ("editor", False, False, False, TargetKind.CREATE, 200),
    ],
    ids=[
        "other-editor",
        "other-space-admin",
        "draft-owner",
        "legacy-creator",
        "tenant-admin",
        "space-owner",
        "create",
    ],
)
def test_builder_apply_enforces_draft_ownership_before_mutation(
    role, owns_draft, legacy_creator, tenant_admin, target_kind, status
):
    permissions = [Permission.FLOWS, Permission.FLOWS_AI_BUILDER_REVIEW]
    if tenant_admin:
        permissions.append(Permission.ADMIN)
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=permissions,
        active_api_key=None,
        user_groups_ids=set(),
        email="dummy@example.com",
        username="dummy-editor",
    )
    space = Space(
        id=uuid4(),
        tenant_id=user.tenant_id,
        tenant_space_id=uuid4(),
        user_id=user.id if role == "owner" else None,
        name="Dummy space",
        description=None,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={
            user.id: SpaceMember(
                id=user.id, email=user.email, role="editor" if role == "owner" else role
            )
        },
    )
    flow = Flow(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=space.id,
        name="Owner draft",
        owner_user_id=user.id if owns_draft else None if legacy_creator else uuid4(),
        created_by_user_id=user.id if legacy_creator else uuid4(),
    )
    container = MagicMock()
    container.user.return_value = user
    container.actor_manager.return_value = ActorManager(
        user=user, factory=ActorFactory()
    )
    container.space_service.return_value = AsyncMock(
        get_space=AsyncMock(return_value=space)
    )
    container.flow_service.return_value = AsyncMock(
        get_flow=AsyncMock(return_value=flow)
    )
    audit = container.audit_service.return_value = AsyncMock()
    session = BuilderSession(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=space.id,
        flow_id=flow.id if target_kind is TargetKind.EDIT else None,
        target_kind=target_kind,
        status=SessionStatus.AWAITING_APPROVAL,
        actor_user_id=user.id,
    )
    plan = SimpleNamespace(id=uuid4(), session_id=session.id)
    service = AsyncMock(
        get_plan=AsyncMock(return_value=plan),
        get_session=AsyncMock(return_value=session),
    )

    async def write_dummy_draft(**kwargs):
        flow.name = "Applied dummy plan"
        return ApplyResultResponse(
            flow_id=flow.id,
            flow_name=flow.name,
            steps_created=0,
            steps_updated=1,
            steps_removed=0,
        )

    service.apply_plan.side_effect = write_dummy_draft
    container.ai_builder_service.return_value = service
    app = FastAPI()
    app.add_exception_handler(
        AIBuilderEnvelopedError, ai_builder_enveloped_error_handler
    )
    app.include_router(router)

    async def override_container():
        return container

    for routed in flatten_routes(list(app.routes)):
        if (
            isinstance(routed.route, APIRoute)
            and routed.path == "/ai-builder/plans/{plan_id}/apply"
        ):
            for dependency in routed.dependant.dependencies:
                if dependency.name == "container":
                    app.dependency_overrides[dependency.call] = override_container
    assert app.dependency_overrides
    with TestClient(app) as client:
        response = client.post(
            f"/ai-builder/plans/{plan.id}/apply", json={"expected_revision": 0}
        )

    assert response.status_code == status
    if status == 403:
        assert response.json()["code"] == "flow_owner_required"
        assert response.json()["category"] == "unauthorized"
        assert response.json()["schema_version"] == 2
        assert response.json()["details"] == {"auth_layer": "flow_owner"}
        assert flow.name == "Owner draft"
        service.apply_plan.assert_not_awaited()
        audit.log.assert_not_awaited()
    else:
        assert flow.name == "Applied dummy plan"
        assert response.json()["flow_id"] == str(flow.id)
        service.apply_plan.assert_awaited_once_with(
            plan_id=plan.id, expected_revision=0
        )
        audit.log.assert_awaited_once()
