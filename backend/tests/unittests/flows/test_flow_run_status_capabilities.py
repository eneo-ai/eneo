from __future__ import annotations

import importlib.util
import types
from pathlib import Path

import pytest

from intric.flows.api.flow_models import flow_run_status_capabilities_public
from intric.flows.enums import (
    CANCELLABLE_FLOW_RUN_STATUSES,
    FLOW_RUN_STATUS_CAPABILITIES,
    FLOW_RUN_STATUS_FILTER_ORDER,
    FlowRunStatus,
    is_active_flow_run_status,
    is_cancellable_flow_run_status,
    is_terminal_flow_run_status,
)

BACKEND_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = BACKEND_ROOT / "scripts" / "generate_flow_run_status_capabilities_ts.py"
SDK_STATUS_CAPABILITIES_JS = (
    BACKEND_ROOT
    / ".."
    / "frontend"
    / "packages"
    / "intric-js"
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
    for status, capability in FLOW_RUN_STATUS_CAPABILITIES.items():
        assert is_active_flow_run_status(status) is capability.is_active
        assert is_terminal_flow_run_status(status) is capability.is_terminal
        assert is_cancellable_flow_run_status(status) is capability.is_cancellable

    assert CANCELLABLE_FLOW_RUN_STATUSES == {
        status
        for status, capability in FLOW_RUN_STATUS_CAPABILITIES.items()
        if capability.is_cancellable
    }


def test_flow_run_status_capabilities_public_contract() -> None:
    payload = flow_run_status_capabilities_public()
    by_status = {item.status: item for item in payload.statuses}

    assert list(by_status) == list(FLOW_RUN_STATUS_CAPABILITIES)
    assert payload.filter_order == list(FLOW_RUN_STATUS_FILTER_ORDER)
    assert by_status[FlowRunStatus.QUEUED].should_poll is True
    assert by_status[FlowRunStatus.QUEUED].can_request_redispatch is True
    assert by_status[FlowRunStatus.AWAITING_REVIEW].is_awaiting_review is True
    assert by_status[FlowRunStatus.COMPLETED].is_terminal is True


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

    assert generated_js.read_text(encoding="utf-8") == SDK_STATUS_CAPABILITIES_JS.read_text(
        encoding="utf-8"
    )
    assert generated_dts.read_text(encoding="utf-8") == SDK_STATUS_CAPABILITIES_DTS.read_text(
        encoding="utf-8"
    )
