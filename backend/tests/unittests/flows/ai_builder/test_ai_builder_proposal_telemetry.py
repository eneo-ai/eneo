from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import get_args
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.flows.ai_builder.ai_builder_domain_models import (
    TargetKind,
)
from intric.flows.ai_builder.ai_builder_proposal_telemetry import (
    APPLY_TELEMETRY_LOG_KEY,
    APPLY_TELEMETRY_SCHEMA_VERSION,
    PROPOSAL_TELEMETRY_LOG_KEY,
    PROPOSAL_TELEMETRY_SCHEMA_VERSION,
    ApplyFailureTelemetryPayload,
    ChangesetCountSummary,
    MaterializerProgressSnapshot,
    ProposalFailureKind,
    ProposalRepairReason,
    ProposalTurnTelemetry,
    ToolProcessingFailureKind,
    log_apply_failed,
    log_proposal_first_attempt,
    log_proposal_repair_invoked,
    proposal_repair_reason_from_tool_failure,
)
from intric.flows.ai_builder.ai_builder_tools import PROPOSE_FLOW_TOOL_NAME
from intric.flows.application.flow_authoring_command import FlowAuthoringPreview
from tests.unittests.flows.ai_builder.proposal_turn_test_doubles import _make_usage

_REPO_ROOT = Path(__file__).resolve().parents[5]
_FAILURE_KIND_SOURCE_FILES = (
    _REPO_ROOT / "backend/src/intric/flows/ai_builder/ai_builder_proposal_processor.py",
    _REPO_ROOT / "backend/src/intric/flows/ai_builder/ai_builder_edit_proposal.py",
)


def _tool_processing_failure_kinds_from_source() -> set[str]:
    emitted: set[str] = set()
    for path in _FAILURE_KIND_SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                function_name = func.id
            elif isinstance(func, ast.Attribute):
                function_name = func.attr
            else:
                function_name = None
            if function_name != "ToolProcessingResult":
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "failure_kind"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)
                ):
                    emitted.add(keyword.value.value)
    return emitted


def test_proposal_turn_telemetry_extends_canonical_planner_payload() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-telemetry",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )
    telemetry.record_response(
        finish_reason="tool_calls",
        usage=_make_usage(prompt_tokens=10, completion_tokens=3, total_tokens=13),
    )
    assert telemetry.record_first_attempt(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=False,
        failure_kind="validation",
    )
    telemetry.record_repair_invocation(reason="validation")

    payload = telemetry.build_planner_telemetry(tool_call_count=1)

    assert payload["request_id"] == "req-telemetry"
    assert payload["total_tokens"] == 13
    assert payload["proposal_first_attempt_tool"] == PROPOSE_FLOW_TOOL_NAME
    assert payload["proposal_target_kind"] == TargetKind.CREATE.value
    assert payload["proposal_first_attempt_success"] is False
    assert payload["proposal_first_attempt_failure_kind"] == "validation"
    assert payload["proposal_repair_invocation_count"] == 1
    assert payload["proposal_repair_invocation_reasons"] == ["validation"]


def test_proposal_turn_telemetry_first_attempt_is_first_write_wins() -> None:
    telemetry = ProposalTurnTelemetry(
        request_id="req-first-write",
        model="openai/gpt-5.4-nano",
        target_kind=TargetKind.CREATE,
    )

    assert telemetry.record_first_attempt(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=False,
        failure_kind="missing_submission_tool",
    )
    assert not telemetry.record_first_attempt(
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=True,
    )

    payload = telemetry.build_planner_telemetry()
    assert payload["proposal_first_attempt_success"] is False
    assert payload["proposal_first_attempt_failure_kind"] == "missing_submission_tool"


def test_proposal_repair_reason_maps_tool_failures() -> None:
    assert proposal_repair_reason_from_tool_failure("parse") == "parse"
    assert proposal_repair_reason_from_tool_failure("validation") == "validation"
    assert proposal_repair_reason_from_tool_failure("quality") == "quality"
    assert proposal_repair_reason_from_tool_failure(None) == "validation"


def test_architecture_failure_kind_is_not_a_repair_reason() -> None:
    assert "architecture" in get_args(ProposalFailureKind)
    assert "architecture" not in get_args(ProposalRepairReason)


def test_proposal_first_attempt_log_uses_nested_payload() -> None:
    event_logger = MagicMock()

    log_proposal_first_attempt(
        request_id="req-log",
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=False,
        failure_kind="quality",
        event_logger=event_logger,
    )

    event_logger.info.assert_called_once()
    (message,) = event_logger.info.call_args.args
    assert message == "ai_builder_proposal_first_attempt"
    payload = event_logger.info.call_args.kwargs["extra"][PROPOSAL_TELEMETRY_LOG_KEY]
    assert payload == {
        "event": "ai_builder.proposal.first_attempt",
        "schema_version": PROPOSAL_TELEMETRY_SCHEMA_VERSION,
        "operation": "first_attempt",
        "request_id": "req-log",
        "tool_name": PROPOSE_FLOW_TOOL_NAME,
        "success": False,
        "failure_kind": "quality",
    }


def test_successful_proposal_first_attempt_log_omits_failure_kind() -> None:
    event_logger = MagicMock()

    log_proposal_first_attempt(
        request_id="req-log",
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        success=True,
        failure_kind=None,
        event_logger=event_logger,
    )

    payload = event_logger.info.call_args.kwargs["extra"][PROPOSAL_TELEMETRY_LOG_KEY]
    assert "failure_kind" not in payload


def test_proposal_repair_log_uses_nested_payload() -> None:
    event_logger = MagicMock()

    log_proposal_repair_invoked(
        request_id="req-log",
        tool_name=PROPOSE_FLOW_TOOL_NAME,
        reason="parse",
        event_logger=event_logger,
    )

    event_logger.info.assert_called_once()
    (message,) = event_logger.info.call_args.args
    assert message == "ai_builder_proposal_repair_invoked"
    payload = event_logger.info.call_args.kwargs["extra"][PROPOSAL_TELEMETRY_LOG_KEY]
    assert payload == {
        "event": "ai_builder.proposal.repair_invoked",
        "schema_version": PROPOSAL_TELEMETRY_SCHEMA_VERSION,
        "operation": "repair_invoked",
        "request_id": "req-log",
        "tool_name": PROPOSE_FLOW_TOOL_NAME,
        "reason": "parse",
    }


def test_apply_failure_log_uses_typed_apply_payload() -> None:
    event_logger = MagicMock()
    session_id = uuid4()
    plan_id = uuid4()
    flow_id = uuid4()

    log_apply_failed(
        phase="apply_authoring",
        plan_id=plan_id,
        session_id=session_id,
        target_kind=TargetKind.EDIT,
        flow_id=flow_id,
        exception=BadRequestLike("stale", code="stale_revision"),
        changeset_counts=ChangesetCountSummary(
            steps_created=1,
            steps_updated=2,
            steps_removed=0,
            assistants_to_create=1,
            assistants_to_update=2,
            assistants_to_delete=0,
        ),
        materializer_progress=MaterializerProgressSnapshot(
            stage="flow_updated",
            assistants_created=1,
            assistants_configured=1,
            assistants_updated=2,
            assistants_deleted=0,
            flow_created=False,
            flow_updated=True,
        ),
        event_logger=event_logger,
    )

    event_logger.info.assert_called_once()
    (message,) = event_logger.info.call_args.args
    assert message == "ai_builder_apply_failed"
    payload = event_logger.info.call_args.kwargs["extra"][APPLY_TELEMETRY_LOG_KEY]
    assert payload == {
        "event": "ai_builder.apply.failed",
        "schema_version": APPLY_TELEMETRY_SCHEMA_VERSION,
        "operation": "apply_failed",
        "phase": "apply_authoring",
        "plan_id": str(plan_id),
        "session_id": str(session_id),
        "target_kind": "edit",
        "flow_id": str(flow_id),
        "exception_class": "BadRequestLike",
        "code": "stale_revision",
        "changeset_counts": {
            "steps_created": 1,
            "steps_updated": 2,
            "steps_removed": 0,
            "assistants_to_create": 1,
            "assistants_to_update": 2,
            "assistants_to_delete": 0,
        },
        "materializer_progress": {
            "stage": "flow_updated",
            "assistants_created": 1,
            "assistants_configured": 1,
            "assistants_updated": 2,
            "assistants_deleted": 0,
            "flow_created": False,
            "flow_updated": True,
        },
    }


def test_changeset_count_summary_maps_preview_counts_to_log_projection() -> None:
    preview = FlowAuthoringPreview(
        kind="edit",
        flow_id=uuid4(),
        base_revision=42,
        spec_hash="spec-hash",
        steps_created=1,
        steps_updated=2,
        steps_removed=3,
        assistants_to_create=4,
        assistants_to_update=5,
        assistants_to_delete=6,
        resource_bindings_count=7,
        step_changes=(),
    )

    summary = ChangesetCountSummary.from_preview(preview)

    assert summary.model_dump() == {
        "steps_created": 1,
        "steps_updated": 2,
        "steps_removed": 3,
        "assistants_to_create": 4,
        "assistants_to_update": 5,
        "assistants_to_delete": 6,
    }


def test_compile_apply_failure_payload_omits_execute_only_fields() -> None:
    payload = ApplyFailureTelemetryPayload(
        phase="prepare_authoring",
        plan_id=str(uuid4()),
        session_id=str(uuid4()),
        target_kind="create",
        flow_id=None,
        exception_class="RuntimeError",
        code=None,
        changeset_counts=None,
        materializer_progress=None,
    ).model_dump(exclude_none=True)

    assert payload["phase"] == "prepare_authoring"
    assert "code" not in payload
    assert "changeset_counts" not in payload
    assert "materializer_progress" not in payload


def test_apply_failure_payload_forbids_extra_raw_material_fields() -> None:
    with pytest.raises(ValidationError):
        ApplyFailureTelemetryPayload(
            phase="prepare_authoring",
            plan_id=str(uuid4()),
            session_id=str(uuid4()),
            target_kind="edit",
            flow_id=None,
            exception_class="RuntimeError",
            prompt="raw prompt must not be accepted",
        )


def test_apply_failure_payload_json_excludes_sensitive_material() -> None:
    sensitive_values = [
        "sensitive prompt text",
        "{{ step_a.output.secret }}",
        "raw source transcript",
    ]

    payload = ApplyFailureTelemetryPayload(
        phase="apply_authoring",
        plan_id=str(uuid4()),
        session_id=str(uuid4()),
        target_kind="edit",
        flow_id=str(uuid4()),
        exception_class="RuntimeError",
        code=None,
        changeset_counts=ChangesetCountSummary(
            steps_created=0,
            steps_updated=1,
            steps_removed=0,
            assistants_to_create=0,
            assistants_to_update=1,
            assistants_to_delete=0,
        ),
        materializer_progress=MaterializerProgressSnapshot(
            stage="assistants_updated",
            assistants_created=0,
            assistants_configured=0,
            assistants_updated=1,
            assistants_deleted=0,
            flow_created=False,
            flow_updated=False,
        ),
    ).model_dump_json(exclude_none=True)

    json.loads(payload)
    for value in sensitive_values:
        assert value not in payload


def test_emitted_failure_kinds_are_a_subset_of_the_taxonomy() -> None:
    emitted = _tool_processing_failure_kinds_from_source()

    assert emitted
    assert emitted <= set(get_args(ToolProcessingFailureKind))


class BadRequestLike(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code
