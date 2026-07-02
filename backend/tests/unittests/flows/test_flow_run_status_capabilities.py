from __future__ import annotations

import importlib.util
import types
from dataclasses import fields
from pathlib import Path

import pytest
from pydantic import ValidationError

from eneo.flows.api.flow_run_status_capability_models import (
    FlowRunStatusCapabilitiesPublic,
    FlowRunStatusCapabilityPublic,
    flow_run_status_capabilities_public,
)
from eneo.flows.enums import (
    ACTIVE_FLOW_RUN_STATUSES,
    ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES,
    ACTIVE_FLOW_STEP_RESULT_STATUSES,
    CANCELLABLE_FLOW_RUN_STATUSES,
    FLOW_RUN_STATUS_CAPABILITIES,
    FLOW_RUN_STATUS_FILTER_ORDER,
    OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES,
    OPEN_FLOW_STEP_ATTEMPT_STATUSES,
    RERUN_ELIGIBLE_FLOW_RUN_STATUS_VALUES,
    RERUN_ELIGIBLE_FLOW_RUN_STATUSES,
    TERMINAL_FLOW_RUN_STATUSES,
    FlowRunStatus,
    FlowRunStatusCapability,
    FlowStepAttemptStatus,
    FlowStepResultStatus,
    is_active_flow_run_status,
    is_cancellable_flow_run_status,
    is_terminal_flow_run_status,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = (
    BACKEND_ROOT / "scripts" / "generate_flow_run_status_capabilities_ts.py"
)
SDK_STATUS_CAPABILITIES_JS = (
    BACKEND_ROOT
    / ".."
    / "frontend"
    / "packages"
    / "eneo-js"
    / "src"
    / "flows"
    / "flow-run-status-capabilities.js"
).resolve()
SDK_STATUS_CAPABILITIES_DTS = SDK_STATUS_CAPABILITIES_JS.with_suffix(".d.ts")


def _load_generator_module() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "generate_flow_run_status_capabilities_ts", GENERATOR_PATH
    )
    if spec is None or spec.loader is None:
        pytest.fail(f"Could not load generator module from {GENERATOR_PATH}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_flow_run_status_capabilities_cover_every_status_once() -> None:
    assert set(FLOW_RUN_STATUS_CAPABILITIES) == set(FlowRunStatus)
    assert set(FLOW_RUN_STATUS_FILTER_ORDER) == set(FlowRunStatus)
    assert len(FLOW_RUN_STATUS_FILTER_ORDER) == len(set(FLOW_RUN_STATUS_FILTER_ORDER))


def test_flow_run_status_helpers_are_derived_from_capabilities() -> None:
    assert ACTIVE_FLOW_RUN_STATUSES == {
        FlowRunStatus.QUEUED,
        FlowRunStatus.RUNNING,
    }
    assert TERMINAL_FLOW_RUN_STATUSES == {
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
        FlowRunStatus.CANCELLED,
    }
    for status, capability in FLOW_RUN_STATUS_CAPABILITIES.items():
        assert is_active_flow_run_status(status) is capability.is_active
        assert is_terminal_flow_run_status(status) is capability.is_terminal
        assert is_cancellable_flow_run_status(status) is capability.is_cancellable

    assert CANCELLABLE_FLOW_RUN_STATUSES == {
        status
        for status, capability in FLOW_RUN_STATUS_CAPABILITIES.items()
        if capability.is_cancellable
    }
    assert RERUN_ELIGIBLE_FLOW_RUN_STATUSES == {
        FlowRunStatus.COMPLETED,
        FlowRunStatus.FAILED,
    }
    assert RERUN_ELIGIBLE_FLOW_RUN_STATUS_VALUES == ("completed", "failed")
    assert ACTIVE_FLOW_RUN_STATUSES.isdisjoint(TERMINAL_FLOW_RUN_STATUSES)
    assert ACTIVE_FLOW_RUN_STATUSES | TERMINAL_FLOW_RUN_STATUSES | {
        FlowRunStatus.AWAITING_REVIEW
    } == set(FlowRunStatus)


def test_flow_step_open_work_status_constants_are_explicit() -> None:
    assert ACTIVE_FLOW_STEP_RESULT_STATUSES == {
        FlowStepResultStatus.PENDING,
        FlowStepResultStatus.RUNNING,
    }
    assert ACTIVE_FLOW_STEP_RESULT_STATUS_VALUES == ("pending", "running")
    assert OPEN_FLOW_STEP_ATTEMPT_STATUSES == {
        FlowStepAttemptStatus.STARTED,
        FlowStepAttemptStatus.RETRIED,
    }
    assert OPEN_FLOW_STEP_ATTEMPT_STATUS_VALUES == ("started", "retried")


def test_retried_step_attempt_status_has_no_runtime_writer() -> None:
    source_root = BACKEND_ROOT / "src" / "eneo" / "flows"
    references = [
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*.py")
        if path.name != "enums.py"
        and "FlowStepAttemptStatus.RETRIED" in path.read_text(encoding="utf-8")
    ]

    assert references == []


@pytest.mark.parametrize(
    ("status", "capability"),
    FLOW_RUN_STATUS_CAPABILITIES.items(),
)
def test_flow_run_status_helpers_accept_enum_and_wire_values(
    status: FlowRunStatus,
    capability: FlowRunStatusCapability,
) -> None:
    assert is_active_flow_run_status(status) is capability.is_active
    assert is_terminal_flow_run_status(status) is capability.is_terminal
    assert is_cancellable_flow_run_status(status) is capability.is_cancellable

    assert is_active_flow_run_status(status.value) is capability.is_active
    assert is_terminal_flow_run_status(status.value) is capability.is_terminal
    assert is_cancellable_flow_run_status(status.value) is capability.is_cancellable


def test_flow_run_status_helpers_reject_unknown_wire_values() -> None:
    with pytest.raises(ValueError):
        is_active_flow_run_status("not-a-flow-run-status")


def test_flow_run_status_capabilities_public_contract() -> None:
    payload = flow_run_status_capabilities_public()
    by_status = {item.status: item for item in payload.statuses}

    assert list(by_status) == list(FLOW_RUN_STATUS_CAPABILITIES)
    assert payload.filter_order == list(FLOW_RUN_STATUS_FILTER_ORDER)
    assert by_status[FlowRunStatus.QUEUED].should_poll is True
    assert by_status[FlowRunStatus.QUEUED].can_request_redispatch is True
    assert by_status[FlowRunStatus.AWAITING_REVIEW].is_awaiting_review is True
    assert by_status[FlowRunStatus.COMPLETED].is_terminal is True


def test_flow_run_status_capability_public_fields_stay_explicit_subset() -> None:
    source_fields = {field.name for field in fields(FlowRunStatusCapability)}
    public_fields = set(FlowRunStatusCapabilityPublic.model_fields)

    assert public_fields == source_fields - {"is_rerun_eligible"}
    assert "is_rerun_eligible" not in public_fields


def test_flow_run_status_capabilities_reject_unknown_response_fields() -> None:
    status_capabilities = flow_run_status_capabilities_public()
    payload = status_capabilities.model_dump(mode="json")
    row_payload = status_capabilities.statuses[0].model_dump(mode="json")

    with pytest.raises(ValidationError):
        FlowRunStatusCapabilitiesPublic.model_validate({**payload, "unexpected": True})

    with pytest.raises(ValidationError):
        FlowRunStatusCapabilityPublic.model_validate(
            {**row_payload, "unexpected": True}
        )


def test_checked_in_sdk_status_capabilities_match_backend_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load_generator_module()
    generated_js = tmp_path / "flow-run-status-capabilities.js"
    generated_dts = tmp_path / "flow-run-status-capabilities.d.ts"

    monkeypatch.setattr(generator, "TARGET_JS", generated_js)
    monkeypatch.setattr(generator, "TARGET_DTS", generated_dts)

    generator.main()

    assert generated_js.read_text(
        encoding="utf-8"
    ) == SDK_STATUS_CAPABILITIES_JS.read_text(encoding="utf-8")
    assert generated_dts.read_text(
        encoding="utf-8"
    ) == SDK_STATUS_CAPABILITIES_DTS.read_text(encoding="utf-8")
