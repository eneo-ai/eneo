from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from intric.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from intric.flows.application.flow_run_rerun_service import FlowRunRerunService
from intric.flows.enums import RerunDependencyKind
from intric.flows.flow import FlowRunStatus
from intric.flows.flow_run_rerun_request import (
    FlowRunRerunRequestFingerprintInput,
    build_rerun_request_fingerprint,
)
from intric.flows.published_definition import FLOW_PUBLISHED_FORM_SCHEMA_INVALID
from intric.main.exceptions import BadRequestException
from tests.unittests.flows.test_flow_run_service import (
    _flow,
    _flow_repo,
    _form_schema_flow,
    _rerun_command_result,
    _run,
    _runtime_version,
)


@pytest.mark.asyncio
async def test_rerun_step_builds_repository_command(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    file_repo = AsyncMock()
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
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
        file_repo=file_repo,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(
        user=user, flow=flow, version=3
    )
    prior_root_attempt_id = uuid4()
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = (
        prior_root_attempt_id
    )
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id, downstream_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result
    file_a_id = uuid4()
    file_b_id = uuid4()
    expected_file_ids = sorted({file_a_id, file_b_id}, key=str)
    file_repo.get_list_by_id_and_user.return_value = [
        SimpleNamespace(id=file_id, mimetype="application/pdf")
        for file_id in expected_file_ids
    ]

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=7,
        reason="  Corrected source  ",
        input_payload_json={"case_id": 123},
        step_inputs={root_step.id: {"file_ids": [file_b_id, file_a_id, file_b_id]}},
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
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_awaited_once_with(
        run_id=run.id,
        flow_id=flow.id,
        tenant_id=user.tenant_id,
        step_id=root_step.id,
    )
    file_repo.get_list_by_id_and_user.assert_awaited_once_with(
        ids=expected_file_ids,
        user_id=user.id,
        include_transcription=False,
    )
    expected_fingerprint = build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=user.tenant_id,
            requested_by_user_id=user.id,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=7,
            prior_root_attempt_id=prior_root_attempt_id,
            input_payload_json={"case_id": "123"},
            root_step_inputs={root_step.id: expected_file_ids},
        )
    )
    kwargs = flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["tenant_id"] == user.tenant_id
    assert kwargs["flow_id"] == flow.id
    assert kwargs["flow_run_id"] == run.id
    assert kwargs["rerun_step_id"] == root_step.id
    assert kwargs["rerun_step_order"] == root_step.step_order
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["expected_run_revision"] == 7
    assert kwargs["reason"] == "Corrected source"
    assert kwargs["input_payload_json"] == {"case_id": "123"}
    assert kwargs["step_inputs_json"] == {
        str(root_step.id): {"file_ids": [str(file_id) for file_id in expected_file_ids]}
    }
    assert kwargs["requested_by_user_id"] == user.id
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
async def test_rerun_step_preserves_empty_root_step_inputs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
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
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=3,
        reason="Refresh answer",
        step_inputs={root_step.id: {"file_ids": []}},
    )

    assert result == expected_result
    expected_fingerprint = build_rerun_request_fingerprint(
        FlowRunRerunRequestFingerprintInput(
            tenant_id=user.tenant_id,
            requested_by_user_id=user.id,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=3,
            prior_root_attempt_id=None,
            input_payload_json=None,
            root_step_inputs={root_step.id: []},
        )
    )
    kwargs = flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["step_inputs_json"] == {str(root_step.id): {"file_ids": []}}


@pytest.mark.asyncio
async def test_rerun_step_fingerprint_uses_none_without_completed_root_attempt(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 4}
    )
    root_step = flow.steps[0]
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result

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
            requested_by_user_id=user.id,
            flow_id=flow.id,
            flow_run_id=run.id,
            rerun_step_id=root_step.id,
            expected_run_revision=4,
            prior_root_attempt_id=None,
            input_payload_json=None,
            root_step_inputs=None,
        )
    )
    kwargs = flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["request_fingerprint"] == expected_fingerprint
    assert kwargs["input_payload_json"] is None
    assert kwargs["step_inputs_json"] is None


@pytest.mark.asyncio
async def test_rerun_step_returns_repository_replay_result(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 2}
    )
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = uuid4()
    replayed_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
        created=False,
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = replayed_result

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
async def test_rerun_step_rejects_empty_reason(user):
    service = FlowRunRerunService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=AsyncMock(),
        flow_version_repo=AsyncMock(),
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
    service = FlowRunRerunService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=AsyncMock(),
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
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED, "revision": 1}
    )
    service = FlowRunRerunService(
        user=user,
        flow_repo=_flow_repo(),
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result
    reason = "x" * 1024

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=1,
        reason=reason,
    )

    assert result == expected_result
    kwargs = flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs
    assert kwargs["reason"] == reason


@pytest.mark.asyncio
async def test_rerun_step_rejects_missing_published_root_step(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
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
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_downstream_step_inputs(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
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
            step_inputs={downstream_step.id: {"file_ids": []}},
        )

    assert exc_info.value.code == "flow_run_rerun_step_inputs_invalid"
    assert exc_info.value.context == {"step_ids": [str(downstream_step.id)]}
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_omitted_payload_does_not_require_form_fields(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
    )
    flow_run_repo.get.return_value = run
    flow_version_repo.get.return_value = _runtime_version(user=user, flow=flow)
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = None
    expected_result = _rerun_command_result(
        user=user,
        run=run,
        rerun_step_id=root_step.id,
        invalidated_step_ids=[root_step.id, downstream_step.id],
    )
    flow_run_repo.accept_or_replay_rerun_operation.return_value = expected_result

    result = await service.rerun_step(
        flow_id=flow.id,
        run_id=run.id,
        rerun_step_id=root_step.id,
        expected_run_revision=1,
        reason="Refresh answer",
    )

    assert result == expected_result
    assert (
        flow_run_repo.accept_or_replay_rerun_operation.await_args.kwargs[
            "input_payload_json"
        ]
        is None
    )


@pytest.mark.asyncio
async def test_rerun_step_rejects_empty_payload_missing_required_form_field(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _form_schema_flow(user)
    root_step = flow.steps[0]
    downstream_step = flow.steps[1].model_copy(update={"input_source": "previous_step"})
    flow = flow.model_copy(update={"steps": [root_step, downstream_step]})
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
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
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_malformed_published_form_schema(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
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
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
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
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_rejects_reserved_payload_keys(user):
    flow_repo = _flow_repo()
    flow_run_repo = AsyncMock()
    flow_version_repo = AsyncMock()
    flow = _flow(user=user, published_version=1)
    flow = flow.model_copy(update={"steps": [flow.steps[0]]})
    root_step = flow.steps[0]
    run = _run(user=user, flow_id=flow.id).model_copy(
        update={"status": FlowRunStatus.COMPLETED}
    )
    service = FlowRunRerunService(
        user=user,
        flow_repo=flow_repo,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
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
            input_payload_json={"expected_flow_version": 1},
        )

    assert exc_info.value.code == "flow_run_reserved_input_payload_key"
    flow_run_repo.get_latest_completed_attempt_id_for_step.assert_not_awaited()
    flow_run_repo.accept_or_replay_rerun_operation.assert_not_awaited()


@pytest.mark.asyncio
async def test_rerun_step_uses_rerun_access_policy(user):
    flow_run_repo = AsyncMock()
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
    flow_run_repo.get_latest_completed_attempt_id_for_step.return_value = None
    flow_run_repo.accept_or_replay_rerun_operation.return_value = (
        _rerun_command_result(
            user=user,
            run=run,
            rerun_step_id=root_step.id,
            invalidated_step_ids=[root_step.id],
        )
    )
    service = FlowRunRerunService(
        user=user,
        flow_run_repo=flow_run_repo,
        flow_version_repo=flow_version_repo,
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
