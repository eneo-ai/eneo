from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileType
from eneo.flows.api.flow_assembler import FlowAssembler, FlowRunResultProjectionError
from eneo.flows.api.flow_models import (
    FlowAssistantCreateRequest,
    FlowCreateRequest,
    FlowFinalOutputContractPublic,
    FlowOutputDelivery,
    FlowReviewStepContractPublic,
    FlowRunContractPublic,
    FlowRunCreateRequest,
    FlowRunDebugAttempt,
    FlowRunEvidenceResponse,
    FlowRunPublic,
    FlowRunRerunInvalidatedStepPublic,
    FlowRunRerunOperationPublic,
    FlowRunStepPublic,
    FlowRuntimeInputContractPublic,
    FlowRuntimeUploadPolicyPublic,
    FlowStepAttemptPublic,
    FlowStepCreateRequest,
    FlowStepUpdateRequest,
    FlowTemplateReadinessPublic,
    FlowUpdateRequest,
    FormFieldPublic,
    StepRunInput,
)
from eneo.flows.domain.flow import Flow, FlowRun, FlowRunReviewCheckpoint, FlowSparse
from eneo.flows.domain.flow_invariant_exceptions import FlowPersistedIdMissingError
from eneo.flows.enums import (
    FlowOutputMode,
    FlowOutputType,
    FlowRunLifecycleSource,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowRunStatus,
    FlowStepAttemptStatus,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_metadata import FlowFormFieldType
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.flow_run_error import (
    FlowRunDispatchError,
    FlowRunDispatchErrorKind,
    FlowRunError,
    parse_flow_run_dispatch_error,
)
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.main.exceptions import BadRequestException

_MISSING = object()


def _flow_sparse_domain(flow_id=None) -> FlowSparse:
    return FlowSparse(
        id=flow_id,
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
    )


def _flow_domain(flow_id=None) -> Flow:
    return Flow(
        id=flow_id,
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
        steps=[],
    )


@pytest.mark.parametrize("factory", [_flow_sparse_domain, _flow_domain])
def test_require_persisted_id_returns_existing_flow_id(factory) -> None:
    flow_id = uuid4()

    assert factory(flow_id).require_persisted_id() == flow_id


@pytest.mark.parametrize("factory", [_flow_sparse_domain, _flow_domain])
def test_require_persisted_id_raises_for_unsaved_flow(factory) -> None:
    with pytest.raises(FlowPersistedIdMissingError):
        factory(None).require_persisted_id()


def test_runtime_public_projection_requires_persisted_flow_id() -> None:
    flow = _flow_domain(None)

    with pytest.raises(FlowPersistedIdMissingError):
        FlowAssembler().to_runtime_public(
            flow,
            published_version=1,
            api_prefix="/api/v1",
        )


def test_runtime_public_projection_maps_published_runtime_fields() -> None:
    flow_id = uuid4()
    flow = _flow_domain(flow_id).model_copy(
        update={
            "name": "Published flow",
            "description": "Runtime projection",
            "published_version": 3,
        }
    )

    public = FlowAssembler().to_runtime_public(
        flow,
        published_version=3,
        api_prefix="/api/v1",
    )

    assert public.id == flow_id
    assert public.space_id == flow.space_id
    assert public.name == "Published flow"
    assert public.description == "Runtime projection"
    assert public.published_version == 3
    assert public.runtime_paths.create_run == f"/api/v1/flows/{flow_id}/runs/"


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "assistant_id": str(uuid4()),
        "step_order": 1,
        "input_source": "flow_input",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "json",
    }
    payload.update(overrides)
    return payload


def _flow_create_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "space_id": str(uuid4()),
        "name": "Flow",
        "description": "Flow description",
        "steps": [_payload()],
    }
    payload.update(overrides)
    return payload


def _assert_extra_forbidden(
    model: type[BaseModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        model.model_validate({**payload, "unexpected": True})

    assert any(
        error.get("type") == "extra_forbidden" for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_source", "banana"),
        ("input_type", "banana"),
        ("output_mode", "banana"),
        ("output_type", "banana"),
    ],
)
def test_flow_step_create_request_rejects_invalid_enum_values(
    field: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        FlowStepCreateRequest.model_validate(_payload(**{field: value}))


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (FlowStepCreateRequest, _payload(input_source="http_post")),
        (
            FlowStepUpdateRequest,
            _payload(id=str(uuid4()), input_source="http_post"),
        ),
    ],
)
def test_flow_step_requests_reject_http_post_input_source(
    model: type[BaseModel], payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_flow_step_create_request_accepts_template_fill_output_mode() -> None:
    request = FlowStepCreateRequest.model_validate(
        _payload(
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_asset_id": str(uuid4()),
                "bindings": {"title": "{{flow_input.title}}"},
            },
        )
    )

    assert request.output_mode.value == "template_fill"


def test_flow_step_create_request_does_not_expose_persisted_id() -> None:
    assert "id" not in FlowStepCreateRequest.model_json_schema()["properties"]


def test_flow_step_update_request_accepts_persisted_step_id() -> None:
    step_id = uuid4()

    request = FlowStepUpdateRequest.model_validate(_payload(id=str(step_id)))

    assert request.id == step_id


def test_flow_run_create_request_parses_typed_step_inputs() -> None:
    step_id = uuid4()
    file_id = uuid4()

    request = FlowRunCreateRequest.model_validate(
        {
            "step_inputs": {
                str(step_id): {
                    "file_ids": [str(file_id)],
                }
            }
        }
    )

    assert request.step_inputs is not None
    assert isinstance(request.step_inputs[step_id], StepRunInput)
    assert request.step_inputs[step_id].file_ids == [file_id]


def test_flow_run_create_request_rejects_removed_top_level_file_ids() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        FlowRunCreateRequest.model_validate({"file_ids": [str(uuid4())]})

    assert exc_info.value.code == "flow_run_top_level_file_ids_not_supported"
    assert "run contract endpoint" in str(exc_info.value)
    assert exc_info.value.context == {
        "invalid_field": "file_ids",
        "expected_field": "step_inputs[step_id].file_ids",
        "contract_endpoint": "/api/v1/flows/{id}/run-contract/",
    }


def test_flow_request_shell_models_reject_unknown_top_level_fields() -> None:
    cases: tuple[tuple[type[BaseModel], dict[str, object]], ...] = (
        (FlowStepCreateRequest, _payload()),
        (FlowStepUpdateRequest, _payload(id=str(uuid4()))),
        (FlowCreateRequest, _flow_create_payload()),
        (FlowUpdateRequest, {"name": "Updated flow"}),
        (FlowAssistantCreateRequest, {"name": "Flow Step Assistant"}),
    )

    for model, payload in cases:
        _assert_extra_forbidden(model, payload)


def test_flow_update_request_partial_model_preserves_strict_request_config() -> None:
    assert FlowUpdateRequest.__name__ == "PartialFlowUpdateRequest"
    assert FlowUpdateRequest.model_config.get("extra") == "forbid"

    _assert_extra_forbidden(FlowUpdateRequest, {"name": "Updated flow"})


def test_flow_update_request_allows_partial_patch_without_steps() -> None:
    request = FlowUpdateRequest.model_validate({"name": "Updated flow"})

    assert request.name == "Updated flow"
    assert request.steps is None


@pytest.mark.parametrize("value", [None, 1, 30, 2555])
@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (FlowCreateRequest, _flow_create_payload),
        (FlowUpdateRequest, lambda **kwargs: kwargs),
    ],
)
def test_flow_request_models_accept_valid_data_retention_days(
    model: type[BaseModel],
    payload,
    value: int | None,
) -> None:
    request = model.model_validate(payload(data_retention_days=value))

    assert request.data_retention_days == value


@pytest.mark.parametrize("value", [0, -1, 2556, True, False, "30", 1.5])
@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (FlowCreateRequest, _flow_create_payload),
        (FlowUpdateRequest, lambda **kwargs: kwargs),
    ],
)
def test_flow_request_models_reject_invalid_data_retention_days(
    model: type[BaseModel],
    payload,
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        model.model_validate(payload(data_retention_days=value))


def test_flow_request_shell_models_keep_nested_maps_open() -> None:
    step_request = FlowStepCreateRequest.model_validate(
        _payload(
            input_contract={
                "type": "object",
                "x-workflow-contract": {"nested": True},
            },
            output_contract={"type": "object", "x-output": {"nested": True}},
            input_bindings={"question": "{{flow.input.question}}", "custom": 1},
            input_config={"runtime": {"custom": True}},
            output_config={"delivery": {"custom": True}},
        )
    )
    flow_request = FlowCreateRequest.model_validate(
        _flow_create_payload(
            metadata_json={"wizard": {"transcription_enabled": True}},
            steps=[step_request.model_dump(mode="json")],
        )
    )
    update_request = FlowUpdateRequest.model_validate(
        {"metadata_json": {"wizard": {"transcription_enabled": True}}}
    )
    assert step_request.input_contract == {
        "type": "object",
        "x-workflow-contract": {"nested": True},
    }
    assert flow_request.metadata_json == {"wizard": {"transcription_enabled": True}}
    assert update_request.metadata_json == {"wizard": {"transcription_enabled": True}}


def test_flow_run_contract_public_parses_typed_form_fields() -> None:
    final_step_id = uuid4()
    contract = FlowRunContractPublic.model_validate(
        {
            "flow_id": str(uuid4()),
            "published_flow_version": 3,
            "final_output": {
                "step_id": str(final_step_id),
                "step_order": 3,
                "label": "Create Word report",
                "output_type": "docx",
                "output_mode": "pass_through",
                "delivery": "artifact",
                "output_contract": None,
            },
            "form_fields": [
                {
                    "name": "employee_name",
                    "type": "text",
                    "label": "Employee name",
                    "required": True,
                }
            ],
        }
    )

    assert isinstance(contract.form_fields[0], FormFieldPublic)
    assert contract.form_fields[0].name == "employee_name"
    assert contract.form_fields[0].type is FlowFormFieldType.TEXT
    assert contract.final_output is not None
    assert contract.final_output.step_id == final_step_id
    assert contract.final_output.output_type == FlowOutputType.DOCX
    assert contract.final_output.output_mode == FlowOutputMode.PASS_THROUGH
    assert contract.final_output.delivery == FlowOutputDelivery.ARTIFACT


def test_flow_run_contract_public_rejects_unknown_response_fields() -> None:
    payload = {
        "flow_id": str(uuid4()),
        "published_flow_version": 3,
        "form_fields": [
            {
                "name": "employee_name",
                "type": "text",
                "label": "Employee name",
                "required": True,
            }
        ],
    }

    with pytest.raises(ValidationError):
        FlowRunContractPublic.model_validate({**payload, "unexpected": True})

    with pytest.raises(ValidationError):
        FlowRunContractPublic.model_validate(
            {
                **payload,
                "form_fields": [
                    {
                        "name": "employee_name",
                        "type": "text",
                        "unexpected": True,
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    ("model_cls", "payload"),
    [
        (
            FlowRuntimeUploadPolicyPublic,
            {
                "min_timeout_seconds": 120,
                "seconds_per_mebibyte": 8,
                "max_timeout_seconds": 600,
                "idle_timeout_seconds": 120,
            },
        ),
        (
            FlowRuntimeInputContractPublic,
            {
                "step_id": str(uuid4()),
                "step_order": 1,
                "required": True,
                "input_format": "document",
            },
        ),
        (
            FlowReviewStepContractPublic,
            {
                "step_id": str(uuid4()),
                "step_order": 2,
                "review_mode": "edit",
                "output_type": "json",
            },
        ),
        (
            FlowFinalOutputContractPublic,
            {
                "step_id": str(uuid4()),
                "step_order": 3,
                "output_type": "docx",
                "output_mode": "pass_through",
                "delivery": "artifact",
            },
        ),
        (
            FlowTemplateReadinessPublic,
            {
                "step_id": str(uuid4()),
                "status": "ready",
            },
        ),
    ],
)
def test_run_contract_nested_public_models_reject_unknown_fields(
    model_cls: type[BaseModel], payload: dict[str, object]
) -> None:
    with pytest.raises(ValidationError):
        model_cls.model_validate({**payload, "unexpected": True})


def test_review_checkpoint_public_exposes_render_contract() -> None:
    now = datetime(2026, 3, 17, 10, 5, tzinfo=timezone.utc)
    checkpoint = FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=uuid4(),
        flow_id=uuid4(),
        flow_run_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
        revision=1,
        schema_version=1,
        original_payload_json={"transcription": "draft"},
        current_payload_json={"transcription": "draft"},
        step_label="Review transcription",
        review_mode=FlowStepReviewMode.EDIT,
        output_type=FlowOutputType.JSON,
        output_contract_json={
            "type": "object",
            "properties": {"transcription": {"type": "string"}},
        },
        requester_principal_type=PrincipalType.USER,
        requester_user_id=uuid4(),
        next_step_ids_json=[uuid4()],
        created_at=now,
        updated_at=now,
    )

    public = FlowAssembler().to_review_checkpoint_public(checkpoint)

    assert public.step_label == "Review transcription"
    assert public.review_mode == FlowStepReviewMode.EDIT
    assert public.output_type == FlowOutputType.JSON
    assert not hasattr(public, "step_snapshot_available")
    assert public.output_contract == {
        "type": "object",
        "properties": {"transcription": {"type": "string"}},
    }
    assert not hasattr(public, "output_contract_json")


def test_run_public_exposes_only_semantic_input_payload() -> None:
    now = datetime(2026, 3, 17, 10, 5, tzinfo=timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=3,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.QUEUED,
        input_payload_json={
            "employee_name": "Alex Example",
            "expected_flow_version": 3,
            "transkribering": "cached transcript",
            "step_inputs": {"step-id": {"file_ids": ["file-id"]}},
            "file_ids": ["removed-top-level-file-id"],
        },
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )

    public = FlowAssembler().to_run_public(run)

    assert public.input_payload_json == {"employee_name": "Alex Example"}
    assert "expected_flow_version" in (run.input_payload_json or {})


def _completed_run(*, output_payload_json: dict[str, object] | None) -> FlowRun:
    now = datetime(2026, 3, 17, 10, 5, tzinfo=timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=3,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        input_payload_json=None,
        output_payload_json=output_payload_json,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _final_output(
    *,
    step_id=None,
    output_type: FlowOutputType,
    delivery: FlowOutputDelivery,
    output_contract: dict[str, object] | None = None,
) -> FlowFinalOutputContractPublic:
    return FlowFinalOutputContractPublic(
        step_id=step_id or uuid4(),
        step_order=1,
        output_type=output_type,
        output_mode=FlowOutputMode.PASS_THROUGH,
        delivery=delivery,
        output_contract=output_contract,
    )


def test_run_public_projects_text_and_opaque_structured_results() -> None:
    assembler = FlowAssembler()
    text_run = _completed_run(output_payload_json={"text": "Finished report"})
    structured_value = {
        "summary": "Finished report",
        "authored_extension": {"version": 7, "items": [True, None]},
    }
    structured_contract = {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
    }
    structured_run = _completed_run(
        output_payload_json={
            "text": "ignored serialized representation",
            "structured": structured_value,
        }
    )

    text_public = assembler.to_run_public(
        text_run,
        final_output=_final_output(
            output_type=FlowOutputType.TEXT,
            delivery=FlowOutputDelivery.PAYLOAD,
        ),
    )
    structured_public = assembler.to_run_public(
        structured_run,
        final_output=_final_output(
            output_type=FlowOutputType.JSON,
            delivery=FlowOutputDelivery.PAYLOAD,
            output_contract=structured_contract,
        ),
    )

    assert text_public.model_dump(mode="json")["result"] == {
        "kind": "inline_text",
        "text": "Finished report",
    }
    assert structured_public.model_dump(mode="json")["result"] == {
        "kind": "structured",
        "value": structured_value,
        "output_contract": structured_contract,
    }


def test_run_public_projects_file_backed_text_with_exact_generated_file() -> None:
    assembler = FlowAssembler()
    final_step_id = uuid4()
    file_id = uuid4()
    run = _completed_run(
        output_payload_json={
            "text": "Bounded preview",
            "text_overflow": {
                "generated_file_ids": [str(file_id)],
                "inline_text_bytes": 15,
                "full_text_bytes": 30,
            },
        }
    )
    result_file = FlowRunStepResultFile(
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_result_id=uuid4(),
        step_id=final_step_id,
        step_order=1,
        attempt_no=2,
        file_id=file_id,
        ordinal=0,
        source="generated_output",
        name="full-output.txt",
        checksum="text-checksum",
        size=30,
        mimetype="text/plain",
        file_type=FileType.TEXT,
        availability="content_purged",
    )

    public = assembler.to_run_public(
        run,
        result_files=(result_file,),
        final_output=_final_output(
            step_id=final_step_id,
            output_type=FlowOutputType.TEXT,
            delivery=FlowOutputDelivery.PAYLOAD,
        ),
    )

    assert public.model_dump(mode="json")["result"] == {
        "kind": "file_backed_text",
        "preview": "Bounded preview",
        "file": result_file.model_dump(mode="json"),
    }


@pytest.mark.parametrize(
    ("step_id_matches", "source"),
    [
        (False, "generated_output"),
        (True, "declared_artifact"),
    ],
)
def test_run_public_rejects_overflow_file_from_wrong_owner(
    step_id_matches: bool,
    source: str,
) -> None:
    final_step_id = uuid4()
    file_id = uuid4()
    run = _completed_run(
        output_payload_json={
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": [str(file_id)],
                "inline_text_bytes": 7,
                "full_text_bytes": 20,
            },
        }
    )
    result_file = FlowRunStepResultFile(
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_result_id=uuid4(),
        step_id=final_step_id if step_id_matches else uuid4(),
        step_order=1,
        attempt_no=1,
        file_id=file_id,
        ordinal=0,
        source=source,
        name="not-the-current-output.txt",
        checksum="wrong-owner",
        size=20,
        mimetype="text/plain",
        file_type=FileType.TEXT,
        availability="available",
    )

    with pytest.raises(
        FlowRunResultProjectionError,
        match="exactly one current final-step generated output file",
    ):
        FlowAssembler().to_run_public(
            run,
            result_files=(result_file,),
            final_output=_final_output(
                step_id=final_step_id,
                output_type=FlowOutputType.TEXT,
                delivery=FlowOutputDelivery.PAYLOAD,
            ),
        )


def test_run_public_projects_current_artifact_metadata_and_outbound_receipt() -> None:
    assembler = FlowAssembler()
    artifact_run = _completed_run(output_payload_json=None)
    final_step_id = uuid4()
    result_file = FlowRunStepResultFile(
        flow_run_id=artifact_run.id,
        flow_id=artifact_run.flow_id,
        tenant_id=artifact_run.tenant_id,
        step_result_id=uuid4(),
        step_id=final_step_id,
        step_order=1,
        attempt_no=2,
        file_id=uuid4(),
        ordinal=0,
        source="generated_output",
        name="report.pdf",
        checksum="artifact-checksum",
        size=4096,
        mimetype="application/pdf",
        file_type=FileType.DOCUMENT,
        availability="available",
    )

    artifact_public = assembler.to_run_public(
        artifact_run,
        result_files=(result_file,),
        final_output=_final_output(
            step_id=final_step_id,
            output_type=FlowOutputType.PDF,
            delivery=FlowOutputDelivery.ARTIFACT,
        ),
    )
    outbound_public = assembler.to_run_public(
        _completed_run(output_payload_json=None),
        final_output=_final_output(
            output_type=FlowOutputType.JSON,
            delivery=FlowOutputDelivery.OUTBOUND_HTTP,
        ),
    )

    artifact_result = artifact_public.model_dump(mode="json")["result"]
    assert artifact_result["kind"] == "artifact"
    assert artifact_result["files"] == [result_file.model_dump(mode="json")]
    assert outbound_public.model_dump(mode="json")["result"] == {
        "kind": "outbound_http",
        "delivery_status": "delivered",
    }


def test_run_public_fails_explicitly_when_completed_artifact_is_missing() -> None:
    with pytest.raises(
        FlowRunResultProjectionError,
        match="no current final-step artifact metadata",
    ):
        FlowAssembler().to_run_public(
            _completed_run(output_payload_json=None),
            final_output=_final_output(
                output_type=FlowOutputType.DOCX,
                delivery=FlowOutputDelivery.ARTIFACT,
            ),
        )


def test_run_public_fails_explicitly_without_completed_run_contract() -> None:
    with pytest.raises(
        FlowRunResultProjectionError,
        match="has no pinned final-output contract",
    ):
        FlowAssembler().to_run_public(
            _completed_run(output_payload_json={"text": "Finished report"})
        )


def _review_checkpoint_payload() -> dict[str, object]:
    now = datetime(2026, 3, 17, 10, 5, tzinfo=timezone.utc)
    return {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "flow_id": uuid4(),
        "flow_run_id": uuid4(),
        "step_id": uuid4(),
        "step_order": 1,
        "attempt_no": 1,
        "state": FlowRunReviewCheckpointState.AWAITING_REVIEW,
        "revision": 1,
        "schema_version": 1,
        "original_payload_json": {"text": "draft"},
        "current_payload_json": {"text": "draft"},
        "step_label": "Review transcription",
        "review_mode": FlowStepReviewMode.EDIT,
        "output_type": FlowOutputType.JSON,
        "output_contract_json": None,
        "requester_principal_type": PrincipalType.USER,
        "requester_user_id": uuid4(),
        "next_step_ids_json": [],
        "created_at": now,
        "updated_at": now,
    }


@pytest.mark.parametrize("missing_field", ["review_mode", "output_type"])
def test_review_checkpoint_requires_step_snapshot_fields(missing_field: str) -> None:
    payload = _review_checkpoint_payload()
    del payload[missing_field]

    with pytest.raises(ValidationError):
        FlowRunReviewCheckpoint.model_validate(payload)


def test_flow_run_evidence_response_parses_typed_nested_models() -> None:
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    step_id = uuid4()
    step_result_id = uuid4()
    file_id = uuid4()
    attempt_id = uuid4()
    rerun_operation_id = uuid4()
    rerun_invalidated_step_id = uuid4()
    replacement_attempt_id = uuid4()
    review_checkpoint_id = uuid4()
    review_checkpoint_contract = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    }

    response = FlowRunEvidenceResponse.model_validate(
        {
            "run": {
                "id": str(run_id),
                "flow_id": str(flow_id),
                "flow_version": 2,
                "tenant_id": str(tenant_id),
                "trace_id": str(uuid4()),
                "status": "completed",
                "revision": 1,
                "dispatch_attempt_count": 0,
                "created_at": "2026-03-20T12:00:00Z",
                "updated_at": "2026-03-20T12:05:00Z",
            },
            "definition_integrity": {
                "status": "verified",
                "expected_checksum": "expected-checksum",
                "current_checksum": "expected-checksum",
            },
            "definition_snapshot": {"steps": []},
            "step_results": [
                {
                    "id": str(step_result_id),
                    "flow_run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "tenant_id": str(tenant_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "status": "completed",
                    "effective_prompt": "Summarize the report",
                    "model_parameters_json": {"temperature": 0.2},
                    "flow_step_execution_hash": "abc123",
                    "created_at": "2026-03-20T12:00:01Z",
                    "updated_at": "2026-03-20T12:00:05Z",
                }
            ],
            "result_files": [
                {
                    "flow_run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "tenant_id": str(tenant_id),
                    "step_result_id": str(step_result_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "attempt_no": 1,
                    "file_id": str(file_id),
                    "ordinal": 0,
                    "source": "declared_artifact",
                    "name": "artifact.pdf",
                    "checksum": "artifact-checksum",
                    "size": 4096,
                    "mimetype": "application/pdf",
                    "file_type": "document",
                    "availability": "available",
                }
            ],
            "step_attempts": [
                {
                    "id": str(attempt_id),
                    "flow_run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "tenant_id": str(tenant_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "attempt_no": 1,
                    "status": "completed",
                    "started_at": "2026-03-20T12:00:00Z",
                    "finished_at": "2026-03-20T12:00:05Z",
                    "created_at": "2026-03-20T12:00:00Z",
                    "updated_at": "2026-03-20T12:00:05Z",
                }
            ],
            "rerun_operations": [
                {
                    "id": str(rerun_operation_id),
                    "tenant_id": str(tenant_id),
                    "flow_id": str(flow_id),
                    "flow_run_id": str(run_id),
                    "rerun_step_id": str(step_id),
                    "rerun_step_order": 1,
                    "root_attempt_no": 2,
                    "root_attempt_id": str(replacement_attempt_id),
                    "status": "completed",
                    "request_fingerprint": "rerun-fingerprint",
                    "expected_run_revision": 1,
                    "accepted_run_revision": 2,
                    "reason": "Reviewer corrected the step output.",
                    "input_payload_json": {"question": "Updated input"},
                    "input_revision": {"status": "not_recorded"},
                    "root_step_input_override": {
                        "step_id": str(step_id),
                        "file_ids": [],
                    },
                    "root_step_input_override_requested": True,
                    "requested_by_principal_type": "user",
                    "requested_by_user_id": str(uuid4()),
                    "failure_code": None,
                    "failure_message": None,
                    "started_at": "2026-03-20T12:01:00Z",
                    "finished_at": "2026-03-20T12:01:05Z",
                    "created_at": "2026-03-20T12:01:00Z",
                    "updated_at": "2026-03-20T12:01:05Z",
                }
            ],
            "rerun_invalidated_steps": [
                {
                    "id": str(rerun_invalidated_step_id),
                    "operation_id": str(rerun_operation_id),
                    "tenant_id": str(tenant_id),
                    "flow_id": str(flow_id),
                    "flow_run_id": str(run_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "invalidation_order": 1,
                    "role": "root",
                    "dependency_sources_json": ["input_bindings.question"],
                    "prior_step_result_id": str(step_result_id),
                    "prior_attempt_id": str(attempt_id),
                    "new_attempt_no": 2,
                    "new_attempt_id": str(replacement_attempt_id),
                    "created_at": "2026-03-20T12:01:00Z",
                    "updated_at": "2026-03-20T12:01:05Z",
                }
            ],
            "review_checkpoints": [
                {
                    "id": str(review_checkpoint_id),
                    "tenant_id": str(tenant_id),
                    "flow_id": str(flow_id),
                    "flow_run_id": str(run_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "attempt_no": 1,
                    "state": "awaiting_review",
                    "revision": 1,
                    "schema_version": 1,
                    "original_payload_json": {"summary": "draft"},
                    "current_payload_json": {"summary": "reviewed"},
                    "step_label": "Review summary",
                    "review_mode": "edit",
                    "output_type": "json",
                    "output_contract": review_checkpoint_contract,
                    "decision": None,
                    "next_step_ids": [],
                    "resume_key_present": False,
                    "requester_user_id": str(uuid4()),
                    "requester_principal_type": "user",
                    "decided_by_user_id": None,
                    "decided_by_principal_type": None,
                    "created_at": "2026-03-20T12:00:05Z",
                    "updated_at": "2026-03-20T12:00:05Z",
                }
            ],
            "webhook_deliveries": [],
            "provider_calls": {
                "items": [],
                "count": 0,
                "total_count": 0,
                "has_more": False,
                "next_after_event_id": None,
            },
            "debug_export": {
                "schema_version": "eneo.flow.debug-export.v2",
                "generated_at": "2026-03-20T12:05:00Z",
                "run": {
                    "run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "flow_version": 2,
                    "trace_id": str(uuid4()),
                    "status": "completed",
                },
                "definition": {
                    "flow_id": str(flow_id),
                    "version": 2,
                    "checksum": "abc",
                    "steps_count": 1,
                },
                "definition_snapshot": {"steps": []},
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "io_types": {"input": "text", "output": "json"},
                        "input": {
                            "source": "flow_input",
                            "type": "text",
                            "contract": None,
                            "bindings": None,
                            "config": None,
                        },
                        "output": {
                            "mode": "pass_through",
                            "type": "json",
                            "contract": None,
                            "classification": None,
                            "config": None,
                        },
                        "rag": {
                            "attempted": True,
                            "status": "success",
                            "tracking": {
                                "retrieval_tracked": True,
                                "prompt_context_inclusion_tracked": True,
                                "citation_tracked": False,
                                "material_influence_tracked": False,
                                "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                            },
                            "prompt_context": {
                                "tracked": True,
                                "included_source_ids": ["source-1"],
                                "included_source_titles": ["Beslut till underlag"],
                                "included_source_display_names": [
                                    "Beslut till underlag"
                                ],
                                "summary": {
                                    "total_sources": 1,
                                    "total_chunks": 2,
                                    "truncated_by_token_budget": False,
                                    "top_ranked_sources": [
                                        {
                                            "source_id": "source-1",
                                            "display_name": "Beslut till underlag",
                                            "source_kind": "website",
                                            "included_group_count": 1,
                                            "included_chunk_count": 2,
                                            "best_score": 1.0,
                                            "rank": 1,
                                        }
                                    ],
                                },
                                "included_groups": [
                                    {
                                        "source_id": "source-1",
                                        "source_title": "Beslut till underlag",
                                        "start_chunk": 1,
                                        "end_chunk": 2,
                                        "chunk_count": 2,
                                        "relevance_score": 1.0,
                                    }
                                ],
                            },
                        },
                        "attempts": [
                            {
                                "attempt_no": 1,
                                "status": "completed",
                                "duration_ms": 5000,
                                "error_code": None,
                                "requested_model": "gpt-4.1",
                                "response_model": "gpt-4.1-mini",
                                "provider": "openai",
                                "finish_reason": "stop",
                                "provider_response_id": "resp-123",
                                "num_tokens_input": 12,
                                "num_tokens_output": 18,
                            }
                        ],
                    }
                ],
                "security": {
                    "redaction_applied": True,
                    "classification_field": "output_classification_override",
                },
            },
        }
    )

    assert isinstance(response.step_attempts[0], FlowStepAttemptPublic)
    assert response.step_attempts[0].status == FlowStepAttemptStatus.COMPLETED
    assert isinstance(response.rerun_operations[0], FlowRunRerunOperationPublic)
    assert response.rerun_operations[0].status == FlowRunRerunOperationStatus.COMPLETED
    assert response.rerun_operations[0].root_attempt_id == replacement_attempt_id
    assert response.rerun_operations[0].input_payload == {"question": "Updated input"}
    assert response.rerun_operations[0].root_step_input_override is not None
    assert response.rerun_operations[0].root_step_input_override.step_id == step_id
    assert response.rerun_operations[0].root_step_input_override.file_ids == []
    assert isinstance(
        response.rerun_invalidated_steps[0], FlowRunRerunInvalidatedStepPublic
    )
    assert response.rerun_invalidated_steps[0].operation_id == rerun_operation_id
    assert response.rerun_invalidated_steps[0].dependency_sources_json == [
        "input_bindings.question"
    ]
    assert response.step_results[0].effective_prompt == "Summarize the report"
    assert response.step_results[0].model_parameters_json == {"temperature": 0.2}
    assert response.step_results[0].flow_step_execution_hash == "abc123"
    assert response.result_files[0].file_id == file_id
    assert response.result_files[0].availability == "available"
    assert response.review_checkpoints[0].id == review_checkpoint_id
    assert response.review_checkpoints[0].step_label == "Review summary"
    assert response.review_checkpoints[0].review_mode == FlowStepReviewMode.EDIT
    assert response.review_checkpoints[0].output_type == FlowOutputType.JSON
    assert not hasattr(response.review_checkpoints[0], "step_snapshot_available")
    assert response.review_checkpoints[0].output_contract == review_checkpoint_contract
    assert isinstance(response.debug_export.steps[0].attempts[0], FlowRunDebugAttempt)
    assert response.debug_export.steps[0].attempts[0].response_model == "gpt-4.1-mini"
    assert response.debug_export.steps[0].rag is not None
    assert response.debug_export.steps[0].rag.prompt_context is not None
    assert response.debug_export.steps[0].rag.prompt_context.included_source_ids == [
        "source-1"
    ]
    assert response.debug_export.steps[0].rag.prompt_context.summary is not None
    assert (
        response.debug_export.steps[0].rag.prompt_context.summary["total_sources"] == 1
    )
    assert response.debug_export.steps[
        0
    ].rag.prompt_context.included_source_display_names == ["Beslut till underlag"]


def _flow_run_step_public_payload() -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "flow_run_id": str(uuid4()),
        "flow_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "step_id": str(uuid4()),
        "step_order": 1,
        "status": "completed",
        "error_code": None,
        "created_at": "2026-03-20T12:00:01Z",
        "updated_at": "2026-03-20T12:00:05Z",
    }


def _flow_step_attempt_public_payload() -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "flow_run_id": str(uuid4()),
        "flow_id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "step_id": str(uuid4()),
        "step_order": 1,
        "attempt_no": 1,
        "status": "completed",
        "started_at": "2026-03-20T12:00:00Z",
        "created_at": "2026-03-20T12:00:00Z",
        "updated_at": "2026-03-20T12:00:05Z",
    }


def _flow_run_rerun_operation_public_payload() -> dict[str, object]:
    return {
        "id": str(uuid4()),
        "tenant_id": str(uuid4()),
        "flow_id": str(uuid4()),
        "flow_run_id": str(uuid4()),
        "rerun_step_id": str(uuid4()),
        "rerun_step_order": 1,
        "root_attempt_no": 2,
        "root_attempt_id": None,
        "status": "failed",
        "request_fingerprint": "rerun-fingerprint",
        "expected_run_revision": 1,
        "accepted_run_revision": 2,
        "reason": "Retry the failed step.",
        "input_payload_json": {"question": "Updated input"},
        "input_revision": {"status": "not_recorded"},
        "root_step_input_override_requested": False,
        "requested_by_principal_type": "user",
        "requested_by_user_id": str(uuid4()),
        "failure_code": None,
        "failure_message": None,
        "started_at": "2026-03-20T12:01:00Z",
        "finished_at": "2026-03-20T12:01:05Z",
        "created_at": "2026-03-20T12:01:00Z",
        "updated_at": "2026-03-20T12:01:05Z",
    }


@pytest.mark.parametrize("bad_value", (_MISSING, None), ids=("missing", "none"))
@pytest.mark.parametrize(
    "field_name", ("flow_run_id", "flow_id", "tenant_id", "step_id")
)
def test_flow_run_step_public_requires_runtime_identity_fields(
    field_name: str,
    bad_value: object,
) -> None:
    payload = _flow_run_step_public_payload()
    if bad_value is _MISSING:
        payload.pop(field_name)
    else:
        payload[field_name] = bad_value

    with pytest.raises(ValidationError):
        FlowRunStepPublic.model_validate(payload)


@pytest.mark.parametrize("bad_value", (_MISSING, None), ids=("missing", "none"))
def test_flow_step_attempt_public_requires_step_id(bad_value: object) -> None:
    payload = _flow_step_attempt_public_payload()
    if bad_value is _MISSING:
        payload.pop("step_id")
    else:
        payload["step_id"] = bad_value

    with pytest.raises(ValidationError):
        FlowStepAttemptPublic.model_validate(payload)


def test_flow_run_step_public_exposes_nullable_error_code() -> None:
    payload = _flow_run_step_public_payload()
    payload["status"] = "failed"
    payload["error_code"] = "flow_step_execution_failed"
    payload["error_message"] = "Flow step 1 execution failed."

    step = FlowRunStepPublic.model_validate(payload)

    assert step.error_code == "flow_step_execution_failed"


@pytest.mark.parametrize(
    ("model", "payload_factory", "field_name"),
    [
        (FlowRunStepPublic, _flow_run_step_public_payload, "error_code"),
        (FlowStepAttemptPublic, _flow_step_attempt_public_payload, "error_code"),
        (
            FlowRunRerunOperationPublic,
            _flow_run_rerun_operation_public_payload,
            "failure_code",
        ),
    ],
)
@pytest.mark.parametrize(
    ("raw_code", "expected_code"),
    [
        (None, None),
        (
            FlowApiErrorCode.STEP_EXECUTION_FAILED.value,
            FlowApiErrorCode.STEP_EXECUTION_FAILED.value,
        ),
        (
            FlowApiErrorCode.RUN_RERUN_INVALID_TRANSITION.value,
            FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID.value,
        ),
        ("not_a_flow_error_code", FlowApiErrorCode.RUN_ERROR_PAYLOAD_INVALID.value),
    ],
    ids=("none", "terminal", "cataloged_non_terminal", "uncataloged"),
)
def test_public_terminal_error_code_fields_sanitize_persisted_values(
    model: type[BaseModel],
    payload_factory: Callable[[], dict[str, object]],
    field_name: str,
    raw_code: str | None,
    expected_code: str | None,
) -> None:
    payload = payload_factory()
    payload[field_name] = raw_code

    public_model = model.model_validate(payload)

    assert public_model.model_dump(mode="json")[field_name] == expected_code


def test_flow_run_public_exposes_structured_error_for_failed_runs() -> None:
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    trace_id = uuid4()
    now = datetime.now(timezone.utc)

    run = FlowRunPublic.model_validate(
        {
            "id": run_id,
            "flow_id": flow_id,
            "flow_version": 20,
            "user_id": None,
            "tenant_id": tenant_id,
            "trace_id": trace_id,
            "revision": 1,
            "status": "failed",
            "dispatch_pending_since": now,
            "dispatch_attempt_count": 2,
            "dispatch_last_attempt_at": now,
            "dispatch_last_error": FlowRunDispatchError.from_kind(
                FlowRunDispatchErrorKind.EXECUTION_BACKEND_FAILURE
            ),
            "dispatch_next_attempt_at": None,
            "dispatched_at": now,
            "dispatch_exhausted_at": None,
            "cancelled_at": None,
            "started_at": now,
            "finished_at": now,
            "input_payload_json": None,
            "output_payload_json": None,
            "result_files": [],
            "token_usage": None,
            "error": {
                "schema_version": 1,
                "code": "flow_review_policy_invalid",
                "message": "Step 3 (Analysera bakgrund): review_policy is invalid.",
                "source": "invalid_flow_definition",
                "step_order": 3,
                "details": {"step_description": "Analysera bakgrund"},
            },
            "job_id": None,
            "created_at": now,
            "updated_at": now,
        }
    )

    assert run.error == FlowRunError(
        code="flow_review_policy_invalid",
        message="Step 3 (Analysera bakgrund): review_policy is invalid.",
        source=FlowRunLifecycleSource.INVALID_FLOW_DEFINITION,
        step_order=3,
        details={"step_description": "Analysera bakgrund"},
    )
    assert not hasattr(run, "error_message")


def test_flow_run_public_dispatch_error_is_strict_and_corruption_is_safe() -> None:
    raw_secret = "postgresql://credential@broker"

    invalid = parse_flow_run_dispatch_error(
        {
            "schema_version": 1,
            "kind": "execution_backend_failure",
            "code": "flow_dispatch_failed",
            "retryable": True,
            "message": raw_secret,
        }
    )

    assert invalid is not None
    assert invalid.kind == FlowRunDispatchErrorKind.INVALID_PERSISTED_ERROR
    assert raw_secret not in invalid.message
    with pytest.raises(ValidationError):
        FlowRunDispatchError.model_validate(
            {
                **invalid.model_dump(mode="json"),
                "unexpected": "compatibility is not accepted",
            }
        )
