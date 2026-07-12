"""Shared support for Flow router tests split by API surface.

Kept in this file because T005 did not allow adding a dedicated support module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks

from eneo.authentication.auth_dependencies import ScopeFilter
from eneo.authentication.principal_types import PrincipalType
from eneo.files.file_models import FileType
from eneo.flows.api import flow_access_context as flow_access_context_module
from eneo.flows.domain.flow import (
    Flow,
    FlowRun,
    FlowRunReviewCheckpoint,
    FlowRunStatus,
    FlowStep,
)
from eneo.flows.enums import FlowRunRerunOperationStatus, FlowRunReviewCheckpointState
from eneo.flows.flow_review_policy import FlowStepReviewMode
from eneo.flows.flow_run_evidence_export_manifest import (
    EvidenceReviewCheckpointSummary,
)
from eneo.flows.flow_run_step_result_file import FlowRunStepResultFile
from eneo.main.exceptions import (
    UnauthorizedException,
)
from eneo.roles.permissions import Permission


def _flow_step(step_id, step_order: int) -> FlowStep:
    return FlowStep(
        id=step_id,
        assistant_id=uuid4(),
        step_order=step_order,
        user_description=f"Step {step_order}",
        input_source="flow_input" if step_order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="json",
    )


def _flow(flow_id):
    now = datetime.now(timezone.utc)
    return Flow(
        id=flow_id,
        tenant_id=uuid4(),
        space_id=uuid4(),
        name="Flow",
        description=None,
        created_by_user_id=uuid4(),
        owner_user_id=uuid4(),
        published_version=1,
        metadata_json=None,
        data_retention_days=None,
        created_at=now,
        updated_at=now,
        steps=[_flow_step(uuid4(), 1)],
    )


def _run(flow_id, tenant_id):
    now = datetime.now(timezone.utc)
    return FlowRun(
        id=uuid4(),
        flow_id=flow_id,
        flow_version=1,
        principal_type=PrincipalType.USER,
        principal_user_id=uuid4(),
        tenant_id=tenant_id,
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )


def _review_checkpoint(
    *,
    flow_id,
    run_id,
    tenant_id,
    step_id,
    revision: int = 2,
) -> FlowRunReviewCheckpoint:
    now = datetime.now(timezone.utc)
    return FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=tenant_id,
        flow_id=flow_id,
        flow_run_id=run_id,
        step_id=step_id,
        step_order=1,
        attempt_no=1,
        state=FlowRunReviewCheckpointState.RESUMED,
        revision=revision,
        original_payload_json={"text": "draft"},
        current_payload_json={"text": "reviewed"},
        step_label="Review step",
        review_mode=FlowStepReviewMode.EDIT,
        output_type="json",
        requester_principal_type=PrincipalType.USER,
        decided_by_principal_type=PrincipalType.USER,
        created_at=now,
        updated_at=now,
    )


def _rerun_result(
    run: FlowRun,
    step_id,
    *,
    created=True,
    status=FlowRunRerunOperationStatus.QUEUED,
    invalidated_step_ids=None,
):
    invalidated_ids = tuple(invalidated_step_ids or (step_id,))
    return SimpleNamespace(
        operation=SimpleNamespace(
            id=uuid4(),
            rerun_step_id=step_id,
            root_attempt_no=2,
            status=status,
        ),
        run=run,
        invalidated_steps=tuple(
            SimpleNamespace(step_id=invalidated_id)
            for invalidated_id in invalidated_ids
        ),
        created=created,
    )


def _result_file(*, run: FlowRun, step_result_id=None) -> FlowRunStepResultFile:
    return FlowRunStepResultFile(
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_result_id=step_result_id or uuid4(),
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        file_id=uuid4(),
        ordinal=0,
        source="declared_artifact",
        name="summary.pdf",
        checksum="checksum",
        size=14012,
        mimetype="application/pdf",
        file_type=FileType.DOCUMENT,
        availability="available",
    )


def _evidence_export_payload(run: FlowRun) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()
    content_hash = "abc123"
    exported_by_user_id = run.principal_user_id
    assert exported_by_user_id is not None
    review_checkpoint_summary = EvidenceReviewCheckpointSummary(
        count=0,
        by_state={state: 0 for state in FlowRunReviewCheckpointState},
        any_edited=False,
        any_resumed=False,
        active_checkpoint_id=None,
        active_checkpoint_conflict=False,
    )
    review_checkpoint_summary_payload = review_checkpoint_summary.model_dump(
        mode="json"
    )
    return {
        "schema_version": "flow-evidence-export.v8",
        "generated_at": generated_at,
        "content_hash": content_hash,
        "manifest": {
            "schema_version": "flow-evidence-export.v8",
            "app_version": "DEV",
            "provenance_schema_version_min": "flow-attempt-provenance.v1",
            "provenance_schema_version_current": "flow-attempt-provenance.v1",
            "provenance_persisted_version_status": "not_tracked",
            "run_id": str(run.id),
            "tenant_id": str(run.tenant_id),
            "flow_id": str(run.flow_id),
            "trace_id": str(run.trace_id),
            "flow_version": run.flow_version,
            "content_hash": content_hash,
            "content_hash_input": "redacted",
            "exported_at": generated_at,
            "exported_by_user_id": str(exported_by_user_id),
            "export_reason": "support_debug",
            "detail_mode": "redacted",
            "redaction_applied": True,
            "masked_fields_count": 0,
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
            "review_checkpoint_summary": review_checkpoint_summary_payload,
        },
        "summary": {
            "status": run.status.value,
            "trace_id": str(run.trace_id),
            "steps_count": 0,
            "completed_steps": 0,
            "failed_steps": 0,
            "attempts_count": 0,
            "artifacts_count": 0,
            "artifact_names": [],
            "artifact_details": [],
            "duration_ms": None,
            "models_used": [],
            "rag_sources_count": 0,
            "rag_source_names": [],
            "rag_source_display_names": [],
            "rag_sources": [],
            "rag_usage_tracking": {},
            "citations": {},
            "rerun_lineage": {
                "operations_count": 0,
                "queued_operations_count": 0,
                "running_operations_count": 0,
                "completed_operations_count": 0,
                "failed_operations_count": 0,
                "cancelled_operations_count": 0,
                "active_operations_count": 0,
                "terminal_operations_count": 0,
                "invalidated_steps_count": 0,
                "completed_replacement_count": 0,
            },
            "review_checkpoints": review_checkpoint_summary_payload,
            "final_output": {
                "kind": "empty",
                "text_present": False,
                "text_preview": None,
                "structured_present": False,
                "artifact_count": 0,
                "artifact_names": [],
                "artifact_details": [],
            },
            "step_overview": [],
        },
        "redaction": {
            "applied": True,
            "policy_version": "flow-evidence-redaction.v3",
            "masked_fields_count": 0,
            "masked_paths": [],
            "masked_fields": [],
        },
        "bundle": {
            "run": run.model_dump(mode="json"),
            "definition_snapshot": {"steps": []},
            "step_results": [],
            "step_attempts": [],
            "result_files": [],
            "debug_export": {
                "schema_version": "eneo.flow.debug-export.v2",
                "generated_at": generated_at,
                "run": {
                    "run_id": str(run.id),
                    "flow_id": str(run.flow_id),
                    "flow_version": run.flow_version,
                    "trace_id": str(run.trace_id),
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
        },
    }


def _enable_space_access(
    container,
    *,
    can_read=True,
    can_create=True,
    can_edit=True,
    can_delete=True,
    can_publish=True,
    user_permissions=None,
):
    """Set up space_service + actor_manager mocks so space checks pass."""
    if (
        getattr(container.session.return_value, "_is_explicit_tx_test_session", False)
        is not True
    ):
        _enable_explicit_transaction(container)
    space_service = AsyncMock()
    container.space_service.return_value = space_service
    actor = MagicMock()
    actor.can_read_flows.return_value = can_read
    actor.can_read_flow.return_value = can_read
    actor.can_create_flows.return_value = can_create
    actor.can_edit_flows.return_value = can_edit
    actor.can_delete_flows.return_value = can_delete
    actor.can_publish_flows.return_value = can_publish
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = actor
    container.actor_manager.return_value = actor_manager
    user = getattr(container.user, "return_value", None)
    if user is not None:
        user.permissions = list(
            [Permission.FLOWS] if user_permissions is None else user_permissions
        )
    return actor


class _RecordingAsyncTransaction:
    def __init__(self, events: list[str] | None = None):
        self.events = events

    async def __aenter__(self):
        if self.events is not None:
            self.events.append("transaction_enter")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.events is not None:
            self.events.append("transaction_exit")
        return False


def _enable_explicit_transaction(container, events: list[str] | None = None):
    session = SimpleNamespace(
        _is_explicit_tx_test_session=True,
        begin=MagicMock(return_value=_RecordingAsyncTransaction(events)),
    )
    container.session.return_value = session
    return session


class _RecordingBackgroundTasks(BackgroundTasks):
    def __init__(self, events: list[str]):
        super().__init__()
        self.events = events

    def add_task(self, func, *args, **kwargs):
        self.events.append("add_task")
        return super().add_task(func, *args, **kwargs)


@dataclass(frozen=True)
class _ReviewCheckpointRouteContext:
    flow_id: UUID
    run: FlowRun
    checkpoint: FlowRunReviewCheckpoint
    events: list[str]
    run_service: AsyncMock
    review_service: AsyncMock


def _enable_review_checkpoint_route_context(container) -> _ReviewCheckpointRouteContext:
    flow_id = uuid4()
    step_id = uuid4()
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    run = _run(flow_id=flow_id, tenant_id=user.tenant_id)
    checkpoint = _review_checkpoint(
        flow_id=flow_id,
        run_id=run.id,
        tenant_id=user.tenant_id,
        step_id=step_id,
    )
    events: list[str] = []

    run_service = AsyncMock()
    review_service = AsyncMock()
    flow_service = AsyncMock()
    flow_service.get_flow.return_value = _flow(flow_id)
    container.flow_run_service.return_value = run_service
    container.flow_run_review_checkpoint_service.return_value = review_service
    container.flow_service.return_value = flow_service
    container.user.return_value = user
    _enable_space_access(container)
    _enable_explicit_transaction(container, events)

    return _ReviewCheckpointRouteContext(
        flow_id=flow_id,
        run=run,
        checkpoint=checkpoint,
        events=events,
        run_service=run_service,
        review_service=review_service,
    )


def _disable_flow_scope_filter(monkeypatch):
    monkeypatch.setattr(
        flow_access_context_module,
        "get_scope_filter",
        lambda _request: ScopeFilter(space_id=None),
    )


def _request():
    return SimpleNamespace(state=SimpleNamespace())


def _assert_scope_mismatch(
    exc_info: pytest.ExceptionInfo[UnauthorizedException],
    *,
    message: str | None = None,
) -> None:
    error = exc_info.value
    if message is not None:
        assert str(error) == message
    assert error.code == "insufficient_scope"
    assert error.context == {"auth_layer": "api_key_scope"}


def _user() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), permissions=[Permission.FLOWS]
    )


def _service_key() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        service_principal_id=uuid4(),
        ownership="service",
        name="Flow service key",
        key_prefix="sk_test",
    )
