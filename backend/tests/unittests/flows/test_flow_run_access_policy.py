from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.authentication.auth_models import (
    ResourcePermissionLevel,
    ResourcePermissions,
)
from intric.authentication.principal_types import PrincipalType
from intric.flows.application.flow_run_access_policy import (
    FlowRunAccessKind,
    FlowRunAccessPolicy,
)
from intric.flows.flow import FlowRun, FlowRunStatus
from intric.main.exceptions import UnauthorizedException
from intric.roles.permissions import Permission


def _run(user, flow_id) -> FlowRun:
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=1,
        principal_type=PrincipalType.USER.value,
        principal_user_id=user.id,
        principal_api_key_id=None,
        tenant_id=user.tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _service_key_user(user):
    return user.model_copy(
        update={
            "active_api_key": SimpleNamespace(
                id=uuid4(),
                ownership="service",
                resource_permissions=None,
            ),
        }
    )


def _policy(user, *, flow_run_repo: AsyncMock) -> FlowRunAccessPolicy:
    return FlowRunAccessPolicy(
        user=user,
        flow_repo=AsyncMock(),
        flow_run_repo=flow_run_repo,
    )


def _policy_with_space(
    user,
    *,
    flow_repo: AsyncMock,
    flow_run_repo: AsyncMock,
    role: str,
    security_level: int = 0,
) -> FlowRunAccessPolicy:
    space = SimpleNamespace(
        id=uuid4(),
        security_classification=SimpleNamespace(security_level=security_level),
    )
    flow = SimpleNamespace(
        id=uuid4(),
        tenant_id=user.tenant_id,
        space_id=space.id,
        metadata_json=None,
    )
    space_service = AsyncMock()
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = SimpleNamespace(
        get_current_role=lambda: role
    )
    flow_repo.get.return_value = flow
    space_service.get_space.return_value = space
    return FlowRunAccessPolicy(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        space_service=space_service,
        actor_manager=actor_manager,
    )


@pytest.mark.asyncio
async def test_load_run_allows_owner_content_access(user):
    flow_id = uuid4()
    run = _run(user, flow_id)
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    result = await policy.load_run(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="content",
    )

    assert result == run
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        tenant_id=user.tenant_id,
        flow_id=flow_id,
    )


@pytest.mark.asyncio
async def test_load_run_allows_owner_rerun_access(user):
    flow_id = uuid4()
    run = _run(user, flow_id)
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    result = await policy.load_run(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="rerun",
    )

    assert result == run


@pytest.mark.asyncio
async def test_load_run_rejects_cross_tenant_run(user):
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(update={"tenant_id": uuid4()})
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind="content",
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "tenant_isolation"}


@pytest.mark.asyncio
async def test_load_run_rejects_other_users_run_for_non_admin(user):
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(update={"principal_user_id": uuid4()})
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind="content",
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_owner"}


@pytest.mark.asyncio
async def test_load_run_allows_tenant_admin_for_other_users_run(user):
    admin_user = user.model_copy(
        update={"roles": [SimpleNamespace(permissions=[Permission.ADMIN])]}
    )
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(update={"principal_user_id": uuid4()})
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(admin_user, flow_run_repo=flow_run_repo)

    result = await policy.load_run(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="content",
    )

    assert result == run


@pytest.mark.asyncio
async def test_service_key_access_requires_matching_run_principal(user):
    service_user = _service_key_user(user)
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(
        update={
            "user_id": None,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_api_key_id": uuid4(),
        }
    )
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(service_user, flow_run_repo=flow_run_repo)

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind="content",
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_principal"}


@pytest.mark.asyncio
async def test_service_key_evidence_view_uses_key_capability(user):
    service_user = _service_key_user(user)
    service_user.active_api_key.resource_permissions = ResourcePermissions(
        flow_evidence=ResourcePermissionLevel.READ
    )
    flow_id = uuid4()
    run = _run(user, flow_id).model_copy(
        update={
            "user_id": None,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_api_key_id": service_user.active_api_key.id,
        }
    )
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(service_user, flow_run_repo=flow_run_repo)

    result = await policy.load_run(
        run_id=run.id,
        flow_id=flow_id,
        access_kind="evidence_view",
    )

    assert result == run


@pytest.mark.asyncio
async def test_can_list_all_runs_in_flow_uses_space_role(user):
    flow_repo = AsyncMock()
    flow_run_repo = AsyncMock()
    admin_policy = _policy_with_space(
        user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        role="admin",
    )
    viewer_policy = _policy_with_space(
        user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        role="viewer",
    )

    assert await admin_policy.can_list_all_runs_in_flow(flow_id=uuid4()) is True
    assert await viewer_policy.can_list_all_runs_in_flow(flow_id=uuid4()) is False


@pytest.mark.asyncio
async def test_load_space_access_returns_none_without_space_dependencies(user):
    flow_run_repo = AsyncMock()
    policy = _policy(user, flow_run_repo=flow_run_repo)

    assert await policy.load_space_access(flow_id=uuid4()) == (None, 0)


@pytest.mark.asyncio
async def test_load_run_rejects_sensitive_flow_export_when_policy_disabled(user):
    flow_id = uuid4()
    run = _run(user, flow_id)
    flow_repo = AsyncMock()
    flow_repo.get.return_value = SimpleNamespace(
        id=flow_id,
        tenant_id=user.tenant_id,
        space_id=uuid4(),
        metadata_json={"care_data_policy": {"sensitive": True}},
    )
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = FlowRunAccessPolicy(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind="evidence_export_redacted",
        )

    assert exc_info.value.code == "flow_run_evidence_forbidden"
    assert exc_info.value.context == {"auth_layer": "flow_runtime_policy"}


@pytest.mark.asyncio
async def test_load_run_fails_closed_on_unknown_access_kind(user):
    flow_id = uuid4()
    run = _run(user, flow_id)
    flow_run_repo = AsyncMock()
    flow_run_repo.get.return_value = run
    policy = _policy(user, flow_run_repo=flow_run_repo)

    with pytest.raises(UnauthorizedException) as exc_info:
        await policy.load_run(
            run_id=run.id,
            flow_id=flow_id,
            access_kind=cast(FlowRunAccessKind, "unknown_access_kind"),
        )

    assert exc_info.value.code == "flow_run_access_denied"
    assert exc_info.value.context == {"auth_layer": "flow_run_access_kind"}
