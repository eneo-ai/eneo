"""Rows to public models. Pure functions, shared by the services and the API."""

from __future__ import annotations

import json
from typing import Any, Optional, cast
from uuid import UUID

from eneo.database.tables.flow_tables import (
    FlowRunReviewCheckpoints,
    FlowRuns,
    Flows,
    FlowStepResults,
)
from eneo.flows.definition import FlowDefinition, Step, StepKind
from eneo.flows.flow_models import (
    FlowPublic,
    FlowRunErrorPublic,
    FlowRunFilePublic,
    FlowRunPublic,
    FlowRunReviewCheckpointPublic,
    FlowRunStatePublic,
    FlowRunStateStepPublic,
    FlowRunStatus,
    FlowRunStepPublic,
    FlowRunSummaryPublic,
    FlowSparsePublic,
    PrincipalType,
    ReviewCheckpointState,
    StepResultStatus,
)
from eneo.flows.flow_repo import RunFileRow

PREVIEW_CHARS = 300


def definition_to_json(definition: FlowDefinition) -> dict[str, Any]:
    return definition.model_dump(mode="json", by_alias=True)


def definition_from_json(data: dict[str, Any]) -> FlowDefinition:
    return FlowDefinition.model_validate(data)


def flow_public(flow: Flows, *, has_unpublished_changes: bool) -> FlowPublic:
    return FlowPublic(
        id=flow.id,
        space_id=flow.space_id,
        name=flow.name,
        description=flow.description,
        definition=definition_from_json(flow.definition),
        published_version=flow.published_version,
        has_unpublished_changes=has_unpublished_changes,
        conversation_id=flow.conversation_id,
        created_at=flow.created_at,
        updated_at=flow.updated_at,
    )


def flow_sparse_public(flow: Flows, last_run: Optional[FlowRuns]) -> FlowSparsePublic:
    raw_steps = flow.definition.get("steps")
    steps: list[dict[str, Any]] = (
        cast(list[dict[str, Any]], raw_steps) if isinstance(raw_steps, list) else []
    )
    return FlowSparsePublic(
        id=flow.id,
        space_id=flow.space_id,
        name=flow.name,
        description=flow.description,
        published_version=flow.published_version,
        step_count=len(steps),
        step_kinds=[StepKind(step["kind"]) for step in steps if "kind" in step],
        conversation_id=flow.conversation_id,
        last_run=run_summary_public(last_run) if last_run is not None else None,
        created_at=flow.created_at,
        updated_at=flow.updated_at,
    )


def run_error_public(run: FlowRuns) -> Optional[FlowRunErrorPublic]:
    error = run.error_json
    if not error:
        return None
    return FlowRunErrorPublic(
        code=str(error.get("code") or "flow_run_failed"),
        message=str(error.get("message") or ""),
    )


def run_summary_public(run: FlowRuns) -> FlowRunSummaryPublic:
    return FlowRunSummaryPublic(
        id=run.id,
        flow_id=run.flow_id,
        flow_version=run.flow_version,
        tenant_id=run.tenant_id,
        principal_type=PrincipalType(run.principal_type),
        status=FlowRunStatus(run.status),
        run_label=run.run_label,
        job_id=run.job_id,
        started_at=run.started_at,
        finished_at=run.finished_at,
        cancelled_at=run.cancelled_at,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def run_file_public(row: RunFileRow) -> FlowRunFilePublic:
    return FlowRunFilePublic(
        id=row.file_id,
        name=row.name,
        mimetype=row.mimetype,
        size=row.size,
        role=row.role,
        field_key=row.field_key,
        step_id=row.step_id,
    )


def step_public(
    result: FlowStepResults,
    step: Optional[Step],
    files: list[RunFileRow],
) -> FlowRunStepPublic:
    return FlowRunStepPublic(
        step_id=result.step_id,
        key=step.key if step is not None else str(result.step_id),
        name=step.name if step is not None else "",
        kind=StepKind(step.kind) if step is not None else StepKind.COMPOSE,
        step_order=result.step_order,
        status=StepResultStatus(result.status),
        current_attempt_no=result.current_attempt_no,
        input_payload_json=result.input_payload_json,
        output_payload_json=result.output_payload_json,
        result_files=[
            run_file_public(row)
            for row in files
            if row.role == "output" and row.step_id == result.step_id
        ],
        num_tokens_input=result.num_tokens_input,
        num_tokens_output=result.num_tokens_output,
        error_code=result.error_code,
        error_message=result.error_message,
        started_at=result.started_at,
        finished_at=result.finished_at,
    )


def checkpoint_public(
    checkpoint: FlowRunReviewCheckpoints,
) -> FlowRunReviewCheckpointPublic:
    return FlowRunReviewCheckpointPublic(
        id=checkpoint.id,
        flow_id=checkpoint.flow_id,
        flow_run_id=checkpoint.flow_run_id,
        step_id=checkpoint.step_id,
        step_order=checkpoint.step_order,
        attempt_no=checkpoint.attempt_no,
        state=ReviewCheckpointState(checkpoint.state),
        revision=checkpoint.revision,
        review_mode=checkpoint.review_mode,
        output_type=checkpoint.output_type,
        original_payload_json=checkpoint.original_payload_json,
        current_payload_json=checkpoint.current_payload_json,
        requester_principal_type=PrincipalType(checkpoint.requester_principal_type),
        decided_by_principal_type=(
            PrincipalType(checkpoint.decided_by_principal_type)
            if checkpoint.decided_by_principal_type
            else None
        ),
        reason=checkpoint.reason,
        edited_at=checkpoint.edited_at,
        approved_at=checkpoint.approved_at,
        rejected_at=checkpoint.rejected_at,
        resumed_at=checkpoint.resumed_at,
        cancelled_at=checkpoint.cancelled_at,
        expires_at=checkpoint.expires_at,
        created_at=checkpoint.created_at,
        updated_at=checkpoint.updated_at,
    )


def _steps_by_id(definition: FlowDefinition) -> dict[UUID, Step]:
    return {step.id: step for step in definition.steps if step.id is not None}


def run_public(
    run: FlowRuns,
    definition: FlowDefinition,
    files: list[RunFileRow],
    checkpoint: Optional[FlowRunReviewCheckpoints],
) -> FlowRunPublic:
    by_id = _steps_by_id(definition)
    summary = run_summary_public(run)
    return FlowRunPublic(
        **summary.model_dump(),
        input_payload_json=run.input_payload_json,
        output_payload_json=run.output_payload_json,
        error=run_error_public(run),
        input_files=[run_file_public(row) for row in files if row.role == "input"],
        result_files=[run_file_public(row) for row in files if row.role == "output"],
        steps=[
            step_public(result, by_id.get(result.step_id), files)
            for result in sorted(run.step_results, key=lambda r: r.step_order)
        ],
        review_checkpoint=checkpoint_public(checkpoint) if checkpoint else None,
    )


def output_preview(
    payload: Optional[dict[str, Any]], step_files: list[RunFileRow]
) -> Optional[str]:
    """A bounded look at a step's output: first characters, or file names."""
    names = [row.name for row in step_files]
    if names:
        return ", ".join(names)[:PREVIEW_CHARS]
    if not payload:
        return None
    text = payload.get("text")
    if text is None and payload.get("value") is not None:
        text = json.dumps(payload["value"], ensure_ascii=False)
    if not text:
        return None
    text = str(text)
    return text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 1] + "…"


def run_state_public(
    run: FlowRuns,
    definition: FlowDefinition,
    files: list[RunFileRow],
    checkpoint: Optional[FlowRunReviewCheckpoints],
) -> FlowRunStatePublic:
    by_id = _steps_by_id(definition)
    steps: list[FlowRunStateStepPublic] = []
    for result in sorted(run.step_results, key=lambda r: r.step_order):
        step = by_id.get(result.step_id)
        step_files = [
            row
            for row in files
            if row.role == "output" and row.step_id == result.step_id
        ]
        steps.append(
            FlowRunStateStepPublic(
                step_id=result.step_id,
                key=step.key if step else str(result.step_id),
                name=step.name if step else "",
                kind=StepKind(step.kind) if step else StepKind.COMPOSE,
                status=StepResultStatus(result.status),
                preview=output_preview(result.output_payload_json, step_files),
                error_message=result.error_message,
            )
        )
    return FlowRunStatePublic(
        flow_id=run.flow_id,
        run_id=run.id,
        flow_version=run.flow_version,
        status=FlowRunStatus(run.status),
        run_label=run.run_label,
        steps=steps,
        review_checkpoint=checkpoint_public(checkpoint) if checkpoint else None,
        output_files=[run_file_public(row) for row in files if row.role == "output"],
        error=run_error_public(run),
        created_at=run.created_at,
        updated_at=run.updated_at,
    )
