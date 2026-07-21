from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_run_rerun_service import FlowRunRerunService
from eneo.flows.assistant_execution_snapshot import build_assistant_execution_snapshot
from eneo.flows.domain.flow import FlowRunStatus, RerunStepInputOverride
from eneo.flows.domain.flow_run_exceptions import FlowRunNotFoundError
from eneo.flows.domain.rerun_exceptions import (
    FlowRunRerunInvalidTransitionError,
    FlowRunRerunMissingCurrentResultsError,
    FlowRunRerunRootStepIncompleteError,
    FlowRunRerunStaleRevisionError,
    FlowRunRerunStepInputsInvalidError,
    FlowRunRerunStepNotFoundError,
)
from eneo.flows.domain.run_step_input_exceptions import (
    FlowRunRuntimeUploadBindingRaceError,
)
from eneo.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
)
from eneo.flows.enums import RerunDependencyKind
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_run_input_envelope import (
    FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS,
    RerunInputOverride,
)
from eneo.flows.flow_run_rerun_request import (
    FlowRunRerunRequestFingerprintInput,
    build_rerun_request_fingerprint,
)
from eneo.flows.flow_run_step_inputs import FlowRunStepInputFiles
from eneo.flows.infrastructure.flow_run_rerun_repo import FlowRunRerunRepository
from eneo.flows.published_definition import (
    FLOW_PUBLISHED_FORM_SCHEMA_INVALID,
    published_definition_checksum,
)
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from tests.unittests.flows.test_flow_run_service import (
    _flow,
    _flow_repo,
    _form_schema_flow,
    _rerun_command_result,
    _run,
    _runtime_upload_repo,
    _runtime_version,
    _service_key_user,
)

_FILE_REPO_UNSET = object()


def _file_repo() -> AsyncMock:
    repo = AsyncMock()
    repo.get_list_by_id_for_owner.return_value = []
    return repo


def _assistant_snapshot(*, assistant_id: UUID, instructions: str) -> dict[str, object]:
    snapshot = build_assistant_execution_snapshot(
        assistant=SimpleNamespace(
            id=assistant_id,
            origin="flow_managed",
            prompt=SimpleNamespace(text=instructions),
            completion_model=None,
            completion_model_kwargs={},
            collections=[],
            websites=[],
            integration_knowledge_list=[],
        )
    )
    assert snapshot is not None
    return snapshot


def _rerun_service(
    *,
    user,
    flow_run_repo,
    flow_run_rerun_repo,
    flow_version_repo,
    runtime_upload_repo,
    file_repo=_FILE_REPO_UNSET,
    flow_repo=None,
    settings_service=None,
    access_policy=None,
) -> FlowRunRerunService:
    resolved_file_repo = _file_repo() if file_repo is _FILE_REPO_UNSET else file_repo
    if resolved_file_repo is None:
        raise AssertionError(
            "FlowRunRerunService tests must provide a file repository."
        )
    if access_policy is None:
        if flow_repo is None:
            raise AssertionError(
                "FlowRunRerunService tests must provide flow_repo or access_policy."
            )
        access_policy = FlowRunAccessPolicy(
            user=user,
            flow_repo=flow_repo,
            flow_run_repo=flow_run_repo,
        )
    return FlowRunRerunService(
        user=user,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=runtime_upload_repo,
        file_repo=resolved_file_repo,
        settings_service=settings_service,
        access_policy=access_policy,
    )


@pytest.mark.asyncio
async def test_rerun_step_builds_repository_command(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    file_repo = AsyncMock()
    runtime_upload_repo = AsyncMock()
    flow = _flow(
        user=user,
        published_version=3,
        metadata_json={
            "form_schema": {
                "fields": [
                    {"name": "case_id", "type": "text", "required": True, "order": 1}
                ]
            }
        },
    )
    root_step = flow.steps[0].model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": False,
                    "max_files": 5,
                    "input_format": "document",
                }
            }
        }
    )
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "flow_version": 3,
            "revision": 7,
            "status": FlowRunStatus.COMPLETED,
        }
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
        runtime_upload_repo=runtime_upload_repo,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(
        user=user, flow=flow, version=3
    )
    prior_root_attempt_id = uuid4()
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = (
        prior_root_attempt_id
    )
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id, downstream_step.id],
    )
    flow_run_rerun_repo.accept_or_replay_rerun_operation.return_value = expected_result
    file_a_id = uuid4()
    file_b_id = uuid4()
    expected_file_ids = [file_b_id, file_a_id]
    runtime_upload_repo.list_bound_file_ids_for_owner.return_value = set(
        expected_file_ids
    )
    file_repo.get_list_by_id_for_owner.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf", size=1024)
        for file_id in expected_file_ids
    ]

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=7,
        reason="  Corrected source  ",
        input_payload_json={"case_id": 123},
        step_inputs={
            root_step.id: FlowRunStepInputFiles(
                file_ids=(file_b_id, file_a_id, file_b_id)
            )
        },
    )

    assert result == expected_result
    flow_run_repo.get.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=user.tenant_id,
    )
    flow_version_repo.get.assert_awaited_once_with(
        flow_id=flow.id,
        version=3,
        tenant_id=user.tenant_id,
    )
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=user.tenant_id,
        step_id=root_step.id,
    )
    file_repo.get_list_by_id_for_owner.assert_awaited_once_with(
        ids=expected_file_ids,
        owner_type="user",
        owner_user_id=user.id,
        owner_service_id=None,
        tenant_id=user.tenant_id,
        include_transcription=False,
    )
    expected_fingerprint = build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=user.tenant_id,
            requested_by_principal_type=PrincipalType.USER,
            requested_by_user_id=user.id,
            requested_by_service_id=None,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=7,
            prior_root_attempt_id=prior_root_attempt_id,
            input_payload_json={"case_id": "123"},
            root_step_inputs={root_step.id: expected_file_ids},
        )
    )
    kwargs = flow_run_rerun_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["tenant_id"] == user.tenant_id
    assert kwargs["flow_id"] == flow.id
    assert kwargs["flow_run_id"] == run.id
    assert kwargs["rerun_step_id"] == root_step.id
    assert kwargs["rerun_step_order"] == root_step.step_order
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["expected_run_revision"] == 7
    assert kwargs["reason"] == "Corrected source"
    assert kwargs["rerun_input_override"] == RerunInputOverride(
        inline_payload_json={"case_id": "123"},
        root_step_input=RerunStepInputOverride(
            step_id=root_step.id,
            file_ids=tuple(expected_file_ids),
        ),
    )
    assert kwargs["requested_by_principal"].principal_type == PrincipalType.USER
    assert kwargs["requested_by_principal"].principal_user_id == user.id
    assert kwargs["requested_by_principal"].principal_service_id is None
    invalidated_steps = kwargs["invalidated_steps"]
    assert [
        (step.step_id, step.step_order, step.dependency_kinds)
        for step in invalidated_steps
    ] == [
        (root_step.id, root_step.step_order, ()),
        (
            downstream_step.id,
            downstream_step.step_order,
            (RerunDependencyKind.INPUT_SOURCE_PREVIOUS_STEP,),
        ),
    ]


@pytest.mark.asyncio
async def test_rerun_rejects_invalid_snapshot_before_graph_analysis(
    user,
    monkeypatch,
):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 2}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    version = _runtime_version(user=user, flow=flow)
    definition_json = dict(version.definition_json)
    definition_steps = [
        dict(step) for step in cast(list[dict[str, object]], definition_json["steps"])
    ]
    snapshot = _assistant_snapshot(
        assistant_id=root_step.assistant_id,
        instructions="Use the published source.",
    )
    snapshot["instructions"] = "Altered after publication."
    definition_steps[0]["assistant_snapshot"] = snapshot
    definition_json["steps"] = definition_steps
    flow_version_repo.get.return_value = version.model_copy(
        update={
            "definition_json": definition_json,
            "definition_checksum": published_definition_checksum(definition_json),
        }
    )
    graph_resolver = MagicMock()
    monkeypatch.setattr(service, "_resolve_rerun_graph", graph_resolver)

    with pytest.raises(BadRequestException, match="does not match its payload"):
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=2,
            reason="Refresh answer",
        )

    graph_resolver.assert_not_called()
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_dependencies_use_validated_executed_snapshot_instructions(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(
        update={
            "input_source": "http_get",
            "input_config": {
                "url": "https://example.org/source",
                "auth": {"mode": "none"},
            },
        }
    )
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    version = _runtime_version(user=user, flow=flow)
    definition_json = dict(version.definition_json)
    definition_steps = [
        dict(step) for step in cast(list[dict[str, object]], definition_json["steps"])
    ]
    definition_steps[0]["assistant_snapshot"] = _assistant_snapshot(
        assistant_id=root_step.assistant_id,
        instructions="Execute the root step.",
    )
    definition_steps[1]["assistant_snapshot"] = _assistant_snapshot(
        assistant_id=downstream_step.assistant_id,
        instructions="Revise {{ step_1.output.text }}.",
    )
    definition_json["steps"] = definition_steps
    flow_version_repo.get.return_value = version.model_copy(
        update={
            "definition_json": definition_json,
            "definition_checksum": published_definition_checksum(definition_json),
        }
    )
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id, downstream_step.id],
    )
    flow_run_rerun_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=4,
        reason="Refresh answer",
    )

    assert result == expected_result
    invalidated_steps = (
        flow_run_rerun_repo.accept_or_replay_rerun_operation.await_args.kwargs[
            "invalidated_steps"
        ]
    )
    assert [(step.step_id, step.dependency_kinds) for step in invalidated_steps] == [
        (root_step.id, ()),
        (
            downstream_step.id,
            (RerunDependencyKind.ASSISTANT_SNAPSHOT_INSTRUCTIONS,),
        ),
    ]


@pytest.mark.asyncio
async def test_service_principal_reruns_own_run(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "status": FlowRunStatus.COMPLETED,
            "revision": 5,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_service_id": service_user.active_api_key.service_principal_id,
            "created_by_api_key_id": service_user.active_api_key.id,
            "runtime_service_permission": service_user.active_api_key.permission,
        }
    )
    service = _rerun_service(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_rerun_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=5,
        reason="Refresh service-owned output",
    )

    assert result == expected_result
    expected_fingerprint = build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=service_user.tenant_id,
            requested_by_principal_type=PrincipalType.SERVICE_KEY,
            requested_by_user_id=None,
            requested_by_service_id=service_user.active_api_key.service_principal_id,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=5,
            prior_root_attempt_id=None,
            input_payload_json=None,
            root_step_inputs=None,
        )
    )
    kwargs = flow_run_rerun_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["requested_by_principal"].principal_type == PrincipalType.SERVICE_KEY
    assert (
        kwargs["requested_by_principal"].principal_service_id
        == service_user.active_api_key.service_principal_id
    )
    assert (
        kwargs["requested_by_principal"].actor_api_key_id
        == service_user.active_api_key.id
    )


@pytest.mark.asyncio
async def test_service_principal_cannot_rerun_other_principals_run(user):
    service_user = _service_key_user(user)
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    other_service_principal_id = uuid4()
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "status": FlowRunStatus.COMPLETED,
            "revision": 5,
            "principal_type": PrincipalType.SERVICE_KEY.value,
            "principal_user_id": None,
            "principal_service_id": other_service_principal_id,
            "created_by_api_key_id": uuid4(),
            "runtime_service_permission": service_user.active_api_key.permission,
        }
    )
    service = _rerun_service(
        user=service_user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run

    with pytest.raises(UnauthorizedException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=5,
            reason="Should not cross service-principal boundary",
        )

    assert exc_info.value.code == "flow_run_access_denied"
    flow_version_repo.get.assert_not_awaited()
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_preserves_empty_root_step_inputs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    root_step = flow.steps[0].model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": False,
                    "max_files": 5,
                    "input_format": "document",
                }
            }
        }
    )
    flow = flow.model_copy(update={"steps": [root_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 3}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_rerun_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=3,
        reason="Refresh answer",
        step_inputs={root_step.id: FlowRunStepInputFiles()},
    )

    assert result == expected_result
    expected_fingerprint = build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=user.tenant_id,
            requested_by_principal_type=PrincipalType.USER,
            requested_by_user_id=user.id,
            requested_by_service_id=None,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=3,
            prior_root_attempt_id=None,
            input_payload_json=None,
            root_step_inputs={root_step.id: []},
        )
    )
    kwargs = flow_run_rerun_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["rerun_input_override"].root_step_input == RerunStepInputOverride(
        step_id=root_step.id,
        file_ids=(),
    )


@pytest.mark.asyncio
async def test_rerun_step_fingerprint_uses_none_without_completed_root_attempt(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    root_step = flow.steps[0]
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_rerun_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=4,
        reason="Refresh answer",
    )

    assert result == expected_result
    expected_fingerprint = build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=user.tenant_id,
            requested_by_principal_type=PrincipalType.USER,
            requested_by_user_id=user.id,
            requested_by_service_id=None,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=4,
            prior_root_attempt_id=None,
            input_payload_json=None,
            root_step_inputs=None,
        )
    )
    kwargs = flow_run_rerun_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["rerun_input_override"] == RerunInputOverride()


@pytest.mark.asyncio
async def test_rerun_step_returns_repository_replay_result(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 2}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = uuid4()
    replayed_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
        created=False,
    )
    flow_run_rerun_repo.accept_or_replay_rerun_operation.return_value = replayed_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=2,
        reason="Refresh answer",
    )

    assert result == replayed_result
    assert result.created is False


@pytest.mark.asyncio
async def test_rerun_step_maps_repository_stale_revision(user):
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_rerun_repo.accept_or_replay_rerun_operation.side_effect = (
        FlowRunRerunStaleRevisionError(
            expected_run_revision=3,
            current_run_revision=4,
        )
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=3,
            reason="Refresh answer",
        )

    assert exc_info.value.code == "flow_run_rerun_stale_revision"
    assert exc_info.value.context == {
        "expected_run_revision": 3,
        "current_run_revision": 4,
    }


@pytest.mark.asyncio
async def test_rerun_step_maps_repository_invalid_transition(user):
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_rerun_repo.accept_or_replay_rerun_operation.side_effect = (
        FlowRunRerunInvalidTransitionError(status="awaiting_review")
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=4,
            reason="Refresh answer",
        )

    assert exc_info.value.code == "flow_run_rerun_invalid_transition"
    assert exc_info.value.context == {"status": "awaiting_review"}


@pytest.mark.asyncio
async def test_rerun_step_maps_repository_step_not_found(user):
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_rerun_repo.accept_or_replay_rerun_operation.side_effect = (
        FlowRunRerunStepNotFoundError()
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=4,
            reason="Refresh answer",
        )

    assert exc_info.value.code == "flow_run_rerun_step_not_found"
    assert exc_info.value.context is None


@pytest.mark.asyncio
async def test_rerun_step_maps_repository_missing_current_results(user):
    missing_step_id = uuid4()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_rerun_repo.accept_or_replay_rerun_operation.side_effect = (
        FlowRunRerunMissingCurrentResultsError(step_ids=(missing_step_id,))
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=4,
            reason="Refresh answer",
        )

    assert exc_info.value.code == "flow_run_rerun_step_incomplete"
    assert exc_info.value.context == {"step_ids": [str(missing_step_id)]}


@pytest.mark.asyncio
async def test_rerun_step_maps_repository_root_step_incomplete(user):
    root_step_id = uuid4()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_rerun_repo.accept_or_replay_rerun_operation.side_effect = (
        FlowRunRerunRootStepIncompleteError(step_ids=(root_step_id,))
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=4,
            reason="Refresh answer",
        )

    assert exc_info.value.code == "flow_run_rerun_step_incomplete"
    assert exc_info.value.context == {"step_ids": [str(root_step_id)]}


@pytest.mark.asyncio
async def test_rerun_step_maps_repository_step_inputs_invalid(user):
    invalid_step_id = uuid4()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_rerun_repo.accept_or_replay_rerun_operation.side_effect = (
        FlowRunRerunStepInputsInvalidError(step_ids=(invalid_step_id,))
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=4,
            reason="Refresh answer",
        )

    assert exc_info.value.code == "flow_run_rerun_step_inputs_invalid"
    assert exc_info.value.context == {"step_ids": [str(invalid_step_id)]}


@pytest.mark.asyncio
async def test_rerun_step_translates_repository_missing_run_race_to_public_not_found(
    user,
):
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_rerun_repo.accept_or_replay_rerun_operation.side_effect = (
        FlowRunNotFoundError(
            run_id=run.id,
            tenant_id=user.tenant_id,
            flow_id=run.flow_id,
        )
    )

    with pytest.raises(NotFoundException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=4,
            reason="Refresh answer",
        )

    assert exc_info.value.code is None


@pytest.mark.asyncio
async def test_rerun_step_maps_runtime_upload_binding_race_to_public_error(user):
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    step_id = uuid4()
    file_id = uuid4()
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_rerun_repo.accept_or_replay_rerun_operation.side_effect = (
        FlowRunRuntimeUploadBindingRaceError(step_id=step_id, file_ids=(file_id,))
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=4,
            reason="Refresh answer",
        )

    assert exc_info.value.code == "flow_run_file_not_bound_to_flow"
    assert exc_info.value.context == {
        "step_id": str(step_id),
        "file_ids": [str(file_id)],
    }


@pytest.mark.asyncio
async def test_rerun_step_rejects_empty_reason(user):
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=AsyncMock(),
        flow_run_rerun_repo=AsyncMock(spec=FlowRunRerunRepository),
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=uuid4(),
            run_id=uuid4(),
            rerun_step_id=uuid4(),
            expected_run_revision=1,
            reason="  \n\t  ",
        )

    assert exc_info.value.code == "flow_run_rerun_reason_required"
    service.flow_run_repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_too_long_reason(user):
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=AsyncMock(),
        runtime_upload_repo=_runtime_upload_repo(),
    )

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=uuid4(),
            run_id=uuid4(),
            rerun_step_id=uuid4(),
            expected_run_revision=1,
            reason="x" * 1025,
        )

    assert exc_info.value.code == "flow_run_rerun_reason_too_long"
    assert exc_info.value.context == {"max_length": 1024}
    flow_run_repo.get.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_accepts_max_length_reason(user):
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 1}
    )
    service = _rerun_service(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_rerun_repo.accept_or_replay_rerun_operation.return_value = expected_result
    reason = "x" * 1024

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=1,
        reason=reason,
    )

    assert result == expected_result
    kwargs = flow_run_rerun_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["reason"] == reason


@pytest.mark.asyncio
async def test_rerun_step_rejects_missing_published_root_step(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=uuid4(),
            expected_run_revision=1,
            reason="Refresh answer",
        )

    assert exc_info.value.code == "flow_run_rerun_step_not_found"
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_checksum_drift_before_rerun_acceptance(user) -> None:
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    version = _runtime_version(user=user, flow=flow)
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = version.model_copy(
        update={"definition_checksum": "stored-checksum-does-not-match"}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )

    with pytest.raises(FlowBadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=run.revision,
            reason="Refresh answer",
        )

    assert exc_info.value.code is FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_published_snapshot_without_executable_steps(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    runtime_upload_repo = AsyncMock()
    flow = _flow(user=user, published_version=5)
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={
            "flow_version": 5,
            "revision": 3,
            "status": FlowRunStatus.COMPLETED,
        }
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=runtime_upload_repo,
    )
    flow_run_repo.get.return_value = run
    empty_definition = {
        "schema_version": 1,
        "flow_id": str(flow.id),
        "steps": [],
    }
    flow_version_repo.get.return_value = SimpleNamespace(
        version=5,
        definition_checksum=published_definition_checksum(empty_definition),
        definition_json=empty_definition,
    )

    with pytest.raises(FlowPublishedDefinitionWithoutExecutableStepsError) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=flow.steps[0].id,
            expected_run_revision=3,
            reason="retry step",
        )

    assert exc_info.value.flow_id == flow.id
    assert exc_info.value.flow_version == 5
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_downstream_step_inputs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=1,
            reason="Refresh answer",
            step_inputs={downstream_step.id: FlowRunStepInputFiles()},
        )

    assert exc_info.value.code == "flow_run_rerun_step_inputs_invalid"
    assert exc_info.value.context == {"step_ids": [str(downstream_step.id)]}
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_inaccessible_file_before_repository(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    file_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    root_step = flow.steps[0].model_copy(
        update={
            "input_config": {
                "runtime_input": {
                    "enabled": True,
                    "required": False,
                    "max_files": 5,
                    "input_format": "document",
                }
            }
        }
    )
    flow = flow.model_copy(update={"steps": [root_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    missing_file_id = uuid4()
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        file_repo=file_repo,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    file_repo.get_list_by_id_for_owner.return_value = []

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=1,
            reason="Refresh answer",
            step_inputs={
                root_step.id: FlowRunStepInputFiles(file_ids=(missing_file_id,))
            },
        )

    assert exc_info.value.code == "flow_run_file_not_accessible"
    assert exc_info.value.context == {
        "step_id": str(root_step.id),
        "file_ids": [str(missing_file_id)],
    }
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_omitted_payload_does_not_require_form_fields(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id, downstream_step.id],
    )
    flow_run_rerun_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=1,
        reason="Refresh answer",
    )

    assert result == expected_result
    assert (
        flow_run_rerun_repo.accept_or_replay_rerun_operation.await_args.kwargs[
            "rerun_input_override"
        ]
        == RerunInputOverride()
    )


@pytest.mark.asyncio
async def test_rerun_step_rejects_empty_payload_missing_required_form_field(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=1,
            reason="Refresh answer",
            input_payload_json={},
        )

    assert exc_info.value.code == "flow_input_required_field_missing"
    assert exc_info.value.context == {
        "field_name": "Namn på brukare",
        "field_type": "text",
    }
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_malformed_published_form_schema(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user).model_copy(
        update={
            "metadata_json": {
                "form_schema": {"fields": [{"name": "case_id", "type": "unsupported"}]}
            }
        }
    )
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(
        BadRequestException, match="Published flow form schema is invalid"
    ) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=1,
            reason="Refresh answer",
            input_payload_json={"case_id": "A-123"},
        )

    assert exc_info.value.code == FLOW_PUBLISHED_FORM_SCHEMA_INVALID
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("reserved_key", sorted(FLOW_RUN_RESERVED_INPUT_PAYLOAD_KEYS))
async def test_rerun_step_rejects_reserved_payload_keys(user, reserved_key: str):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = _rerun_service(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)

    with pytest.raises(BadRequestException) as exc_info:
        await service.rerun_step(
            flow_id=flow.id,
            run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=1,
            reason="Refresh answer",
            input_payload_json={reserved_key: "value"},
        )

    assert exc_info.value.code == "flow_run_reserved_input_payload_key"
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_rerun_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_uses_rerun_access_policy(user):
    flow_run_repo = AsyncMock()
    flow_run_rerun_repo = AsyncMock(spec=FlowRunRerunRepository)
    flow_version_repo = AsyncMock()
    access_policy_mock = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 2}
    )
    access_policy_mock.load_run.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_rerun_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_rerun_repo.accept_or_replay_rerun_operation.return_value = (
        _rerun_command_result(
            user=user,
            run=run,
            rerun_step_id=root_step.id,
            invalidated_step_ids=[root_step.id],
        )
    )
    service = _rerun_service(
        user=user,
        flow_run_repo=flow_run_repo,
        flow_run_rerun_repo=flow_run_rerun_repo,
        flow_version_repo=flow_version_repo,
        runtime_upload_repo=_runtime_upload_repo(),
        access_policy=cast(FlowRunAccessPolicy, access_policy_mock),
    )

    await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=2,
        reason="Refresh answer",
    )

    access_policy_mock.load_run.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow.id,
        access_kind="rerun",
    )
