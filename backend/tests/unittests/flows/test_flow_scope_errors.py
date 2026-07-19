from __future__ import annotations

from datetime import (
    datetime,
    timezone,
)
from types import SimpleNamespace
from unittest.mock import (
    AsyncMock,
    MagicMock,
)
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from eneo.actors.actors.space_actor import SpaceRole
from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.flows.api import flow_access_context as flow_access_context_module
from eneo.flows.api.flow_authoring_router import (
    create_flow,
    get_published_flow_runtime,
)
from eneo.flows.api.flow_authoring_router import (
    delete_flow as definition_delete_flow,
)
from eneo.flows.api.flow_authoring_router import (
    get_flow as definition_get_flow,
)
from eneo.flows.api.flow_authoring_router import (
    list_flows as definition_list_flows,
)
from eneo.flows.api.flow_authoring_router import (
    publish_flow as definition_publish_flow,
)
from eneo.flows.api.flow_authoring_router import (
    unpublish_flow as definition_unpublish_flow,
)
from eneo.flows.api.flow_authoring_router import (
    update_flow as definition_update_flow,
)
from eneo.flows.api.flow_models import (
    FlowCreateRequest,
    FlowFinalOutputContractPublic,
    FlowOutputDelivery,
    FlowRunCreateRequest,
    FlowRunStepRerunRequest,
    FlowStepCreateRequest,
    FlowUpdateRequest,
)
from eneo.flows.api.flow_run_evidence_router import get_flow_run_evidence
from eneo.flows.api.flow_run_execution_router import (
    cancel_flow_run,
    create_flow_run,
    get_flow_run,
    list_flow_runs,
    redispatch_flow_run,
    rerun_flow_run_step,
)
from eneo.flows.api.flow_run_steps_router import get_flow_graph
from eneo.flows.application.flow_run_service import (
    FlowRunPageWithResultFilesAndTokenUsage,
    FlowRunWithResultFilesAndTokenUsage,
)
from eneo.flows.enums import (
    FlowOutputMode,
    FlowOutputType,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.main.exceptions import (
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from tests.unittests.flows.test_flow_router import (
    _assert_scope_mismatch,
    _enable_explicit_transaction,
    _enable_space_access,
    _flow,
    _request,
    _rerun_result,
    _run,
    _service_key,
)


@pytest.mark.asyncio
async def test_get_flow_graph_rejects_scope_mismatch(monkeypatch):
    container = MagicMock()
    container.flow_service.return_value = AsyncMock()
    container.flow_run_service.return_value = AsyncMock()
    container.flow_version_repo.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    flow_id = uuid4()

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=uuid4()),
    )

    with pytest.raises(UnauthorizedException) as exc:
        await get_flow_graph(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_id=None,
            container=container,
        )

    _assert_scope_mismatch(
        exc,
        message="API key space scope does not match requested flow.",
    )
    container.flow_run_service.return_value.get_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_flows_rejects_user_without_flow_roles():
    container = MagicMock()
    flow_service = AsyncMock()
    container.flow_service.return_value = flow_service
    _enable_space_access(container, user_permissions=[])

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_list_flows(
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    assert exc_info.value.code == "insufficient_tenant_permission"
    flow_service.list_flows.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_run_rejects_user_without_run_permission():
    container = MagicMock()
    flow_service = AsyncMock()
    flow_run_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = flow_run_service
    _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])

    flow = _flow(uuid4())
    flow_service.get_flow.return_value = flow

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow_run(
            id=flow.id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_in=FlowRunCreateRequest(input_payload_json={}),
            background_tasks=BackgroundTasks(),
            container=container,
        )

    assert exc_info.value.code == "insufficient_tenant_permission"
    flow_run_service.create_run.assert_not_awaited()


@pytest.mark.parametrize(
    ("permissions", "expected_code"),
    [
        ([Permission.FLOWS_VIEW], "insufficient_tenant_permission"),
        ([Permission.FLOWS_RUN], "insufficient_tenant_permission"),
        ([], "insufficient_tenant_permission"),
    ],
)
@pytest.mark.asyncio
async def test_rerun_flow_run_step_permission_matrix_denies_non_managers(
    monkeypatch,
    permissions,
    expected_code,
):
    container = MagicMock()
    flow_id = uuid4()
    step_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), permissions=permissions)
    flow = _flow(flow_id)
    flow.owner_user_id = user.id
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    rerun_service = AsyncMock()
    container.flow_service.return_value = flow_service
    container.flow_run_rerun_service.return_value = rerun_service
    container.user.return_value = user
    _enable_space_access(container, user_permissions=permissions)
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await rerun_flow_run_step(
            id=flow_id,
            run_id=uuid4(),
            step_id=step_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            rerun_in=FlowRunStepRerunRequest(
                expected_run_revision=1,
                reason="Ownership alone is not enough",
            ),
            background_tasks=BackgroundTasks(),
            container=container,
        )

    assert exc_info.value.code == expected_code
    rerun_service.rerun_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_flow_run_step_permission_matrix_allows_service_key_principal(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    run_id = uuid4()
    step_id = uuid4()
    user = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS_MANAGE],
        active_api_key=_service_key(),
    )
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id).model_copy(
        update={
            "id": run_id,
            "output_payload_json": {"text": "Rerun finished"},
        }
    )
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    rerun_service = AsyncMock()
    rerun_service.rerun_step.return_value = _rerun_result(
        run,
        step_id,
        created=False,
    )
    run_service = AsyncMock()
    run_service.enrich_run_with_result_files_and_token_usage.return_value = (
        FlowRunWithResultFilesAndTokenUsage(
            run=run,
            result_files=(),
            token_usage=None,
            final_output=FlowFinalOutputContractPublic(
                step_id=step_id,
                step_order=1,
                output_type=FlowOutputType.TEXT,
                output_mode=FlowOutputMode.PASS_THROUGH,
                delivery=FlowOutputDelivery.PAYLOAD,
            ),
        )
    )
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = run_service
    container.flow_run_rerun_service.return_value = rerun_service
    container.audit_service.return_value = AsyncMock()
    container.user.return_value = user
    _enable_space_access(container, user_permissions=[Permission.FLOWS_MANAGE])
    _enable_explicit_transaction(container)
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    response = await rerun_flow_run_step(
        id=flow_id,
        run_id=run_id,
        step_id=step_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        rerun_in=FlowRunStepRerunRequest(
            expected_run_revision=1,
            reason="Service keys can request own-run reruns",
        ),
        background_tasks=BackgroundTasks(),
        container=container,
    )

    assert response.run.id == run_id
    rerun_service.rerun_step.assert_awaited_once_with(
        flow_id=flow_id,
        run_id=run_id,
        rerun_step_id=step_id,
        expected_run_revision=1,
        reason="Service keys can request own-run reruns",
        input_payload_json=None,
        step_inputs=None,
    )
    container.audit_service.return_value.log_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_flow_run_rejects_scope_mismatch(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run_service = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    _enable_explicit_transaction(container)

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=uuid4()),
    )

    with pytest.raises(UnauthorizedException) as exc:
        await create_flow_run(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_in=FlowRunCreateRequest(input_payload_json={"x": 1}),
            background_tasks=BackgroundTasks(),
            container=container,
        )

    _assert_scope_mismatch(
        exc,
        message="API key space scope does not match requested flow.",
    )
    run_service.create_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_flow_rejects_space_scope_mismatch(monkeypatch):
    container = MagicMock()
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    container.audit_service.return_value = AsyncMock()

    allowed_space_id = uuid4()
    target_space_id = uuid4()
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=allowed_space_id),
    )

    with pytest.raises(UnauthorizedException) as exc:
        await create_flow(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_in=FlowCreateRequest(
                space_id=target_space_id,
                name="Flow",
                steps=[
                    FlowStepCreateRequest(
                        assistant_id=uuid4(),
                        step_order=1,
                        user_description="Step",
                        input_source="flow_input",
                        input_type="text",
                        output_mode="pass_through",
                        output_type="json",
                    )
                ],
            ),
            container=container,
        )

    _assert_scope_mismatch(
        exc,
        message=(
            f"API key is scoped to space '{allowed_space_id}'. "
            f"Cannot create flow in space '{target_space_id}'."
        ),
    )


@pytest.mark.asyncio
async def test_list_flow_runs_viewer_cannot_read_unpublished_flow(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run_service = AsyncMock()
    container.flow_run_service.return_value = run_service

    flow = _flow(flow_id)
    flow.published_version = None
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )
    actor = _enable_space_access(container)
    actor.can_read_flow.return_value = False

    with pytest.raises(UnauthorizedException) as exc_info:
        await list_flow_runs(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            limit=20,
            offset=0,
            container=container,
        )

    assert exc_info.value.code == "insufficient_space_permission"
    run_service.list_runs_with_result_files_and_token_usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_run_control_endpoints_reject_scope_mismatch(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.get_run.return_value = run
    run_service.cancel_run.return_value = run
    run_service.get_redacted_evidence_bundle.return_value = SimpleNamespace(
        to_dict=lambda: {
            "run": run.model_dump(mode="json"),
            "definition_snapshot": {"steps": []},
            "step_results": [],
            "step_attempts": [],
            "result_files": [],
            "debug_export": {
                "schema_version": "eneo.flow.debug-export.v2",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "run": {
                    "run_id": str(run.id),
                    "flow_id": str(run.flow_id),
                    "flow_version": run.flow_version,
                    "status": run.status.value,
                },
                "definition": {
                    "flow_id": str(run.flow_id),
                    "version": 1,
                    "checksum": "abc",
                    "steps_count": 0,
                },
                "definition_snapshot": {"steps": []},
                "steps": [],
                "security": {
                    "redaction_applied": True,
                    "classification_field": "output_classification_override",
                },
            },
        }
    )
    container.flow_run_service.return_value = run_service
    container.flow_run_evidence_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.flow_execution_backend.return_value = MagicMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    container.audit_service.return_value = AsyncMock()
    _enable_explicit_transaction(container)

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=uuid4()),
    )

    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(UnauthorizedException) as cancel_exc:
        await cancel_flow_run(
            id=flow_id,
            run_id=run.id,
            request=request,
            container=container,
        )
    _assert_scope_mismatch(
        cancel_exc,
        message="API key space scope does not match requested flow.",
    )
    with pytest.raises(UnauthorizedException) as redispatch_exc:
        await redispatch_flow_run(
            id=flow_id,
            run_id=run.id,
            request=request,
            container=container,
        )
    _assert_scope_mismatch(
        redispatch_exc,
        message="API key space scope does not match requested flow.",
    )
    with pytest.raises(UnauthorizedException) as evidence_exc:
        await get_flow_run_evidence(
            id=flow_id,
            run_id=run.id,
            request=request,
            container=container,
        )
    _assert_scope_mismatch(
        evidence_exc,
        message="API key space scope does not match requested flow.",
    )

    run_service.cancel_run.assert_not_awaited()
    run_service.get_run.assert_not_awaited()
    run_service.get_redacted_evidence_bundle.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_runtime_endpoints_reject_scope_mismatch(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    run = _run(flow_id=flow_id, tenant_id=uuid4())
    run_service = AsyncMock()
    run_service.list_runs_with_result_files_and_token_usage.return_value = (
        SimpleNamespace(
            items=(SimpleNamespace(run=run, result_files=(), token_usage=None),),
            has_more=False,
        )
    )
    run_service.get_run_with_result_files_and_token_usage.return_value = (
        SimpleNamespace(run=run, result_files=(), token_usage=None)
    )
    run_service.list_step_results.return_value = []
    container.flow_run_service.return_value = run_service
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    wrong_space = uuid4()
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=wrong_space),
    )

    request = SimpleNamespace(state=SimpleNamespace())
    with pytest.raises(UnauthorizedException) as list_exc:
        await list_flow_runs(
            id=flow_id,
            request=request,
            limit=10,
            offset=0,
            container=container,
        )
    with pytest.raises(UnauthorizedException) as get_exc:
        await get_flow_run(
            id=flow_id,
            run_id=run.id,
            request=request,
            container=container,
        )

    _assert_scope_mismatch(
        list_exc,
        message="API key space scope does not match requested flow.",
    )
    _assert_scope_mismatch(
        get_exc,
        message="API key space scope does not match requested flow.",
    )
    run_service.list_runs_with_result_files_and_token_usage.assert_not_awaited()
    run_service.get_run_with_result_files_and_token_usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_flow_rejects_non_member():
    """get_flow returns 403 when user has no space membership."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_read=False)

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_get_flow(id=flow_id, request=_request(), container=container)
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_get_flow_viewer_cannot_read_unpublished():
    """VIEWER cannot see an unpublished flow (published property is False)."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.published_version = None  # unpublished
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service

    # can_read_flow(flow) returns False for unpublished flows for viewers
    actor = _enable_space_access(container, can_read=True)
    actor.can_read_flow.return_value = False

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_get_flow(id=flow_id, request=_request(), container=container)
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_update_flow_rejects_viewer():
    """VIEWER cannot update a flow."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_edit=False)

    from eneo.flows.api.flow_models import FlowUpdateRequest

    update_req = FlowUpdateRequest(name="New Name")

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_update_flow(
            id=flow_id,
            request=_request(),
            flow_in=update_req,
            container=container,
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_update_flow_rejects_same_space_admin_for_other_members_draft():
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.owner_user_id = uuid4()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    actor = _enable_space_access(container, can_edit=True)
    actor.get_current_role.return_value = SpaceRole.ADMIN
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    update_req = FlowUpdateRequest(name="New Name")

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_update_flow(
            id=flow_id,
            request=_request(),
            flow_in=update_req,
            container=container,
        )

    assert exc_info.value.code == FlowApiErrorCode.OWNER_REQUIRED.value


@pytest.mark.asyncio
async def test_delete_flow_rejects_viewer():
    """VIEWER cannot delete a flow."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    _enable_space_access(container, can_delete=False)

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_delete_flow(
            id=flow_id, request=_request(), container=container
        )
    assert exc_info.value.code == "insufficient_space_permission"
    assert exc_info.value.context == {"auth_layer": "space_membership"}


@pytest.mark.asyncio
async def test_delete_flow_rejects_same_space_admin_for_other_members_draft():
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.owner_user_id = uuid4()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    actor = _enable_space_access(container, can_delete=True)
    actor.get_current_role.return_value = SpaceRole.ADMIN
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_delete_flow(
            id=flow_id, request=_request(), container=container
        )

    assert exc_info.value.code == FlowApiErrorCode.OWNER_REQUIRED.value
    assert exc_info.value.context == {"auth_layer": "flow_owner"}


@pytest.mark.asyncio
async def test_publish_flow_rejects_editor_in_personal_space():
    """No PUBLISH in personal space — should be rejected."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_publish=False)

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_publish_flow(
            id=flow_id, request=_request(), container=container
        )
    assert exc_info.value.code == "insufficient_space_permission"
    assert exc_info.value.context == {"auth_layer": "space_membership"}


@pytest.mark.asyncio
async def test_publish_flow_rejects_same_space_admin_for_other_members_draft():
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.owner_user_id = uuid4()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    actor = _enable_space_access(container, can_publish=True)
    actor.get_current_role.return_value = SpaceRole.ADMIN
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_publish_flow(
            id=flow_id, request=_request(), container=container
        )

    assert exc_info.value.code == FlowApiErrorCode.OWNER_REQUIRED.value
    assert exc_info.value.context == {"auth_layer": "flow_owner"}


@pytest.mark.asyncio
async def test_unpublish_flow_rejects_without_publish_permission():
    """User without publish permission cannot unpublish."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_edit=True, can_delete=True, can_publish=False)

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_unpublish_flow(
            id=flow_id, request=_request(), container=container
        )
    assert exc_info.value.code == "insufficient_space_permission"
    assert exc_info.value.context == {"auth_layer": "space_membership"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("route_fn", "build_kwargs"),
    [
        (definition_get_flow, lambda flow_id: {}),
        (
            definition_update_flow,
            lambda _flow_id: {"flow_in": FlowUpdateRequest(name="Scoped update")},
        ),
        (definition_delete_flow, lambda flow_id: {}),
        (definition_publish_flow, lambda flow_id: {}),
        (definition_unpublish_flow, lambda flow_id: {}),
    ],
)
async def test_definition_endpoints_reject_scope_mismatch(
    monkeypatch,
    route_fn,
    build_kwargs,
):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )
    _enable_space_access(container)

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=uuid4()),
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await route_fn(
            id=flow_id,
            request=_request(),
            container=container,
            **build_kwargs(flow_id),
        )

    _assert_scope_mismatch(
        exc_info,
        message="API key space scope does not match requested flow.",
    )


@pytest.mark.asyncio
async def test_list_flows_rejects_non_member(monkeypatch):
    """list_flows returns 403 when user has no space membership."""
    container = MagicMock()
    space_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    _enable_space_access(container, can_read=False)

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_list_flows(
            request=SimpleNamespace(state=SimpleNamespace()),
            space_id=space_id,
            container=container,
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_list_flows_rejects_without_tenant_view_permission(monkeypatch):
    container = MagicMock()
    space_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[],
    )
    _enable_space_access(container, user_permissions=[])

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await definition_list_flows(
            request=SimpleNamespace(state=SimpleNamespace()),
            space_id=space_id,
            container=container,
        )

    assert exc_info.value.code == "insufficient_tenant_permission"


@pytest.mark.asyncio
async def test_get_published_flow_runtime_hides_unpublished_flow(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.published_version = None
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_read=True, user_permissions=[Permission.FLOWS])

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    with pytest.raises(NotFoundException):
        await get_published_flow_runtime(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )


@pytest.mark.asyncio
async def test_get_published_flow_runtime_hides_unpublished_flow_before_read_denial(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.published_version = None
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    actor = _enable_space_access(
        container,
        can_read=False,
        user_permissions=[Permission.FLOWS],
    )

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    with pytest.raises(NotFoundException):
        await get_published_flow_runtime(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )

    actor.can_read_flow.assert_not_called()


@pytest.mark.asyncio
async def test_get_published_flow_runtime_hides_unpublished_flow_for_service_key(
    monkeypatch,
):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow.published_version = None
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=_service_key(),
    )
    _enable_space_access(container, can_read=True, user_permissions=[Permission.FLOWS])

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    with pytest.raises(NotFoundException):
        await get_published_flow_runtime(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            container=container,
        )


@pytest.mark.asyncio
async def test_create_flow_rejects_non_member(monkeypatch):
    """create_flow returns 403 when user cannot create flows in the space."""
    container = MagicMock()
    space_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    _enable_space_access(container, can_create=False)

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    flow_in = FlowCreateRequest(
        space_id=space_id,
        name="Test Flow",
        steps=[
            FlowStepCreateRequest(
                assistant_id=uuid4(),
                step_order=1,
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="json",
            )
        ],
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_in=flow_in,
            container=container,
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_create_flow_rejects_without_tenant_manage_permission(monkeypatch):
    container = MagicMock()
    space_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS_VIEW],
    )
    _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    flow_in = FlowCreateRequest(
        space_id=space_id,
        name="Test Flow",
        steps=[
            FlowStepCreateRequest(
                assistant_id=uuid4(),
                step_order=1,
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="json",
            )
        ],
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow(
            request=SimpleNamespace(state=SimpleNamespace()),
            flow_in=flow_in,
            container=container,
        )

    assert exc_info.value.code == "insufficient_tenant_permission"


@pytest.mark.asyncio
async def test_enforce_flow_scope_rejects_non_member_on_consumer_endpoint(monkeypatch):
    """Consumer endpoint (create_flow_run) returns 403 when user has no space access."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    _enable_space_access(container, can_read=False)

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    run_in = FlowRunCreateRequest(input_payload_json={"test": "value"})

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow_run(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_in=run_in,
            background_tasks=BackgroundTasks(),
            container=container,
        )
    assert exc_info.value.code == "insufficient_space_permission"


@pytest.mark.asyncio
async def test_create_flow_run_rejects_without_tenant_run_permission(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.flow_run_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS_VIEW],
    )
    _enable_space_access(container, user_permissions=[Permission.FLOWS_VIEW])

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )

    run_in = FlowRunCreateRequest(input_payload_json={"test": "value"})

    with pytest.raises(UnauthorizedException) as exc_info:
        await create_flow_run(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            run_in=run_in,
            background_tasks=BackgroundTasks(),
            container=container,
        )

    assert exc_info.value.code == "insufficient_tenant_permission"


@pytest.mark.asyncio
async def test_tenant_scoped_user_api_key_loads_space_membership_check(monkeypatch):
    """Tenant-scoped user-owned API keys should still respect space visibility rules."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=flow.tenant_id).model_copy(
        update={"output_payload_json": {"text": "Finished"}}
    )

    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=SimpleNamespace(ownership="user"),
    )
    _enable_space_access(container)

    run_service = AsyncMock()
    run_service.list_runs_with_result_files_and_token_usage.return_value = (
        FlowRunPageWithResultFilesAndTokenUsage(
            items=(
                FlowRunWithResultFilesAndTokenUsage(
                    run=run,
                    result_files=(),
                    token_usage=None,
                    final_output=FlowFinalOutputContractPublic(
                        step_id=uuid4(),
                        step_order=1,
                        output_type=FlowOutputType.TEXT,
                        output_mode=FlowOutputMode.PASS_THROUGH,
                        delivery=FlowOutputDelivery.PAYLOAD,
                    ),
                ),
            ),
            has_more=False,
        )
    )
    container.flow_run_service.return_value = run_service

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="tenant", space_id=None),
    )

    result = await list_flow_runs(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        limit=50,
        offset=0,
        container=container,
    )

    assert result["count"] == 1
    assert result["has_more"] is False
    container.space_service.return_value.get_space.assert_awaited_once_with(
        flow.space_id
    )


@pytest.mark.asyncio
async def test_space_scoped_api_key_rejects_wrong_space(monkeypatch):
    """Space-scoped API key for a different space must get 403 scope mismatch."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    wrong_space_id = uuid4()

    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
    )

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=wrong_space_id),
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await list_flow_runs(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            limit=50,
            offset=0,
            container=container,
        )
    _assert_scope_mismatch(
        exc_info,
        message="API key space scope does not match requested flow.",
    )


@pytest.mark.asyncio
async def test_space_scoped_api_key_matching_space_succeeds(monkeypatch):
    """User-owned space-scoped API keys should still load actor context for flow visibility."""
    container = MagicMock()
    flow_id = uuid4()
    flow = _flow(flow_id)
    run = _run(flow_id=flow_id, tenant_id=flow.tenant_id).model_copy(
        update={"output_payload_json": {"text": "Finished"}}
    )

    flow_service = AsyncMock()
    flow_service.get_flow.return_value = flow
    container.flow_service.return_value = flow_service
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=SimpleNamespace(ownership="user"),
    )
    _enable_space_access(container)

    run_service = AsyncMock()
    run_service.list_runs_with_result_files_and_token_usage.return_value = (
        FlowRunPageWithResultFilesAndTokenUsage(
            items=(
                FlowRunWithResultFilesAndTokenUsage(
                    run=run,
                    result_files=(),
                    token_usage=None,
                    final_output=FlowFinalOutputContractPublic(
                        step_id=uuid4(),
                        step_order=1,
                        output_type=FlowOutputType.TEXT,
                        output_mode=FlowOutputMode.PASS_THROUGH,
                        delivery=FlowOutputDelivery.PAYLOAD,
                    ),
                ),
            ),
            has_more=False,
        )
    )
    container.flow_run_service.return_value = run_service

    # Space-scoped key matching the flow's space
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="space", space_id=flow.space_id),
    )

    result = await list_flow_runs(
        id=flow_id,
        request=SimpleNamespace(state=SimpleNamespace()),
        limit=50,
        offset=0,
        container=container,
    )

    assert result["count"] == 1
    assert result["has_more"] is False
    container.space_service.return_value.get_space.assert_awaited_once_with(
        flow.space_id
    )


@pytest.mark.asyncio
async def test_assistant_scoped_api_key_cannot_access_flow_runtime(monkeypatch):
    container = MagicMock()
    flow_id = uuid4()
    container.flow_service.return_value = AsyncMock()
    container.flow_run_service.return_value = AsyncMock()
    container.user.return_value = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        permissions=[Permission.FLOWS],
        active_api_key=SimpleNamespace(ownership="user"),
    )

    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(scope_type="assistant", assistant_id=uuid4()),
    )

    with pytest.raises(UnauthorizedException) as exc_info:
        await list_flow_runs(
            id=flow_id,
            request=SimpleNamespace(state=SimpleNamespace()),
            limit=50,
            offset=0,
            container=container,
        )

    _assert_scope_mismatch(
        exc_info,
        message="API key scope does not permit flow access.",
    )
    container.flow_service.return_value.get_flow.assert_not_awaited()
    run_service = container.flow_run_service.return_value
    run_service.list_runs_with_result_files_and_token_usage.assert_not_awaited()
