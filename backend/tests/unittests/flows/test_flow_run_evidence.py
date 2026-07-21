from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID, uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileType
from eneo.flows.application.flow_run_evidence import (
    build_debug_export,
    normalize_debug_step,
    parse_step_order,
)
from eneo.flows.application.flow_run_evidence_bundle import (
    build_evidence_bundle,
    redact_evidence_bundle,
)
from eneo.flows.application.flow_run_evidence_export_manifest import (
    EVIDENCE_EXPORT_SCHEMA_VERSION,
    EvidenceExportContext,
    EvidenceExportManifest,
)
from eneo.flows.application.flow_run_export_json import render_evidence_json_export
from eneo.flows.domain.flow import (
    FlowPersistedJsonObject,
    FlowRun,
    FlowRunRerunInvalidatedStep,
    FlowRunRerunOperation,
    FlowRunReviewCheckpoint,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
)
from eneo.flows.enums import (
    FlowOutputType,
    FlowRunRerunInvalidationRole,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    RerunDependencyKind,
)
from eneo.flows.flow_retention_tombstone import (
    FLOW_RETENTION_ACTOR_SOURCE,
    FLOW_RETENTION_TOMBSTONES_KEY,
    FlowAttemptRetentionMarker,
    FlowRetentionTombstone,
    GeneratedArtifactRetentionCounts,
    RunDebugAttemptRetentionCounts,
)
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.flow_run_provenance import (
    FLOW_ATTEMPT_PROVENANCE_MARKER_SCHEMA_VERSION,
    FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
    normalize_attempt_provenance,
    normalize_rag_payload,
    parse_attempt_provenance,
)
from eneo.flows.flow_run_step_input_file import FlowRunStepInputFileMetadata
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.flows.published_definition import (
    build_published_definition_json,
    published_definition_checksum,
)
from eneo.main.config import get_settings


def _redacted_export_context() -> EvidenceExportContext:
    return EvidenceExportContext(
        detail_mode="redacted",
        export_reason="support_debug",
        exported_by_user_id="00000000-0000-0000-0000-000000000030",
    )


def _raw_export_context() -> EvidenceExportContext:
    return EvidenceExportContext(
        detail_mode="raw",
        export_reason="regulatory_audit",
        exported_by_user_id="00000000-0000-0000-0000-000000000030",
    )


def _evidence_run_and_version() -> tuple[FlowRun, FlowVersion]:
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "done"},
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    definition_steps: list[FlowPersistedJsonObject] = [
        {
            "step_id": str(uuid4()),
            "step_order": 1,
            "assistant_id": str(uuid4()),
            "input_source": "flow_input",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "text",
        }
    ]
    definition_json = build_published_definition_json(
        flow_id=run.flow_id,
        name="Evidence flow",
        description=None,
        metadata_json=None,
        steps=definition_steps,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum=published_definition_checksum(definition_json),
        definition_json=definition_json,
        created_at=now,
        updated_at=now,
    )
    return run, version


def test_evidence_marks_canonical_snapshot_verified() -> None:
    run, version = _evidence_run_and_version()

    evidence = build_evidence_bundle(
        run=run,
        version=version,
        step_results=[],
        step_attempts=[],
    ).to_dict()

    assert evidence["definition_snapshot"] == version.definition_json
    assert evidence["definition_integrity"] == {
        "status": "verified",
        "expected_checksum": version.definition_checksum,
        "current_checksum": version.definition_checksum,
    }


def test_evidence_integrity_uses_raw_snapshot_before_redaction() -> None:
    run, version = _evidence_run_and_version()
    definition_json: dict[str, object] = {
        "steps": [],
        "metadata_json": {"api_key": "sensitive-value"},
    }
    corrupt_version = version.model_copy(
        update={
            "definition_checksum": "stored-checksum-does-not-match",
            "definition_json": definition_json,
        }
    )

    bundle = build_evidence_bundle(
        run=run,
        version=corrupt_version,
        step_results=[],
        step_attempts=[],
    )
    raw_payload = bundle.to_dict()
    redacted_payload = redact_evidence_bundle(bundle).to_dict()
    expected_integrity = {
        "status": "invalid",
        "expected_checksum": "stored-checksum-does-not-match",
        "current_checksum": published_definition_checksum(definition_json),
    }

    assert bundle.final_output is None
    assert raw_payload["definition_snapshot"] == definition_json
    assert redacted_payload["definition_snapshot"]["metadata_json"] == {
        "api_key": "[REDACTED]"
    }
    assert raw_payload["definition_integrity"] == expected_integrity
    assert redacted_payload["definition_integrity"] == expected_integrity
    assert (
        published_definition_checksum(redacted_payload["definition_snapshot"])
        != expected_integrity["current_checksum"]
    )


def test_evidence_marks_matching_checksum_malformed_snapshot_invalid() -> None:
    run, version = _evidence_run_and_version()
    malformed_definition: dict[str, object] = {
        "schema_version": 1,
        "flow_id": str(run.flow_id),
        "steps": "not-an-array",
    }
    checksum = published_definition_checksum(malformed_definition)
    malformed_version = version.model_copy(
        update={
            "definition_checksum": checksum,
            "definition_json": malformed_definition,
        }
    )

    bundle = build_evidence_bundle(
        run=run,
        version=malformed_version,
        step_results=[],
        step_attempts=[],
    )
    evidence = bundle.to_dict()

    assert bundle.final_output is None
    assert evidence["definition_snapshot"] == malformed_definition
    assert evidence["definition_integrity"] == {
        "status": "invalid",
        "expected_checksum": checksum,
        "current_checksum": checksum,
    }


def test_evidence_marks_matching_checksum_invalid_runtime_step_invalid() -> None:
    run, version = _evidence_run_and_version()
    invalid_definition = build_published_definition_json(
        flow_id=run.flow_id,
        name="Invalid evidence flow",
        description=None,
        metadata_json=None,
        steps=[
            {
                "step_id": str(uuid4()),
                "step_order": 1,
                "assistant_id": str(uuid4()),
                "input_source": "flow_input",
                "input_type": "text",
                "output_mode": "invalid_mode",
                "output_type": "text",
            }
        ],
    )
    checksum = published_definition_checksum(invalid_definition)
    invalid_version = version.model_copy(
        update={
            "definition_checksum": checksum,
            "definition_json": invalid_definition,
        }
    )

    bundle = build_evidence_bundle(
        run=run,
        version=invalid_version,
        step_results=[],
        step_attempts=[],
    )
    evidence = bundle.to_dict()

    assert bundle.final_output is None
    assert evidence["definition_snapshot"] == invalid_definition
    assert evidence["definition_integrity"] == {
        "status": "invalid",
        "expected_checksum": checksum,
        "current_checksum": checksum,
    }


def _attempt_with_provenance(
    run: FlowRun, provenance_json: dict[str, Any] | None
) -> FlowStepAttempt:
    now = datetime.now(timezone.utc)
    return FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        requested_model="gpt-5.4-nano",
        response_model="gpt-5.4-nano",
        provider="openai",
        finish_reason="stop",
        provider_response_id=None,
        num_tokens_input=1,
        num_tokens_output=1,
        provenance_json=provenance_json,
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )


def _attempt_retention_marker_payload(
    run: FlowRun,
    *,
    object_id: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return FlowAttemptRetentionMarker(
        tombstone=FlowRetentionTombstone(
            tenant_id=str(run.tenant_id),
            run_id=str(run.id),
            trace_id=str(run.trace_id),
            data_class="run_debug_evidence",
            object_type="flow_step_attempt",
            object_id=object_id or str(uuid4()),
            policy_source="tenant.flow_settings.retention_policy.run_debug_evidence_days",
            cutoff=now,
            actor_source=FLOW_RETENTION_ACTOR_SOURCE,
            counts=RunDebugAttemptRetentionCounts(cleared_field_count=1),
            timestamp=now,
            retention_state="retention_purged",
        )
    ).to_payload()


def _step_result_retention_tombstone_payload(run: FlowRun) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    tombstone = FlowRetentionTombstone(
        tenant_id=str(run.tenant_id),
        run_id=str(run.id),
        trace_id=str(run.trace_id),
        data_class="generated_artifact",
        object_type="flow_step_result",
        object_id=str(uuid4()),
        policy_source="tenant.flow_settings.retention_policy.generated_artifact_days",
        cutoff=now,
        actor_source=FLOW_RETENTION_ACTOR_SOURCE,
        counts=GeneratedArtifactRetentionCounts(referenced_file_count=1),
        timestamp=now,
        retention_state="artifact_content_purged",
    )
    return {FLOW_RETENTION_TOMBSTONES_KEY: [tombstone.to_payload()]}


def _step_result_for_run(
    run: FlowRun,
    *,
    step_id: UUID | None = None,
    output_payload_json: dict[str, Any] | None = None,
) -> FlowStepResult:
    now = datetime.now(timezone.utc)
    return FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=step_id or uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json=None,
        effective_prompt=None,
        output_payload_json=output_payload_json or {"text": "done"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )


def _review_checkpoint_for_run(
    run: FlowRun,
    *,
    step_id: UUID | None = None,
    step_order: int = 1,
    attempt_no: int = 1,
    state: FlowRunReviewCheckpointState = FlowRunReviewCheckpointState.RESUMED,
    revision: int = 4,
    original_payload_json: dict[str, Any] | None = None,
    current_payload_json: dict[str, Any] | None = None,
    resume_idempotency_key: str | None = "resume-key",
) -> FlowRunReviewCheckpoint:
    now = datetime.now(timezone.utc)
    resolved_step_id = step_id or uuid4()
    requester_user_id = run.principal_user_id
    assert requester_user_id is not None
    return FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=run.tenant_id,
        flow_id=run.flow_id,
        flow_run_id=run.id,
        step_id=resolved_step_id,
        step_order=step_order,
        attempt_no=attempt_no,
        state=state,
        revision=revision,
        schema_version=1,
        original_payload_json=original_payload_json or {"text": "Original"},
        current_payload_json=current_payload_json or {"text": "Reviewed"},
        step_label="Review step",
        review_mode=FlowStepReviewMode.EDIT,
        output_type=FlowOutputType.JSON,
        requester_user_id=requester_user_id,
        requester_principal_type=PrincipalType.USER,
        decided_by_user_id=requester_user_id,
        decided_by_principal_type=PrincipalType.USER,
        next_step_ids_json=[uuid4()],
        resume_idempotency_key=resume_idempotency_key,
        edited_at=now,
        approved_at=now,
        rejected_at=None,
        resumed_at=now if state == FlowRunReviewCheckpointState.RESUMED else None,
        cancelled_at=None,
        created_at=now,
        updated_at=now,
    )


def _result_file_for_run(
    run: FlowRun,
    *,
    step_id: UUID | None = None,
    step_result_id: UUID | None = None,
    step_order: int = 1,
    attempt_no: int = 1,
    file_id: UUID | None = None,
    name: str = "artifact.pdf",
    checksum: str = "artifact-checksum",
    size: int = 4096,
    availability: Literal["available", "content_purged"] = "available",
) -> FlowRunStepResultFile:
    return FlowRunStepResultFile(
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_result_id=step_result_id or uuid4(),
        step_id=step_id or uuid4(),
        step_order=step_order,
        attempt_no=attempt_no,
        file_id=file_id or uuid4(),
        ordinal=0,
        source="declared_artifact",
        name=name,
        checksum=checksum,
        size=size,
        mimetype="application/pdf",
        file_type=FileType.DOCUMENT,
        availability=availability,
    )


def test_verified_final_output_metadata_is_not_serialized_in_evidence_exports() -> None:
    run, version = _evidence_run_and_version()
    raw_bundle = build_evidence_bundle(
        run=run,
        version=version,
        step_results=[],
        step_attempts=[],
    )
    redacted_bundle = redact_evidence_bundle(raw_bundle)

    assert raw_bundle.final_output is not None
    assert raw_bundle.final_output.output_type is FlowOutputType.TEXT
    assert redacted_bundle.final_output == raw_bundle.final_output
    for bundle in (raw_bundle, redacted_bundle):
        payload_with_metadata = json.dumps(
            bundle.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        payload_without_metadata = json.dumps(
            replace(bundle, final_output=None).to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

        assert "final_output" not in bundle.to_dict()
        assert payload_with_metadata == payload_without_metadata


def _input_file_metadata(
    *,
    file_id: UUID,
    name: str,
    checksum: str,
    size: int,
    mimetype: str | None,
    file_type: FileType,
    text_length: int | None = None,
    has_text: bool = False,
    has_transcription: bool = False,
) -> FlowRunStepInputFileMetadata:
    return FlowRunStepInputFileMetadata(
        file_id=file_id,
        name=name,
        checksum=checksum,
        size=size,
        mimetype=mimetype,
        file_type=file_type,
        text_length=text_length,
        has_text=has_text,
        has_transcription=has_transcription,
    )


def _render_raw_export(
    run: FlowRun,
    version: FlowVersion,
    *,
    step_results: list[FlowStepResult] | None = None,
    step_attempts: list[FlowStepAttempt] | None = None,
    result_files: list[FlowRunStepResultFile] | None = None,
    review_checkpoints: list[FlowRunReviewCheckpoint] | None = None,
) -> dict[str, Any]:
    return render_evidence_json_export(
        bundle=build_evidence_bundle(
            run=run,
            version=version,
            step_results=step_results or [],
            step_attempts=step_attempts or [],
            result_files=result_files or [],
            review_checkpoints=review_checkpoints or [],
        ),
        context=_raw_export_context(),
    )


def _evidence_version_with_steps(
    run: FlowRun,
    *,
    step_ids: list[UUID],
) -> FlowVersion:
    now = datetime.now(timezone.utc)
    return FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": str(step_id),
                    "assistant_id": str(uuid4()),
                    "step_order": index,
                    "user_description": f"Steg {index}",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "text",
                }
                for index, step_id in enumerate(step_ids, start=1)
            ]
        },
        created_at=now,
        updated_at=now,
    )


def _evidence_export_content_hash(bundle_payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            bundle_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def test_build_debug_export_uses_latest_evidence_timestamp() -> None:
    run, version = _evidence_run_and_version()
    run_timestamp = datetime(2026, 3, 17, 10, 5, tzinfo=timezone.utc)
    version_timestamp = datetime(2026, 3, 17, 10, 6, tzinfo=timezone.utc)
    result_timestamp = datetime(2026, 3, 17, 10, 7, tzinfo=timezone.utc)
    attempt_timestamp = datetime(2026, 3, 17, 10, 8, tzinfo=timezone.utc)
    operation_timestamp = datetime(2026, 3, 17, 10, 9, tzinfo=timezone.utc)
    invalidation_timestamp = datetime(2026, 3, 17, 10, 10, tzinfo=timezone.utc)
    run = run.model_copy(update={"updated_at": run_timestamp})
    version = version.model_copy(update={"updated_at": version_timestamp})
    result = _step_result_for_run(run).model_copy(
        update={"updated_at": result_timestamp}
    )
    attempt = _attempt_with_provenance(run, {}).model_copy(
        update={"updated_at": attempt_timestamp}
    )
    operation = FlowRunRerunOperation(
        id=uuid4(),
        tenant_id=run.tenant_id,
        flow_id=run.flow_id,
        flow_run_id=run.id,
        rerun_step_id=attempt.step_id or uuid4(),
        rerun_step_order=attempt.step_order,
        root_attempt_no=2,
        root_attempt_id=attempt.id,
        status=FlowRunRerunOperationStatus.COMPLETED,
        request_fingerprint="fingerprint",
        expected_run_revision=1,
        accepted_run_revision=2,
        reason="refresh evidence",
        input_payload_json=None,
        root_step_input_override_requested=False,
        root_step_input_override=None,
        requested_by_principal_type=PrincipalType.USER,
        requested_by_user_id=uuid4(),
        failure_code=None,
        failure_message=None,
        started_at=operation_timestamp,
        finished_at=operation_timestamp,
        created_at=operation_timestamp,
        updated_at=operation_timestamp,
    )
    invalidated_step = FlowRunRerunInvalidatedStep(
        id=uuid4(),
        operation_id=operation.id,
        tenant_id=run.tenant_id,
        flow_id=run.flow_id,
        flow_run_id=run.id,
        step_id=operation.rerun_step_id,
        step_order=operation.rerun_step_order,
        invalidation_order=0,
        role=FlowRunRerunInvalidationRole.ROOT,
        dependency_sources_json=[RerunDependencyKind.INPUT_BINDINGS_QUESTION],
        prior_step_result_id=result.id,
        prior_attempt_id=attempt.id,
        new_attempt_no=2,
        new_attempt_id=attempt.id,
        created_at=invalidation_timestamp,
        updated_at=invalidation_timestamp,
    )

    export = build_debug_export(
        run=run,
        version=version,
        step_results=[result],
        step_attempts=[attempt],
        rerun_operations=[operation],
        rerun_invalidated_steps=[invalidated_step],
    )

    assert export["generated_at"] == invalidation_timestamp.isoformat()


def test_parse_step_order_handles_strings_and_bools():
    assert parse_step_order(" 7 ") == 7
    assert parse_step_order(True, default=9) == 9
    assert parse_step_order("bad", default=5) == 5
    assert parse_step_order(None, default=3) == 3
    assert parse_step_order(7.2, default=4) == 4


def test_normalize_debug_step_uses_rag_metadata():
    step = normalize_debug_step(
        {
            "step_id": "step-1",
            "step_order": 1,
            "assistant_id": "assistant-1",
            "input_source": "flow_input",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "json",
        },
        rag_metadata={"status": "success"},
    )

    assert step["rag"]["status"] == "success"
    assert step["rag"]["tracking"]["retrieval_tracked"] is True


def test_build_debug_export_reads_rag_metadata_from_typed_step_results():
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=2,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=2,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "step_order": 1,
                    "assistant_id": "assistant-1",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                }
            ]
        },
        created_at=now,
        updated_at=now,
    )
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={"rag": {"status": "success", "chunks_retrieved": 3}},
        effective_prompt=None,
        output_payload_json=None,
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )

    export = build_debug_export(run=run, version=version, step_results=[result])

    assert export["definition"]["steps_count"] == 1
    assert export["steps"][0]["rag"]["status"] == "success"
    assert export["steps"][0]["rag"]["chunks_retrieved"] == 3
    assert export["steps"][0]["rag"]["tracking"]["retrieval_tracked"] is True


def test_build_debug_export_handles_empty_steps():
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={"steps": []},
        created_at=now,
        updated_at=now,
    )

    export = build_debug_export(run=run, version=version, step_results=[])

    assert export["steps"] == []
    assert export["definition"]["steps_count"] == 0


def test_normalize_attempt_provenance_truncates_large_text_and_json_payloads():
    normalized = normalize_attempt_provenance(
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "llm": {
                "effective_prompt": "x" * 20000,
                "tool_calls": {
                    "result": "y" * 20000,
                },
            },
        }
    )

    assert normalized is not None
    assert normalized.llm is not None
    assert normalized.llm.effective_prompt is not None
    assert normalized.llm.effective_prompt.truncated is True
    assert normalized.llm.effective_prompt.byte_size > 16000
    assert normalized.llm.effective_prompt.sha256 is not None
    assert normalized.llm.tool_calls is not None
    assert normalized.llm.tool_calls.truncated is True
    assert normalized.llm.tool_calls.sha256 is not None


def test_parse_attempt_provenance_returns_tracked_current_payload() -> None:
    result = parse_attempt_provenance(
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "llm": {"effective_prompt": "Hello"},
        }
    )

    assert result.status == "tracked"
    assert result.provenance is not None
    assert result.marker is None
    payload = result.to_export_payload()
    assert payload is not None
    assert payload["schema_version"] == FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION


def test_parse_attempt_provenance_accepts_attempt_start_section() -> None:
    result = parse_attempt_provenance(
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "attempt_start": {
                "requested_model": "gpt-5.4-nano",
                "provider": "openai",
                "deadline_at": "2026-05-06T08:12:00Z",
                "resolved_timeout_seconds": 1800,
                "effective_prompt_length": 120,
                "input_text_length": 8000,
                "input_tokens_estimate": 2000,
                "model_parameter_snapshot": {
                    "temperature": None,
                    "top_p": None,
                    "reasoning_effort": "high",
                    "verbosity": None,
                },
            },
        }
    )

    assert result.status == "tracked"
    assert result.provenance is not None
    assert result.provenance.attempt_start is not None
    assert result.provenance.attempt_start.resolved_timeout_seconds == 1800
    assert (
        result.provenance.attempt_start.model_parameter_snapshot.reasoning_effort
        == "high"
    )


@pytest.mark.parametrize(
    ("raw", "error_code"),
    [
        (["not", "an", "object"], "flow_attempt_provenance_invalid_type"),
        ({"llm": {}}, "flow_attempt_provenance_schema_version_missing"),
        (
            {"schema_version": "flow-attempt-provenance." + "v0", "llm": {}},
            "flow_attempt_provenance_schema_version_unsupported",
        ),
        (
            {
                "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
                "unexpected": {},
            },
            "flow_attempt_provenance_unknown_top_level_keys",
        ),
    ],
)
def test_parse_attempt_provenance_returns_typed_corruption_marker(
    raw: Any, error_code: str
) -> None:
    result = parse_attempt_provenance(raw)

    assert result.status == "corrupt"
    assert result.provenance is None
    assert result.marker is not None
    assert result.marker.schema_version == FLOW_ATTEMPT_PROVENANCE_MARKER_SCHEMA_VERSION
    assert result.marker.error_code == error_code
    payload = result.to_export_payload()
    assert payload is not None
    assert payload["status"] == "corrupt"


def test_parse_attempt_provenance_rejects_invalid_current_section() -> None:
    result = parse_attempt_provenance(
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "llm": "bad",
        }
    )

    assert result.status == "corrupt"
    assert result.marker is not None
    assert result.marker.error_code == "flow_attempt_provenance_invalid_current_payload"


def test_parse_attempt_provenance_marks_current_schema_validation_failure() -> None:
    result = parse_attempt_provenance(
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "llm": {"effective_prompt": {"preview": "missing required fields"}},
        }
    )

    assert result.status == "corrupt"
    assert result.marker is not None
    assert result.marker.error_code == "flow_attempt_provenance_invalid_current_payload"


def test_parse_attempt_provenance_marks_invalid_retention_marker() -> None:
    result = parse_attempt_provenance(
        {"schema_version": "flow-attempt-retention-marker.v1"}
    )

    assert result.status == "corrupt"
    assert result.marker is not None
    assert (
        result.marker.error_code == "flow_attempt_provenance_invalid_retention_marker"
    )


def test_build_debug_export_adds_rag_source_names_and_run_summary() -> None:
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=2,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=2,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "step_order": 1,
                    "assistant_id": "assistant-1",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                }
            ]
        },
        created_at=now,
        updated_at=now,
    )
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={
            "rag": {
                "attempted": True,
                "status": "success",
                "source_ids": ["source-1", "source-2"],
                "source_ids_short": ["source-1", "source-2"],
                "references": [
                    {
                        "id": "source-1",
                        "id_short": "source-1",
                        "title": "Knowledge A",
                        "matched_chunk_count": 1,
                        "best_score": 0.8,
                        "chunks": [],
                    },
                    {
                        "id": "source-2",
                        "id_short": "source-2",
                        "title": None,
                        "matched_chunk_count": 1,
                        "best_score": 0.7,
                        "chunks": [],
                    },
                ],
            }
        },
        effective_prompt=None,
        output_payload_json=None,
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )

    export = build_debug_export(run=run, version=version, step_results=[result])

    assert export["run"]["summary"]["steps_count"] == 1
    assert export["run"]["summary"]["completed_steps"] == 1
    assert export["steps"][0]["rag"]["source_names"] == ["Knowledge A"]
    assert export["steps"][0]["rag"]["has_named_sources"] is True


def test_build_debug_export_adds_run_token_usage_summary() -> None:
    run, version = _evidence_run_and_version()
    first_attempt = _attempt_with_provenance(run, None).model_copy(
        update={
            "num_tokens_input": 10,
            "num_tokens_output": 4,
        }
    )
    second_attempt = _attempt_with_provenance(run, None).model_copy(
        update={
            "id": uuid4(),
            "attempt_no": 2,
            "num_tokens_input": None,
            "num_tokens_output": 6,
        }
    )

    export = build_debug_export(
        run=run,
        version=version,
        step_attempts=[first_attempt, second_attempt],
    )

    assert export["run"]["summary"]["token_usage"] == {
        "num_tokens_input": 10,
        "num_tokens_output": 10,
        "num_tokens_total": 20,
    }


def test_normalize_rag_payload_adds_prompt_context_display_names_and_usage_state() -> (
    None
):
    normalized = normalize_rag_payload(
        {
            "tracking": {
                "retrieval_tracked": True,
                "prompt_context_inclusion_tracked": True,
                "citation_tracked": False,
                "material_influence_tracked": False,
            },
            "prompt_context": {
                "tracked": True,
                "included_source_ids": ["source-1"],
                "included_groups": [
                    {
                        "source_id": "source-1",
                        "source_title": "https://kunskap.example.se/beslut/underlag",
                        "chunk_count": 2,
                    }
                ],
            },
            "references": [
                {
                    "id": "source-1",
                    "title": "https://kunskap.example.se/beslut/underlag",
                }
            ],
        }
    )

    assert normalized is not None
    assert normalized["references"][0]["usage_state"] == "inserted_into_prompt"
    assert normalized["prompt_context"]["included_source_titles"] == [
        "https://kunskap.example.se/beslut/underlag"
    ]
    assert normalized["prompt_context"]["included_source_display_names"] == [
        "kunskap.example.se/beslut/underlag"
    ]


def test_normalize_rag_payload_derives_reference_match_count_from_display_chunks() -> (
    None
):
    normalized = normalize_rag_payload(
        {
            "references": [
                {
                    "id": "source-1",
                    "id_short": "source-1",
                    "chunks": [
                        {"chunk_no": 1, "score": 0.9, "snippet": "First snippet"},
                        {"chunk_no": 2, "score": 0.7, "snippet": ""},
                        {"chunk_no": 3, "score": 0.6, "snippet": "Third snippet"},
                    ],
                }
            ]
        }
    )

    assert normalized is not None
    reference = normalized["references"][0]
    assert reference["matched_chunk_count"] == 2


def test_render_evidence_json_export_adds_manifest_and_summary() -> None:
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json={"authorization": "Bearer secret-token"},
        output_payload_json={"text": "done"},
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={"steps": []},
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[],
            step_attempts=[],
        )
    )
    export = render_evidence_json_export(
        bundle=bundle, context=_redacted_export_context()
    )

    assert set(export["manifest"]) == {
        "schema_version",
        "app_version",
        "provenance_schema_version_min",
        "provenance_schema_version_current",
        "provenance_persisted_version_status",
        "run_id",
        "tenant_id",
        "flow_id",
        "trace_id",
        "flow_version",
        "content_hash",
        "content_hash_input",
        "exported_at",
        "exported_by_user_id",
        "export_reason",
        "detail_mode",
        "redaction_applied",
        "masked_fields_count",
        "redaction_policy_version",
        "retention_state_summary",
        "artifact_availability_summary",
        "review_checkpoint_summary",
    }
    assert export["schema_version"] == EVIDENCE_EXPORT_SCHEMA_VERSION
    assert export["manifest"]["schema_version"] == export["schema_version"]
    assert export["manifest"]["app_version"] == get_settings().app_version
    assert export["manifest"]["run_id"] == str(run.id)
    assert export["manifest"]["tenant_id"] == str(run.tenant_id)
    assert export["manifest"]["flow_id"] == str(run.flow_id)
    assert export["manifest"]["trace_id"] == str(run.trace_id)
    assert export["manifest"]["flow_version"] == 1
    assert export["manifest"]["content_hash_input"] == "redacted"
    assert export["manifest"]["detail_mode"] == "redacted"
    assert export["manifest"]["export_reason"] == "support_debug"
    assert export["manifest"]["exported_at"] == export["generated_at"]
    assert export["manifest"]["content_hash"] == export["content_hash"]
    assert export["manifest"]["redaction_applied"] is True
    assert isinstance(export["manifest"]["masked_fields_count"], int)
    assert (
        export["manifest"]["redaction_policy_version"] == "flow-evidence-redaction.v3"
    )
    assert export["manifest"]["redaction_applied"] == export["redaction"]["applied"]
    assert (
        export["manifest"]["masked_fields_count"]
        == export["redaction"]["masked_fields_count"]
    )
    assert export["manifest"]["retention_state_summary"] == {
        "tracking_state": "not_tracked",
        "tombstone_count": 0,
        "retention_purged_count": 0,
        "artifact_content_purged_count": 0,
        "redacted_for_deletion_count": 0,
        "note": (
            "No retention tombstones are present in this export; rows purged before "
            "tombstone tracking remain indistinguishable from never-tracked evidence."
        ),
    }
    assert export["manifest"]["artifact_availability_summary"] == {
        "tracking_state": "tracked",
        "artifact_count": 0,
        "available_count": 0,
        "content_purged_count": 0,
        "total_size_bytes": 0,
        "artifacts": [],
        "note": (
            "Artifact availability is derived from result-file rows joined to file "
            "metadata."
        ),
    }
    assert export["manifest"]["review_checkpoint_summary"] == {
        "count": 0,
        "by_state": {
            "awaiting_review": 0,
            "edited": 0,
            "approved": 0,
            "rejected": 0,
            "resumed": 0,
            "cancelled": 0,
            "expired": 0,
        },
        "any_edited": False,
        "any_resumed": False,
        "active_checkpoint_id": None,
        "active_checkpoint_conflict": False,
    }
    assert export["manifest"]["provenance_persisted_version_status"] == "not_tracked"
    assert export["summary"]["status"] == "completed"
    assert export["summary"]["steps_count"] == 0
    assert export["summary"]["artifacts_count"] == 0
    assert export["redaction"]["applied"] is True
    assert export["redaction"]["policy_version"] == "flow-evidence-redaction.v3"
    assert export["redaction"]["masked_fields_count"] >= 1
    assert (
        "bundle.run.input_payload_json.authorization"
        in export["redaction"]["masked_paths"]
    )
    assert export["redaction"]["masked_fields"][0]["reason"] in {
        "sensitive_key",
        "bearer_token",
    }

    serialized_bundle = json.dumps(
        bundle.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert export["content_hash"] == hashlib.sha256(serialized_bundle).hexdigest()


def test_evidence_export_marks_corrupt_attempt_provenance_raw_and_redacted() -> None:
    run, version = _evidence_run_and_version()
    attempt = _attempt_with_provenance(run, {"llm": {"effective_prompt": "Prompt"}})
    raw_bundle = build_evidence_bundle(
        run=run,
        version=version,
        step_results=[],
        step_attempts=[attempt],
    )
    redacted_bundle = redact_evidence_bundle(raw_bundle)

    for export in (
        render_evidence_json_export(bundle=raw_bundle, context=_raw_export_context()),
        render_evidence_json_export(
            bundle=redacted_bundle, context=_redacted_export_context()
        ),
    ):
        marker = export["bundle"]["step_attempts"][0]["provenance_json"]
        assert export["manifest"]["provenance_persisted_version_status"] == "corrupt"
        assert marker["schema_version"] == FLOW_ATTEMPT_PROVENANCE_MARKER_SCHEMA_VERSION
        assert marker["status"] == "corrupt"
        assert marker["error_code"] == "flow_attempt_provenance_schema_version_missing"


def test_evidence_export_manifest_tracks_valid_and_absent_provenance() -> None:
    run, version = _evidence_run_and_version()
    tracked_attempt = _attempt_with_provenance(
        run,
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "llm": {"effective_prompt": "Prompt"},
        },
    )
    absent_attempt = _attempt_with_provenance(run, None)
    bundle = build_evidence_bundle(
        run=run,
        version=version,
        step_results=[],
        step_attempts=[tracked_attempt, absent_attempt],
    )

    export = render_evidence_json_export(bundle=bundle, context=_raw_export_context())

    assert export["manifest"]["provenance_persisted_version_status"] == "tracked"
    assert (
        export["bundle"]["step_attempts"][0]["provenance_json"]["schema_version"]
        == FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION
    )
    assert export["bundle"]["step_attempts"][1]["provenance_json"] is None


def test_attempt_retention_marker_parses_as_retention_purged() -> None:
    run, _version = _evidence_run_and_version()

    result = parse_attempt_provenance(_attempt_retention_marker_payload(run))

    assert result.status == "retention_purged"
    assert result.to_export_payload() is not None
    assert result.to_export_payload()["status"] == "retention_purged"
    assert result.retention_marker is not None
    assert result.retention_marker.tombstone.actor_source == FLOW_RETENTION_ACTOR_SOURCE


def test_evidence_export_manifest_corrupt_precedes_retention_purged() -> None:
    run, version = _evidence_run_and_version()
    corrupt_attempt = _attempt_with_provenance(run, {"rag": {"status": "success"}})
    purged_attempt = _attempt_with_provenance(
        run,
        _attempt_retention_marker_payload(run),
    )

    export = _render_raw_export(
        run,
        version,
        step_attempts=[corrupt_attempt, purged_attempt],
    )

    assert export["manifest"]["provenance_persisted_version_status"] == "corrupt"
    assert export["manifest"]["retention_state_summary"]["tombstone_count"] == 1
    assert (
        export["bundle"]["step_attempts"][1]["provenance_json"]["status"]
        == "retention_purged"
    )


def test_evidence_export_manifest_retention_purged_precedes_tracked() -> None:
    run, version = _evidence_run_and_version()
    tracked_attempt = _attempt_with_provenance(
        run,
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "llm": {"effective_prompt": "Prompt"},
        },
    )
    purged_attempt = _attempt_with_provenance(
        run,
        _attempt_retention_marker_payload(run),
    )

    export = _render_raw_export(
        run,
        version,
        step_attempts=[tracked_attempt, purged_attempt],
    )

    assert (
        export["manifest"]["provenance_persisted_version_status"] == "retention_purged"
    )
    assert (
        export["bundle"]["step_attempts"][0]["provenance_json"]["llm"][
            "effective_prompt"
        ]["preview"]
        == "Prompt"
    )
    assert export["manifest"]["retention_state_summary"]["retention_purged_count"] == 1


def test_evidence_export_retention_summary_counts_payload_tombstones() -> None:
    run, version = _evidence_run_and_version()
    result = _step_result_for_run(
        run,
        output_payload_json=_step_result_retention_tombstone_payload(run),
    )

    first_export = _render_raw_export(run, version, step_results=[result])
    second_export = _render_raw_export(run, version, step_results=[result])

    summary = first_export["manifest"]["retention_state_summary"]
    assert summary == {
        "tracking_state": "tracked",
        "tombstone_count": 1,
        "retention_purged_count": 0,
        "artifact_content_purged_count": 1,
        "redacted_for_deletion_count": 0,
        "note": (
            "Retention tombstones are present: 1 total, 0 retention-purged, "
            "1 artifact-content-purged, 0 redacted-for-deletion."
        ),
    }
    assert (
        second_export["manifest"]["retention_state_summary"]["note"] == summary["note"]
    )


def test_evidence_export_redacted_preserves_retention_marker_fields() -> None:
    run, version = _evidence_run_and_version()
    attempt = _attempt_with_provenance(run, _attempt_retention_marker_payload(run))
    raw_bundle = build_evidence_bundle(
        run=run,
        version=version,
        step_results=[],
        step_attempts=[attempt],
    )
    export = render_evidence_json_export(
        bundle=redact_evidence_bundle(raw_bundle),
        context=_redacted_export_context(),
    )

    marker = export["bundle"]["step_attempts"][0]["provenance_json"]
    assert marker["status"] == "retention_purged"
    assert marker["tombstone"]["actor_source"] == FLOW_RETENTION_ACTOR_SOURCE
    assert marker["tombstone"]["tenant_id"] == str(run.tenant_id)
    assert marker["tombstone"]["run_id"] == str(run.id)
    assert marker["tombstone"]["trace_id"] == str(run.trace_id)
    assert marker["tombstone"]["counts"] == {"cleared_field_count": 1}
    assert not any(
        path.startswith("bundle.step_attempts.0.provenance_json.tombstone")
        for path in export["redaction"]["masked_paths"]
    )


def test_evidence_export_rag_tracking_reports_not_tracked_without_provenance() -> None:
    run, version = _evidence_run_and_version()
    export = _render_raw_export(
        run,
        version,
        step_attempts=[_attempt_with_provenance(run, None)],
    )

    tracking = export["summary"]["rag_usage_tracking"]
    assert tracking["tracking_state"] == "not_tracked"
    assert tracking["retrieval_tracked"] is False
    assert "does not prove knowledge was unused" in tracking["note"]


def test_evidence_export_rag_tracking_reports_tracked_no_sources() -> None:
    run, version = _evidence_run_and_version()
    export = _render_raw_export(
        run,
        version,
        step_attempts=[
            _attempt_with_provenance(
                run,
                {
                    "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
                    "rag": {"status": "success", "references": []},
                },
            )
        ],
    )

    tracking = export["summary"]["rag_usage_tracking"]
    assert tracking["tracking_state"] == "tracked_no_sources"
    assert tracking["retrieval_tracked"] is True
    assert export["summary"]["rag_sources"] == []


def test_evidence_export_rag_tracking_reports_tracked_with_sources() -> None:
    run, version = _evidence_run_and_version()
    export = _render_raw_export(
        run,
        version,
        step_attempts=[
            _attempt_with_provenance(
                run,
                {
                    "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
                    "rag": {
                        "status": "success",
                        "references": [
                            {
                                "id": "source-1",
                                "title": "Knowledge Source",
                                "usage_state": "retrieved_candidate",
                            }
                        ],
                    },
                },
            )
        ],
    )

    assert (
        export["summary"]["rag_usage_tracking"]["tracking_state"]
        == "tracked_with_sources"
    )
    assert export["summary"]["rag_sources"][0]["name"] == "Knowledge Source"


def test_evidence_export_rag_tracking_prefers_sources_over_empty_tracked_rag() -> None:
    run, version = _evidence_run_and_version()
    empty_tracked = _attempt_with_provenance(
        run,
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "rag": {"status": "success", "references": []},
        },
    )
    with_sources = _attempt_with_provenance(
        run,
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "rag": {
                "status": "success",
                "references": [
                    {
                        "id": "source-1",
                        "title": "Knowledge Source",
                        "usage_state": "inserted_into_prompt",
                    }
                ],
            },
        },
    )

    export = _render_raw_export(
        run,
        version,
        step_attempts=[empty_tracked, with_sources],
    )

    assert (
        export["summary"]["rag_usage_tracking"]["tracking_state"]
        == "tracked_with_sources"
    )


def test_evidence_export_rag_tracking_prefers_corrupt_over_tracked_sources() -> None:
    run, version = _evidence_run_and_version()
    tracked = _attempt_with_provenance(
        run,
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "rag": {
                "status": "success",
                "references": [
                    {
                        "id": "source-1",
                        "title": "Knowledge Source",
                        "usage_state": "inserted_into_prompt",
                    }
                ],
            },
        },
    )
    corrupt = _attempt_with_provenance(run, {"rag": {"status": "success"}})

    export = _render_raw_export(
        run,
        version,
        step_attempts=[tracked, corrupt],
    )

    tracking = export["summary"]["rag_usage_tracking"]
    assert tracking["tracking_state"] == "partial_corrupt"
    assert tracking["retrieval_tracked"] is True
    assert export["summary"]["rag_sources"][0]["name"] == "Knowledge Source"


def test_evidence_export_rag_tracking_reports_unknown_for_all_corrupt_attempts() -> (
    None
):
    run, version = _evidence_run_and_version()

    export = _render_raw_export(
        run,
        version,
        step_attempts=[_attempt_with_provenance(run, {"rag": {"status": "success"}})],
    )

    tracking = export["summary"]["rag_usage_tracking"]
    assert tracking["tracking_state"] == "unknown_corrupt"
    assert tracking["retrieval_tracked"] is False
    assert export["summary"]["rag_sources"] == []


def test_evidence_export_rag_tracking_reports_retention_purged_attempts() -> None:
    run, version = _evidence_run_and_version()

    export = _render_raw_export(
        run,
        version,
        step_attempts=[
            _attempt_with_provenance(run, _attempt_retention_marker_payload(run))
        ],
    )

    tracking = export["summary"]["rag_usage_tracking"]
    assert tracking["tracking_state"] == "retention_purged"
    assert tracking["retrieval_tracked"] is False
    assert tracking["retention_purged_attempt_count"] == 1
    assert "does not prove knowledge was unused" in tracking["note"]


def test_evidence_export_rag_tracking_keeps_tracked_state_with_retention_purged() -> (
    None
):
    run, version = _evidence_run_and_version()
    tracked = _attempt_with_provenance(
        run,
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "rag": {
                "status": "success",
                "references": [
                    {
                        "id": "source-1",
                        "title": "Knowledge Source",
                        "usage_state": "retrieved_candidate",
                    }
                ],
            },
        },
    )
    purged = _attempt_with_provenance(run, _attempt_retention_marker_payload(run))

    export = _render_raw_export(run, version, step_attempts=[tracked, purged])

    tracking = export["summary"]["rag_usage_tracking"]
    assert tracking["tracking_state"] == "tracked_with_sources"
    assert tracking["retention_purged_attempt_count"] == 1


def test_evidence_export_rag_tracking_corrupt_and_retention_purged_precedence() -> None:
    run, version = _evidence_run_and_version()
    corrupt = _attempt_with_provenance(run, {"rag": {"status": "success"}})
    purged = _attempt_with_provenance(run, _attempt_retention_marker_payload(run))

    unknown_export = _render_raw_export(
        run,
        version,
        step_attempts=[corrupt, purged],
    )

    assert (
        unknown_export["summary"]["rag_usage_tracking"]["tracking_state"]
        == "unknown_corrupt"
    )
    assert (
        unknown_export["summary"]["rag_usage_tracking"][
            "retention_purged_attempt_count"
        ]
        == 1
    )

    tracked = _attempt_with_provenance(
        run,
        {
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "rag": {"status": "success", "references": []},
        },
    )
    partial_export = _render_raw_export(
        run,
        version,
        step_attempts=[tracked, corrupt, purged],
    )

    assert (
        partial_export["summary"]["rag_usage_tracking"]["tracking_state"]
        == "partial_corrupt"
    )
    assert (
        partial_export["summary"]["rag_usage_tracking"][
            "retention_purged_attempt_count"
        ]
        == 1
    )


def test_evidence_export_includes_review_checkpoint_lineage() -> None:
    run, version = _evidence_run_and_version()
    step_id = uuid4()
    original_payload = {"text": "Model draft", "score": 1}
    reviewed_payload = {"text": "Human reviewed", "score": 2}
    attempt = _attempt_with_provenance(run, None).model_copy(
        update={"step_id": step_id, "output_payload_json": original_payload}
    )
    step_result = _step_result_for_run(
        run,
        step_id=step_id,
        output_payload_json=reviewed_payload,
    )
    checkpoint = _review_checkpoint_for_run(
        run,
        step_id=step_id,
        original_payload_json=original_payload,
        current_payload_json=reviewed_payload,
    )

    export = _render_raw_export(
        run,
        version,
        step_results=[step_result],
        step_attempts=[attempt],
        review_checkpoints=[checkpoint],
    )

    exported_checkpoint = export["bundle"]["review_checkpoints"][0]
    assert exported_checkpoint["original_payload_json"] == original_payload
    assert exported_checkpoint["current_payload_json"] == reviewed_payload
    assert exported_checkpoint["decision"] == "approved"
    assert exported_checkpoint["revision"] == checkpoint.revision
    assert exported_checkpoint["resume_key_present"] is True
    assert "resume_idempotency_key" not in exported_checkpoint
    assert exported_checkpoint["next_step_ids"] == [
        str(step_id) for step_id in checkpoint.next_step_ids_json or []
    ]
    assert export["bundle"]["step_attempts"][0]["output_payload_json"] == (
        original_payload
    )
    assert export["bundle"]["step_results"][0]["output_payload_json"] == (
        reviewed_payload
    )
    assert (
        export["summary"]["review_checkpoints"]
        == (export["manifest"]["review_checkpoint_summary"])
    )
    assert export["summary"]["review_checkpoints"]["count"] == 1
    assert export["summary"]["review_checkpoints"]["by_state"]["resumed"] == 1
    assert export["summary"]["review_checkpoints"]["any_edited"] is True
    assert export["summary"]["review_checkpoints"]["any_resumed"] is True


@pytest.mark.parametrize("redacted", [False, True])
def test_evidence_export_typed_summary_adds_review_impact_without_changing_content_hash(
    redacted: bool,
) -> None:
    run, _ = _evidence_run_and_version()
    step_1_id = uuid4()
    step_2_id = uuid4()
    version = _evidence_version_with_steps(run, step_ids=[step_1_id, step_2_id])
    created_1 = datetime(2026, 5, 17, 8, 0, tzinfo=timezone.utc)
    created_2 = datetime(2026, 5, 17, 8, 1, tzinfo=timezone.utc)
    created_3 = datetime(2026, 5, 17, 8, 2, tzinfo=timezone.utc)
    first_payload = {"text": "Första utkastet"}
    edited_payload = {"text": "Redigerat av granskare"}
    resumed_payload = {"text": "Godkänt och återupptaget"}
    step_results = [
        _step_result_for_run(
            run,
            step_id=step_1_id,
            output_payload_json=resumed_payload,
        ),
        _step_result_for_run(
            run,
            step_id=step_2_id,
            output_payload_json={"text": "Inget granskningssteg"},
        ).model_copy(update={"step_order": 2}),
    ]
    step_attempts = [
        _attempt_with_provenance(run, None).model_copy(
            update={
                "step_id": step_1_id,
                "step_order": 1,
                "attempt_no": 1,
                "created_at": created_1,
                "updated_at": created_1,
            }
        ),
        _attempt_with_provenance(run, None).model_copy(
            update={
                "step_id": step_1_id,
                "step_order": 1,
                "attempt_no": 2,
                "created_at": created_3,
                "updated_at": created_3,
            }
        ),
        _attempt_with_provenance(run, None).model_copy(
            update={
                "step_id": step_2_id,
                "step_order": 2,
                "attempt_no": 1,
            }
        ),
    ]
    checkpoints = [
        _review_checkpoint_for_run(
            run,
            step_id=step_1_id,
            step_order=1,
            attempt_no=1,
            state=FlowRunReviewCheckpointState.REJECTED,
            revision=1,
            original_payload_json=first_payload,
            current_payload_json=first_payload,
            resume_idempotency_key=None,
        ).model_copy(
            update={
                "created_at": created_1,
                "updated_at": created_1,
                "approved_at": None,
                "rejected_at": created_1,
                "resumed_at": None,
            }
        ),
        _review_checkpoint_for_run(
            run,
            step_id=step_1_id,
            step_order=1,
            attempt_no=1,
            state=FlowRunReviewCheckpointState.EDITED,
            revision=1,
            original_payload_json=first_payload,
            current_payload_json=edited_payload,
            resume_idempotency_key=None,
        ).model_copy(
            update={
                "created_at": created_2,
                "updated_at": created_2,
                "approved_at": None,
                "resumed_at": None,
            }
        ),
        _review_checkpoint_for_run(
            run,
            step_id=step_1_id,
            step_order=1,
            attempt_no=2,
            state=FlowRunReviewCheckpointState.RESUMED,
            revision=2,
            original_payload_json=edited_payload,
            current_payload_json=resumed_payload,
            resume_idempotency_key="resume-key-must-not-leak",
        ).model_copy(
            update={
                "created_at": created_3,
                "updated_at": created_3,
                "approved_at": created_3,
                "resumed_at": created_3,
            }
        ),
    ]
    raw_bundle = build_evidence_bundle(
        run=run,
        version=version,
        step_results=step_results,
        step_attempts=step_attempts,
        review_checkpoints=checkpoints,
    )
    export = render_evidence_json_export(
        bundle=redact_evidence_bundle(raw_bundle) if redacted else raw_bundle,
        context=_redacted_export_context() if redacted else _raw_export_context(),
    )

    assert export["content_hash"] == _evidence_export_content_hash(export["bundle"])
    serialized_export = json.dumps(export, sort_keys=True)
    assert "resume-key-must-not-leak" not in serialized_export
    assert "resume_idempotency_key" not in serialized_export

    assert "summary_typed" not in export
    step_1_review = export["summary"]["step_overview"][0]["review_impact"]
    events = step_1_review["events"]
    assert step_1_review["checkpoint_count"] == 3
    assert step_1_review["any_edited"] is True
    assert step_1_review["any_resumed"] is True
    assert step_1_review["any_output_changed"] is True
    assert [event["state"] for event in events] == [
        "rejected",
        "edited",
        "resumed",
    ]
    assert [event["decision"] for event in events] == [
        "rejected",
        None,
        "approved",
    ]
    assert [event["output_changed"] for event in events] == [False, True, True]
    assert step_1_review["last_event"] == events[-1]
    assert step_1_review["last_event"]["attempt_no"] == 2
    assert step_1_review["last_event"]["revision"] == 2

    step_2_review = export["summary"]["step_overview"][1]["review_impact"]
    assert step_2_review == {
        "checkpoint_count": 0,
        "any_edited": False,
        "any_resumed": False,
        "any_output_changed": False,
        "last_event": None,
        "events": [],
    }


@pytest.mark.parametrize("state", list(FlowRunReviewCheckpointState))
def test_evidence_export_typed_summary_maps_review_impact_states(
    state: FlowRunReviewCheckpointState,
) -> None:
    run, _ = _evidence_run_and_version()
    step_id = uuid4()
    version = _evidence_version_with_steps(run, step_ids=[step_id])
    timestamp = datetime(2026, 5, 17, 9, 0, tzinfo=timezone.utc)
    checkpoint = _review_checkpoint_for_run(
        run,
        step_id=step_id,
        step_order=1,
        attempt_no=3,
        state=state,
        revision=7,
        original_payload_json={"text": "original"},
        current_payload_json={"text": "current"},
        resume_idempotency_key=None,
    ).model_copy(
        update={
            "created_at": timestamp,
            "updated_at": timestamp,
            "edited_at": timestamp
            if state == FlowRunReviewCheckpointState.EDITED
            else None,
            "approved_at": timestamp
            if state
            in {
                FlowRunReviewCheckpointState.APPROVED,
                FlowRunReviewCheckpointState.RESUMED,
            }
            else None,
            "rejected_at": timestamp
            if state == FlowRunReviewCheckpointState.REJECTED
            else None,
            "resumed_at": timestamp
            if state == FlowRunReviewCheckpointState.RESUMED
            else None,
            "cancelled_at": timestamp
            if state == FlowRunReviewCheckpointState.CANCELLED
            else None,
            "expired_at": timestamp
            if state == FlowRunReviewCheckpointState.EXPIRED
            else None,
        }
    )

    export = _render_raw_export(
        run,
        version,
        step_results=[
            _step_result_for_run(
                run,
                step_id=step_id,
                output_payload_json={"text": "current"},
            )
        ],
        step_attempts=[
            _attempt_with_provenance(run, None).model_copy(
                update={"step_id": step_id, "step_order": 1, "attempt_no": 3}
            )
        ],
        review_checkpoints=[checkpoint],
    )

    review = export["summary"]["step_overview"][0]["review_impact"]
    event = review["events"][0]
    expected_decision = {
        FlowRunReviewCheckpointState.APPROVED: "approved",
        FlowRunReviewCheckpointState.RESUMED: "approved",
        FlowRunReviewCheckpointState.REJECTED: "rejected",
        FlowRunReviewCheckpointState.CANCELLED: "cancelled",
    }.get(state)
    assert review["checkpoint_count"] == 1
    assert event["state"] == state.value
    assert event["decision"] == expected_decision
    assert event["attempt_no"] == 3
    assert event["revision"] == 7
    assert event["edited"] is (state == FlowRunReviewCheckpointState.EDITED)
    assert event["resumed"] is (state == FlowRunReviewCheckpointState.RESUMED)
    assert event["output_changed"] is True


def test_evidence_export_summary_is_single_typed_contract() -> None:
    run, _ = _evidence_run_and_version()
    step_id = uuid4()
    version = _evidence_version_with_steps(run, step_ids=[step_id])
    export = _render_raw_export(
        run,
        version,
        step_results=[
            _step_result_for_run(
                run,
                step_id=step_id,
                output_payload_json={"text": "done"},
            )
        ],
        step_attempts=[
            _attempt_with_provenance(run, None).model_copy(
                update={"step_id": step_id, "step_order": 1, "attempt_no": 1}
            )
        ],
    )

    assert "summary_typed" not in export

    summary = export["summary"]
    assert set(summary) == {
        "status",
        "trace_id",
        "steps_count",
        "completed_steps",
        "failed_steps",
        "attempts_count",
        "artifacts_count",
        "artifact_names",
        "artifact_details",
        "duration_ms",
        "models_used",
        "rag_sources_count",
        "rag_source_names",
        "rag_source_display_names",
        "rag_sources",
        "rag_usage_tracking",
        "citations",
        "rerun_lineage",
        "review_checkpoints",
        "final_output",
        "step_overview",
    }

    step = summary["step_overview"][0]
    assert set(step) == {
        "step_order",
        "step_id",
        "user_description",
        "status",
        "attempts_count",
        "retries",
        "duration_ms",
        "models_used",
        "knowledge_sources_count",
        "knowledge_usage_state",
        "knowledge_retrieval",
        "citations",
        "artifact_names",
        "artifact_details",
        "result_output_kind",
        "output_summary",
        "input_lineage",
        "configured_input_type",
        "configured_output_type",
        "review_impact",
    }


@pytest.mark.parametrize(
    ("mirror_key", "mirror_value"),
    [
        ("webhook_delivered", False),
        ("webhook_error", "HTTP 503 Service Unavailable"),
    ],
)
def test_evidence_export_ignores_legacy_webhook_delivery_payload_mirror(
    mirror_key: str,
    mirror_value: bool | str,
) -> None:
    run, _ = _evidence_run_and_version()
    step_id = uuid4()
    version = _evidence_version_with_steps(run, step_ids=[step_id])
    output_payload = {"text": "done", mirror_key: mirror_value}
    export = _render_raw_export(
        run.model_copy(update={"output_payload_json": output_payload}),
        version,
        step_results=[
            _step_result_for_run(
                run,
                step_id=step_id,
                output_payload_json=output_payload,
            )
        ],
        step_attempts=[
            _attempt_with_provenance(run, None).model_copy(
                update={"step_id": step_id, "step_order": 1, "attempt_no": 1}
            )
        ],
    )

    assert export["summary"]["final_output"]["kind"] == "text"
    assert export["summary"]["step_overview"][0]["result_output_kind"] == "text"


def test_evidence_export_summary_shared_fields_use_typed_normalization() -> None:
    run, _ = _evidence_run_and_version()
    step_id = uuid4()
    version = _evidence_version_with_steps(run, step_ids=[step_id])
    bundle = build_evidence_bundle(
        run=run,
        version=version,
        step_results=[
            _step_result_for_run(
                run,
                step_id=step_id,
                output_payload_json={"text": "done"},
            )
        ],
        step_attempts=[
            _attempt_with_provenance(run, None).model_copy(
                update={"step_id": step_id, "step_order": 1, "attempt_no": 1}
            )
        ],
    )
    debug_export = dict(bundle.debug_export)
    debug_run = dict(debug_export["run"])
    debug_run["summary"] = {
        "steps_count": "1",
        "completed_steps": True,
        "failed_steps": "0",
        "attempts_count": "1",
        "artifacts_count": "0",
        "duration_ms": "1000",
        "models_used": "gpt-5.4-nano",
    }
    debug_export["run"] = debug_run

    export = render_evidence_json_export(
        bundle=replace(bundle, debug_export=debug_export),
        context=_raw_export_context(),
    )

    for field, expected in {
        "steps_count": 0,
        "completed_steps": 0,
        "failed_steps": 0,
        "attempts_count": 0,
        "duration_ms": None,
        "models_used": [],
    }.items():
        assert export["summary"][field] == expected


def test_evidence_export_review_summary_surfaces_active_checkpoint_conflict() -> None:
    run, version = _evidence_run_and_version()
    awaiting_checkpoint = _review_checkpoint_for_run(
        run,
        state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
        resume_idempotency_key=None,
    ).model_copy(
        update={
            "edited_at": None,
            "approved_at": None,
            "resumed_at": None,
            "decided_by_user_id": None,
            "decided_by_principal_type": None,
        }
    )
    approved_checkpoint = _review_checkpoint_for_run(
        run,
        state=FlowRunReviewCheckpointState.APPROVED,
        resume_idempotency_key=None,
    )

    export = _render_raw_export(
        run,
        version,
        review_checkpoints=[awaiting_checkpoint, approved_checkpoint],
    )

    summary = export["summary"]["review_checkpoints"]
    assert summary["by_state"]["awaiting_review"] == 1
    assert summary["by_state"]["approved"] == 1
    assert summary["active_checkpoint_id"] is None
    assert summary["active_checkpoint_conflict"] is True
    assert export["bundle"]["review_checkpoints"][1]["decision"] == "approved"


def test_evidence_export_redacts_review_checkpoint_payloads_without_resume_key() -> (
    None
):
    run, version = _evidence_run_and_version()
    checkpoint = _review_checkpoint_for_run(
        run,
        original_payload_json={"token": "original-secret"},
        current_payload_json={"api_key": "reviewed-secret"},
        resume_idempotency_key="resume-key-must-not-export",
    )
    raw_bundle = build_evidence_bundle(
        run=run,
        version=version,
        step_results=[],
        step_attempts=[],
        review_checkpoints=[checkpoint],
    )
    export = render_evidence_json_export(
        bundle=redact_evidence_bundle(raw_bundle),
        context=_redacted_export_context(),
    )
    serialized_export = json.dumps(export, sort_keys=True)
    exported_checkpoint = export["bundle"]["review_checkpoints"][0]

    assert "resume-key-must-not-export" not in serialized_export
    assert "resume_idempotency_key" not in serialized_export
    assert exported_checkpoint["resume_key_present"] is True
    assert exported_checkpoint["original_payload_json"]["token"] == "[REDACTED]"
    assert exported_checkpoint["current_payload_json"]["api_key"] == "[REDACTED]"
    assert (
        "bundle.review_checkpoints[0].original_payload_json.token"
        in export["redaction"]["masked_paths"]
    )
    assert (
        "bundle.review_checkpoints[0].current_payload_json.api_key"
        in export["redaction"]["masked_paths"]
    )


def test_evidence_export_manifest_rejects_unknown_fields() -> None:
    payload = {
        "schema_version": EVIDENCE_EXPORT_SCHEMA_VERSION,
        "app_version": get_settings().app_version,
        "provenance_schema_version_min": "flow-attempt-provenance.v1",
        "provenance_schema_version_current": "flow-attempt-provenance.v1",
        "provenance_persisted_version_status": "not_tracked",
        "content_hash": "abc123",
        "content_hash_input": "redacted",
        "exported_at": datetime.now(timezone.utc),
        "tenant_id": str(uuid4()),
        "run_id": str(uuid4()),
        "trace_id": str(uuid4()),
        "flow_id": str(uuid4()),
        "flow_version": 1,
        "exported_by_user_id": str(uuid4()),
        "export_reason": "support_debug",
        "detail_mode": "redacted",
        "redaction_applied": True,
        "masked_fields_count": 1,
        "redaction_policy_version": "flow-evidence-redaction.v3",
        "retention_state_summary": {
            "tracking_state": "not_tracked",
            "tombstone_count": 0,
            "retention_purged_count": 0,
            "artifact_content_purged_count": 0,
            "redacted_for_deletion_count": 0,
            "note": (
                "No retention tombstones are present in this export; rows purged "
                "before tombstone tracking remain indistinguishable from "
                "never-tracked evidence."
            ),
        },
        "artifact_availability_summary": {
            "tracking_state": "tracked",
            "artifact_count": 0,
            "available_count": 0,
            "content_purged_count": 0,
            "total_size_bytes": 0,
            "artifacts": [],
            "note": "Artifact availability is row-backed.",
        },
        "review_checkpoint_summary": {
            "count": 0,
            "by_state": {
                "awaiting_review": 0,
                "edited": 0,
                "approved": 0,
                "rejected": 0,
                "resumed": 0,
                "cancelled": 0,
            },
            "any_edited": False,
            "any_resumed": False,
            "active_checkpoint_id": None,
            "active_checkpoint_conflict": False,
        },
    }

    with pytest.raises(ValueError):
        EvidenceExportManifest.model_validate({**payload, "unexpected": "blocked"})

    payload_without_review_summary = dict(payload)
    payload_without_review_summary.pop("review_checkpoint_summary")
    with pytest.raises(ValueError):
        EvidenceExportManifest.model_validate(payload_without_review_summary)


def test_evidence_export_context_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError):
        EvidenceExportContext.model_validate(
            {
                "detail_mode": "redacted",
                "export_reason": "support_debug",
                "unexpected": "blocked",
            }
        )


def test_render_evidence_json_export_adds_human_readable_rag_and_artifact_summaries() -> (
    None
):
    now = datetime.now(timezone.utc)
    artifact_file_id = uuid4()
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "done"},
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "metadata_json": {
                "ai_builder": {
                    "origin": {
                        "builder_session_id": "builder-session-123",
                    }
                }
            },
            "steps": [],
        },
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[],
            step_attempts=[],
            result_files=[
                _result_file_for_run(
                    run,
                    file_id=artifact_file_id,
                    name="beslut-underlag.pdf",
                )
            ],
        )
    )
    bundle = replace(
        bundle,
        step_attempts=(
            {
                "provenance_json": {
                    "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
                    "rag": {
                        "references": [
                            {
                                "id": "source-1",
                                "title": "https://psykologi.se/psykologilexikon/affekt/",
                                "id_short": "source-1",
                                "chunks": [],
                                "matched_chunk_count": 1,
                                "best_score": 0.9,
                            }
                        ],
                        "source_names": [
                            "https://psykologi.se/psykologilexikon/affekt/"
                        ],
                    },
                }
            },
        ),
    )

    export = render_evidence_json_export(
        bundle=bundle, context=_redacted_export_context()
    )

    assert export["summary"]["artifact_names"] == ["beslut-underlag.pdf"]
    assert export["summary"]["rag_source_names"] == [
        "https://psykologi.se/psykologilexikon/affekt/"
    ]
    assert export["summary"]["rag_source_display_names"] == [
        "psykologi.se/psykologilexikon/affekt"
    ]
    assert (
        export["manifest"]["redaction_policy_version"] == "flow-evidence-redaction.v3"
    )
    assert (
        export["bundle"]["definition_snapshot"]["metadata_json"]["ai_builder"][
            "origin"
        ]["builder_session_id"]
        == "builder-session-123"
    )
    assert (
        "bundle.definition_snapshot.metadata_json.ai_builder.origin.builder_session_id"
        not in export["redaction"]["masked_paths"]
    )


def test_render_evidence_json_export_adds_rag_source_details_and_step_overview() -> (
    None
):
    started_at = datetime.now(timezone.utc)
    finished_at = started_at
    artifact_file_id = uuid4()
    runtime_input_file_id = uuid4()
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=3,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "Beslut till underlag klart."},
        job_id=None,
        created_at=started_at,
        updated_at=finished_at,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=3,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "assistant_id": "assistant-1",
                    "step_order": 1,
                    "user_description": "Sammanfatta underlaget",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                }
            ]
        },
        created_at=started_at,
        updated_at=finished_at,
    )
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={
            "input_source": "flow_input",
            "used_question_binding": False,
            "runtime_input": {
                "file_ids": [str(runtime_input_file_id)],
                "files_count": 1,
                "files": [
                    {
                        "id": str(runtime_input_file_id),
                        "name": "underlag.pdf",
                        "checksum": "input-checksum",
                        "size": 2048,
                        "mimetype": "application/pdf",
                        "file_type": "document",
                        "text_length": 1024,
                        "has_text": True,
                        "has_transcription": False,
                    }
                ],
                "total_file_size": 2048,
                "extracted_text_length": 1024,
                "input_format": "document",
                "capture_mode": "flow_input_files",
            },
        },
        effective_prompt=None,
        output_payload_json={"text": "Beslut till underlag klart."},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=started_at,
        updated_at=finished_at,
    )
    assert result.id is not None
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=result.step_id,
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        requested_model="gpt-4.1-mini",
        response_model="gpt-4.1-mini",
        provider="openai",
        finish_reason="stop",
        provider_response_id="resp_123",
        num_tokens_input=12,
        num_tokens_output=8,
        provenance_json={
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "rag": {
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
                    "version": 2,
                    "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                    "raw_source_count": 1,
                    "raw_chunk_count": 1,
                    "included_source_count": 1,
                    "not_included_source_count": 0,
                    "included_chunk_count": 1,
                    "knowledge_tokens": 144,
                    "truncated_by_token_budget": False,
                    "included_source_ids": ["source-1"],
                    "not_included_source_ids": [],
                    "included_source_titles": ["Beslut till underlag"],
                    "included_groups": [
                        {
                            "source_id": "source-1",
                            "source_id_short": "source-1",
                            "source_title": "Beslut till underlag",
                            "start_chunk": 1,
                            "end_chunk": 1,
                            "chunk_count": 1,
                            "relevance_score": 0.82,
                        }
                    ],
                },
                "references": [
                    {
                        "id": "source-1",
                        "id_short": "source-1",
                        "title": "Beslut till underlag",
                        "source_title": "Beslut till underlag",
                        "source_url": "https://kunskap.example.se/beslut/underlag",
                        "source_kind": "website",
                        "source_container_kind": "website",
                        "source_container_name": "Kunskapsbanken",
                        "source_container_id": "website-1",
                        "usage_state": "inserted_into_prompt",
                        "matched_chunk_count": 1,
                        "best_score": 0.82,
                        "chunks": [],
                    }
                ],
                "unique_sources": 1,
                "source_names": ["Beslut till underlag"],
                "source_display_names": ["Beslut till underlag"],
                "reference_metadata_status": "success",
                "references_truncated": False,
            },
        },
        started_at=started_at,
        finished_at=finished_at,
        created_at=started_at,
        updated_at=finished_at,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[attempt],
            runtime_input_file_ids_by_step_result_id={
                result.id: (runtime_input_file_id,)
            },
            runtime_input_file_metadata_by_step_result_id={
                result.id: (
                    _input_file_metadata(
                        file_id=runtime_input_file_id,
                        name="underlag.pdf",
                        checksum="input-checksum",
                        size=2048,
                        mimetype="application/pdf",
                        file_type=FileType.DOCUMENT,
                        text_length=1024,
                        has_text=True,
                    ),
                )
            },
            result_files=[
                _result_file_for_run(
                    run,
                    step_id=result.step_id,
                    step_result_id=result.id,
                    step_order=1,
                    attempt_no=1,
                    file_id=artifact_file_id,
                    name="beslut-underlag.pdf",
                    checksum="artifact-checksum",
                )
            ],
        )
    )

    export = render_evidence_json_export(
        bundle=bundle, context=_redacted_export_context()
    )

    assert export["summary"]["final_output"]["kind"] == "mixed"
    assert export["summary"]["final_output"]["artifact_names"] == [
        "beslut-underlag.pdf"
    ]
    assert (
        export["summary"]["final_output"]["artifact_details"][0]["checksum"]
        == "artifact-checksum"
    )
    assert (
        export["summary"]["final_output"]["text_preview"]["preview"]
        == "Beslut till underlag klart."
    )
    assert export["summary"]["rag_sources"][0]["source_kind"] == "website"
    assert (
        export["summary"]["rag_sources"][0]["source_container_name"] == "Kunskapsbanken"
    )
    assert (
        export["summary"]["rag_sources"][0]["source_container_display_name"]
        == "Kunskapsbanken"
    )
    assert export["summary"]["rag_sources"][0]["usage_state"] == "inserted_into_prompt"
    assert export["summary"]["rag_usage_tracking"]["retrieval_tracked"] is True
    assert (
        export["summary"]["rag_usage_tracking"]["prompt_context_inclusion_tracked"]
        is True
    )
    assert export["summary"]["rag_usage_tracking"]["citation_tracked"] is False
    assert (
        export["summary"]["step_overview"][0]["user_description"]
        == "Sammanfatta underlaget"
    )
    assert export["summary"]["step_overview"][0]["knowledge_sources_count"] == 1
    assert (
        export["summary"]["step_overview"][0]["knowledge_retrieval"]["status"]
        == "success"
    )
    assert (
        export["summary"]["step_overview"][0]["knowledge_retrieval"]["unique_sources"]
        == 1
    )
    assert export["summary"]["step_overview"][0]["knowledge_retrieval"][
        "prompt_context"
    ]["included_source_display_names"] == ["Beslut till underlag"]
    assert export["summary"]["step_overview"][0]["artifact_names"] == [
        "beslut-underlag.pdf"
    ]
    assert (
        export["summary"]["step_overview"][0]["artifact_details"][0]["checksum"]
        == "artifact-checksum"
    )
    assert export["summary"]["step_overview"][0]["input_lineage"][
        "runtime_file_names"
    ] == ["underlag.pdf"]
    assert export["summary"]["step_overview"][0]["input_lineage"][
        "runtime_file_checksums"
    ] == ["input-checksum"]
    assert (
        export["summary"]["step_overview"][0]["output_summary"]["preview"]
        == "Beslut till underlag klart."
    )


def test_render_evidence_json_export_adds_step_input_lineage_for_upstream_bindings() -> (
    None
):
    now = datetime.now(timezone.utc)
    step_one_file_id = uuid4()
    step_two_file_id = uuid4()
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=2,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "klart"},
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=2,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "assistant_id": "assistant-1",
                    "step_order": 1,
                    "user_description": "Extrahera text",
                    "input_source": "flow_input",
                    "input_type": "document",
                    "output_type": "text",
                },
                {
                    "step_id": "step-2",
                    "assistant_id": "assistant-2",
                    "step_order": 2,
                    "user_description": "Analysera dokumentet",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "json",
                    "input_bindings": {
                        "question": "Analysera med fokus på {{ step_input.text }}",
                        "source_refs": [
                            {
                                "step_ref": "step_1",
                                "output": "text",
                                "label": "Underlag",
                            }
                        ],
                    },
                },
            ]
        },
        created_at=now,
        updated_at=now,
    )
    step_one = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={
            "input_source": "flow_input",
            "used_question_binding": False,
            "runtime_input": {
                "file_ids": [str(step_one_file_id)],
                "files_count": 1,
                "files": [
                    {
                        "id": str(step_one_file_id),
                        "name": "underlag.pdf",
                        "checksum": "input-checksum",
                        "size": 100,
                        "mimetype": "application/pdf",
                        "file_type": "document",
                        "text_length": 50,
                        "has_text": True,
                        "has_transcription": False,
                    }
                ],
                "total_file_size": 100,
                "extracted_text_length": 50,
                "input_format": "document",
                "capture_mode": "flow_input_files",
            },
        },
        effective_prompt=None,
        output_payload_json={"text": "Extraherad text"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )
    step_two = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=2,
        assistant_id=uuid4(),
        input_payload_json={
            "input_source": "previous_step",
            "used_question_binding": True,
            "runtime_input": {
                "file_ids": [str(step_two_file_id)],
                "files_count": 1,
                "files": [
                    {
                        "id": str(step_two_file_id),
                        "name": "frågor.txt",
                        "checksum": "question-checksum",
                        "size": 80,
                        "mimetype": "text/plain",
                        "file_type": "text",
                        "text_length": 30,
                        "has_text": True,
                        "has_transcription": False,
                    }
                ],
                "total_file_size": 80,
                "extracted_text_length": 30,
                "input_format": "document",
                "capture_mode": "runtime_input",
            },
        },
        effective_prompt=None,
        output_payload_json={"structured": {"ok": True}},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )
    assert step_one.id is not None
    assert step_two.id is not None

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[step_one, step_two],
            step_attempts=[],
            runtime_input_file_ids_by_step_result_id={
                step_one.id: (step_one_file_id,),
                step_two.id: (step_two_file_id,),
            },
            runtime_input_file_metadata_by_step_result_id={
                step_one.id: (
                    _input_file_metadata(
                        file_id=step_one_file_id,
                        name="underlag.pdf",
                        checksum="input-checksum",
                        size=100,
                        mimetype="application/pdf",
                        file_type=FileType.DOCUMENT,
                        text_length=50,
                        has_text=True,
                    ),
                ),
                step_two.id: (
                    _input_file_metadata(
                        file_id=step_two_file_id,
                        name="frågor.txt",
                        checksum="question-checksum",
                        size=80,
                        mimetype="text/plain",
                        file_type=FileType.TEXT,
                        text_length=30,
                        has_text=True,
                    ),
                ),
            },
        )
    )

    export = render_evidence_json_export(
        bundle=bundle, context=_redacted_export_context()
    )

    lineage = export["summary"]["step_overview"][1]["input_lineage"]
    assert lineage["input_source"] == "previous_step"
    assert lineage["uses_runtime_input"] is True
    assert lineage["runtime_file_names"] == ["frågor.txt"]
    assert lineage["runtime_file_checksums"] == ["question-checksum"]
    assert lineage["upstream_step_orders"] == [1]
    assert lineage["upstream_step_labels"] == ["Extrahera text"]
    assert lineage["question_binding_references_runtime_input"] is True
    assert lineage["question_binding_expressions"] == [
        "step_input.text",
        "step_1.output.text",
    ]


def test_evidence_input_lineage_recognizes_display_label_alias() -> None:
    run, _ = _evidence_run_and_version()
    version = _evidence_version_with_steps(run, step_ids=[uuid4(), uuid4()])
    steps = version.definition_json["steps"]
    assert isinstance(steps, list)
    first_step = steps[0]
    second_step = steps[1]
    assert isinstance(first_step, dict)
    assert isinstance(second_step, dict)
    first_step["user_description"] = "Collect evidence"
    second_step["input_source"] = "flow_input"
    second_step["input_bindings"] = {
        "question": "Use {{ Collect evidence }}",
    }

    export = _render_raw_export(run, version)

    assert export["summary"]["step_overview"][1]["input_lineage"][
        "upstream_step_orders"
    ] == [1]


def test_evidence_bundle_export_prefers_typed_runtime_input_file_ids() -> None:
    run, _ = _evidence_run_and_version()
    relational_file_id = uuid4()
    stale_payload_file_ids = [str(uuid4()), str(uuid4())]
    result = _step_result_for_run(run).model_copy(
        update={
            "input_payload_json": {
                "input_source": "flow_input",
                "used_question_binding": False,
                "runtime_input": {
                    "file_ids": stale_payload_file_ids,
                    "files_count": len(stale_payload_file_ids),
                    "files": [
                        {
                            "id": stale_payload_file_ids[0],
                            "name": "payload.pdf",
                            "checksum": "payload-checksum",
                            "size": 100,
                            "mimetype": "application/pdf",
                            "file_type": "document",
                        }
                    ],
                    "total_file_size": 100,
                    "input_format": "document",
                },
            }
        }
    )
    version = _evidence_version_with_steps(run, step_ids=[result.step_id])
    assert result.id is not None
    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[],
            runtime_input_file_ids_by_step_result_id={result.id: (relational_file_id,)},
        )
    )

    export = render_evidence_json_export(
        bundle=bundle,
        context=_redacted_export_context(),
    )
    dumped_result = bundle.to_dict()["step_results"][0]
    lineage = export["summary"]["step_overview"][0]["input_lineage"]

    assert dumped_result["runtime_input_file_ids"] == [str(relational_file_id)]
    dumped_runtime_input = dumped_result["input_payload_json"]["runtime_input"]
    assert dumped_runtime_input["file_ids"] == [str(relational_file_id)]
    assert dumped_runtime_input["files_count"] == 1
    assert dumped_runtime_input["files"] == []
    assert dumped_runtime_input["total_file_size"] == 0
    assert lineage == {
        "input_source": "previous_step",
        "used_question_binding": False,
        "uses_runtime_input": True,
        "runtime_input_format": "document",
        "runtime_file_count": 1,
        "runtime_file_ids": [str(relational_file_id)],
        "runtime_file_names": [],
        "runtime_file_checksums": [],
        "runtime_files": [],
        "question_binding_references_runtime_input": False,
        "question_binding_expressions": [],
        "upstream_step_orders": [],
        "upstream_step_labels": [],
    }


def test_evidence_bundle_export_uses_relational_runtime_file_metadata() -> None:
    run, _ = _evidence_run_and_version()
    current_file_id = uuid4()
    stale_file_id = uuid4()
    result = _step_result_for_run(run).model_copy(
        update={
            "input_payload_json": {
                "input_source": "flow_input",
                "used_question_binding": False,
                "runtime_input": {
                    "file_ids": [str(stale_file_id), str(current_file_id)],
                    "files_count": 2,
                    "files": [
                        {
                            "id": str(stale_file_id),
                            "name": "stale.pdf",
                            "checksum": "stale-checksum",
                            "size": 100,
                            "mimetype": "application/pdf",
                            "file_type": "document",
                        },
                        {
                            "id": str(current_file_id),
                            "name": "json-current.pdf",
                            "checksum": "json-current-checksum",
                            "size": 999,
                            "mimetype": "application/pdf",
                            "file_type": "document",
                        },
                    ],
                    "total_file_size": 300,
                    "input_format": "document",
                },
            }
        }
    )
    version = _evidence_version_with_steps(run, step_ids=[result.step_id])
    assert result.id is not None
    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[],
            runtime_input_file_ids_by_step_result_id={result.id: (current_file_id,)},
            runtime_input_file_metadata_by_step_result_id={
                result.id: (
                    _input_file_metadata(
                        file_id=current_file_id,
                        name="current.pdf",
                        checksum="current-checksum",
                        size=200,
                        mimetype="application/pdf",
                        file_type=FileType.DOCUMENT,
                        text_length=80,
                        has_text=True,
                    ),
                )
            },
        )
    )

    export = render_evidence_json_export(
        bundle=bundle,
        context=_redacted_export_context(),
    )
    dumped_result = bundle.to_dict()["step_results"][0]
    dumped_runtime_input = dumped_result["input_payload_json"]["runtime_input"]
    lineage = export["summary"]["step_overview"][0]["input_lineage"]

    expected_file = {
        "id": str(current_file_id),
        "name": "current.pdf",
        "checksum": "current-checksum",
        "size": 200,
        "mimetype": "application/pdf",
        "file_type": "document",
        "text_length": 80,
        "has_text": True,
        "has_transcription": False,
    }
    assert dumped_result["runtime_input_file_ids"] == [str(current_file_id)]
    assert dumped_runtime_input["file_ids"] == [str(current_file_id)]
    assert dumped_runtime_input["files_count"] == 1
    assert dumped_runtime_input["files"] == [expected_file]
    assert dumped_runtime_input["total_file_size"] == 200
    assert lineage["runtime_file_ids"] == [str(current_file_id)]
    assert lineage["runtime_file_count"] == 1
    assert lineage["runtime_file_names"] == ["current.pdf"]
    assert lineage["runtime_file_checksums"] == ["current-checksum"]
    assert lineage["runtime_files"] == [expected_file]


def test_render_evidence_json_export_adds_fallback_container_display_name_and_model_default_semantics() -> (
    None
):
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "klart"},
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={"steps": []},
        created_at=now,
        updated_at=now,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        requested_model="gpt-5.4-nano",
        response_model="gpt-5.4-nano",
        provider="openai",
        finish_reason="stop",
        provider_response_id=None,
        num_tokens_input=1,
        num_tokens_output=1,
        provenance_json={
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "llm": {
                "model_parameters": {
                    "model_id": str(uuid4()),
                    "provider": "openai",
                    "model_name": "gpt-5.4-nano",
                    "temperature": None,
                    "reasoning_effort": None,
                    "verbosity": None,
                    "parameter_semantics": {
                        "temperature": {"mode": "model_default"},
                        "reasoning_effort": {"mode": "model_default"},
                        "verbosity": {"mode": "model_default"},
                    },
                }
            },
            "rag": {
                "status": "success",
                "references": [
                    {
                        "id": "source-1",
                        "title": "https://psykologi.se/terapi/psykoanalys/",
                        "source_url": "https://psykologi.se/terapi/psykoanalys/",
                        "source_kind": "website",
                        "source_container_kind": "website",
                        "source_container_id": "website-1",
                        "usage_state": "retrieved_candidate",
                        "chunks": [],
                        "matched_chunk_count": 1,
                        "best_score": 0.8,
                    }
                ],
            },
        },
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )
    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[],
            step_attempts=[attempt],
        )
    )

    export = render_evidence_json_export(
        bundle=bundle, context=_redacted_export_context()
    )

    assert export["summary"]["rag_sources"][0]["source_container_name"] is None
    assert (
        export["summary"]["rag_sources"][0]["source_container_display_name"]
        == "psykologi.se"
    )
    llm = export["bundle"]["step_attempts"][0]["provenance_json"]["llm"][
        "model_parameters"
    ]
    assert llm["temperature"] is None
    assert llm["reasoning_effort"] is None
    assert llm["verbosity"] is None
    assert llm["parameter_semantics"]["temperature"]["mode"] == "model_default"


def test_render_evidence_json_export_adds_citation_sidecars_and_prompt_context_summary() -> (
    None
):
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={
            "text": 'Slutsats med kallor <inref id="11111111"/><inref id="aaaaaaaa"/>',
            "structured": {"summary": 'Detta styrks av kalla <inref id="22222222"/>'},
        },
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "assistant_id": "assistant-1",
                    "step_order": 1,
                    "user_description": "Analysera underlaget",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "json",
                }
            ]
        },
        created_at=now,
        updated_at=now,
    )
    source_one = "11111111-1111-1111-1111-111111111111"
    source_two = "22222222-2222-2222-2222-222222222222"
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt=None,
        output_payload_json={
            "text": 'Stegsvar <inref id="11111111"/>',
            "structured": {"note": 'Komplettering <inref id="aaaaaaaa"/>'},
        },
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=result.step_id,
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        requested_model="gpt-5.4-nano",
        response_model="gpt-5.4-nano",
        provider="openai",
        finish_reason="stop",
        provider_response_id="resp_123",
        num_tokens_input=10,
        num_tokens_output=12,
        provenance_json={
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "rag": {
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
                    "included_source_count": 2,
                    "not_included_source_count": 0,
                    "included_chunk_count": 3,
                    "knowledge_tokens": 180,
                    "truncated_by_token_budget": False,
                    "included_source_ids": [source_one, source_two],
                    "included_source_titles": ["Kalla ett", "Kalla tva"],
                    "included_groups": [
                        {
                            "source_id": source_one,
                            "source_id_short": "11111111",
                            "source_title": "Kalla ett",
                            "start_chunk": 1,
                            "end_chunk": 2,
                            "chunk_count": 2,
                            "relevance_score": 1.0,
                        },
                        {
                            "source_id": source_two,
                            "source_id_short": "22222222",
                            "source_title": "Kalla tva",
                            "start_chunk": 1,
                            "end_chunk": 1,
                            "chunk_count": 1,
                            "relevance_score": 0.6,
                        },
                    ],
                },
                "references": [
                    {
                        "id": source_one,
                        "id_short": "11111111",
                        "title": "Kalla ett",
                        "usage_state": "inserted_into_prompt",
                        "matched_chunk_count": 2,
                        "best_score": 0.9,
                        "chunks": [],
                    },
                    {
                        "id": source_two,
                        "id_short": "22222222",
                        "title": "Kalla tva",
                        "usage_state": "inserted_into_prompt",
                        "matched_chunk_count": 1,
                        "best_score": 0.7,
                        "chunks": [],
                    },
                ],
            },
        },
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[attempt],
        )
    )
    export = render_evidence_json_export(
        bundle=bundle, context=_redacted_export_context()
    )

    prompt_context_summary = export["summary"]["step_overview"][0][
        "knowledge_retrieval"
    ]["prompt_context"]["summary"]
    assert prompt_context_summary["total_sources"] == 2
    assert prompt_context_summary["total_chunks"] == 3
    assert prompt_context_summary["truncated_by_token_budget"] is False
    assert prompt_context_summary["top_ranked_sources"][0]["source_id"] == source_one
    assert export["summary"]["citations"]["tracking_mode"] == "passive_inline_scan"
    assert export["summary"]["citations"]["citation_mode_requested"] is False
    assert export["summary"]["citations"]["citation_applicable"] is True
    assert export["summary"]["citations"]["citation_context_kind"] == "direct"
    assert export["summary"]["citations"]["citation_expected"] is False
    assert export["summary"]["citations"]["citation_observed"] is True
    assert (
        export["summary"]["citations"]["citation_compliance"]
        == "unknown_citation_ids_present"
    )
    assert export["summary"]["citations"]["cited_source_ids"] == [
        source_one,
        source_two,
    ]
    assert export["summary"]["citations"]["unknown_citation_ids"] == ["aaaaaaaa"]
    assert export["summary"]["citations"]["uncited_inserted_source_ids"] == []
    assert export["summary"]["step_overview"][0]["citations"]["cited_source_ids"] == [
        source_one
    ]
    assert export["summary"]["step_overview"][0]["citations"][
        "unknown_citation_ids"
    ] == ["aaaaaaaa"]
    assert (
        export["summary"]["step_overview"][0]["citations"]["citation_compliance"]
        == "unknown_citation_ids_present"
    )


def test_render_evidence_json_export_uses_provenance_citation_compliance_and_run_level_counts() -> (
    None
):
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "Ren sluttext utan taggar"},
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "assistant_id": "assistant-1",
                    "step_order": 1,
                    "user_description": "Analysera underlaget",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                    "output_config": {"citation_mode": "inline_inref_sidecar"},
                }
            ]
        },
        created_at=now,
        updated_at=now,
    )
    source_one = "11111111-1111-1111-1111-111111111111"
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt=None,
        output_payload_json={"text": "Ren sluttext utan taggar"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=result.step_id,
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        requested_model="gpt-5.4-nano",
        response_model="gpt-5.4-nano",
        provider="openai",
        finish_reason="stop",
        provider_response_id="resp_123",
        num_tokens_input=10,
        num_tokens_output=12,
        provenance_json={
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "rag": {
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
                    "included_source_count": 1,
                    "not_included_source_count": 0,
                    "included_chunk_count": 1,
                    "knowledge_tokens": 80,
                    "truncated_by_token_budget": False,
                    "included_source_ids": [source_one],
                    "included_source_titles": ["Kalla ett"],
                    "included_groups": [],
                },
                "references": [
                    {
                        "id": source_one,
                        "id_short": "11111111",
                        "title": "Kalla ett",
                        "usage_state": "inserted_into_prompt",
                        "chunks": [],
                    }
                ],
            },
            "citations": {
                "tracking_mode": "inline_inref_required",
                "citation_tracked": True,
                "citation_mode_requested": True,
                "citation_applicable": True,
                "citation_context_kind": "direct",
                "citation_expected": True,
                "citation_observed": False,
                "citation_compliance": "missing_required_citations",
                "cited_source_ids": [],
                "cited_source_count": 0,
                "unknown_citation_ids": [],
                "uncited_inserted_source_ids": [source_one],
                "direct_available_source_ids": [source_one],
                "inherited_available_source_ids": [],
                "direct_cited_source_ids": [],
                "inherited_cited_source_ids": [],
                "upstream_grounded_step_orders": [],
            },
            "llm": {
                "raw_completion_text": "Ren sluttext utan taggar",
            },
        },
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[attempt],
        )
    )
    export = render_evidence_json_export(
        bundle=bundle, context=_redacted_export_context()
    )

    assert export["summary"]["citations"]["tracking_mode"] == "inline_inref_required"
    assert export["summary"]["citations"]["citation_mode_requested"] is True
    assert export["summary"]["citations"]["citation_applicable"] is True
    assert export["summary"]["citations"]["citation_context_kind"] == "direct"
    assert export["summary"]["citations"]["citation_expected"] is True
    assert export["summary"]["citations"]["citation_observed"] is False
    assert (
        export["summary"]["citations"]["citation_compliance"]
        == "missing_required_citations"
    )
    assert export["summary"]["citations"]["steps_with_citation_mode_requested"] == 1
    assert export["summary"]["citations"]["steps_with_citations_applicable"] == 1
    assert export["summary"]["citations"]["steps_with_direct_citation_context"] == 1
    assert export["summary"]["citations"]["steps_with_inherited_citation_context"] == 0
    assert export["summary"]["citations"]["steps_with_citations_expected"] == 1
    assert export["summary"]["citations"]["steps_with_citations_observed"] == 0
    assert export["summary"]["citations"]["steps_missing_required_citations"] == 1
    assert export["summary"]["citations"]["steps_with_unknown_citation_ids"] == 0
    assert (
        export["summary"]["step_overview"][0]["citations"]["citation_expected"] is True
    )
    assert (
        export["summary"]["step_overview"][0]["citations"]["citation_compliance"]
        == "missing_required_citations"
    )


def test_render_evidence_json_export_surfaces_inherited_citation_context() -> None:
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "Slutrapport"},
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-2",
                    "assistant_id": "assistant-2",
                    "step_order": 2,
                    "user_description": "Grounded summary",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                },
                {
                    "step_id": "step-3",
                    "assistant_id": "assistant-3",
                    "step_order": 3,
                    "user_description": "Final report",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                    "output_config": {"citation_mode": "inline_inref_sidecar"},
                },
            ]
        },
        created_at=now,
        updated_at=now,
    )
    source_one = "11111111-1111-1111-1111-111111111111"
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=3,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt=None,
        output_payload_json={"text": "Slutrapport"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        flow_step_execution_hash=None,
        created_at=now,
        updated_at=now,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=result.step_id,
        step_order=3,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        requested_model="gpt-5.4-nano",
        response_model="gpt-5.4-nano",
        provider="openai",
        finish_reason="stop",
        provider_response_id="resp_123",
        num_tokens_input=10,
        num_tokens_output=12,
        provenance_json={
            "schema_version": FLOW_ATTEMPT_PROVENANCE_SCHEMA_VERSION,
            "citations": {
                "tracking_mode": "inline_inref_required",
                "citation_tracked": True,
                "citation_mode_requested": True,
                "citation_applicable": True,
                "citation_context_kind": "inherited",
                "citation_expected": True,
                "citation_observed": True,
                "citation_compliance": "observed",
                "cited_source_ids": [source_one],
                "cited_source_count": 1,
                "unknown_citation_ids": [],
                "uncited_inserted_source_ids": [],
                "direct_available_source_ids": [],
                "inherited_available_source_ids": [source_one],
                "direct_cited_source_ids": [],
                "inherited_cited_source_ids": [source_one],
                "upstream_grounded_step_orders": [2],
                "upstream_grounded_step_labels": ["Grounded summary"],
            },
            "llm": {
                "raw_completion_text": 'Slutrapport<inref id="11111111"/>',
            },
        },
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[attempt],
        )
    )
    export = render_evidence_json_export(
        bundle=bundle, context=_redacted_export_context()
    )

    assert export["summary"]["citations"]["citation_context_kind"] == "inherited"
    assert export["summary"]["citations"]["inherited_cited_source_ids"] == [source_one]
    assert export["summary"]["citations"]["upstream_grounded_step_orders"] == [2]
    assert export["summary"]["citations"]["steps_with_inherited_citation_context"] == 1
    assert (
        export["summary"]["step_overview"][1]["citations"]["citation_context_kind"]
        == "inherited"
    )
