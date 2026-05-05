from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


def load_live_eval_runner() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[5]
    runner_path = (
        repo_root / "docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py"
    )
    spec = importlib.util.spec_from_file_location(
        "flow_ai_builder_live_eval", runner_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_parse_builder_stream_extracts_json_events_and_ignores_comments() -> None:
    runner = load_live_eval_runner()

    events = runner.parse_builder_stream(
        b": ping\n\n"
        b"event: status\r\n"
        b'data: {"status":"architecture_committed"}\r\n\r\n'
        b"event: done\r\n"
        b"data: \r\n\r\n"
    )

    assert [event.event for event in events] == ["status", "done"]
    assert events[0].data == {"status": "architecture_committed"}
    assert events[1].data is None


def test_stream_requirements_version_reads_requirements_summary() -> None:
    runner = load_live_eval_runner()
    events = runner.parse_builder_stream(
        b"event: status\n"
        b'data: {"status":"architecture_committed"}\n\n'
        b"event: requirements_summary\n"
        b'data: {"requirements_version":"abc123","summary":"ok"}\n\n'
    )

    assert runner.stream_requirements_version(events) == "abc123"


def test_stream_error_messages_include_code_and_message() -> None:
    runner = load_live_eval_runner()
    events = runner.parse_builder_stream(
        b"event: error\n"
        b'data: {"code":"self_correction_invalid_plan",'
        b'"message":"Plan still invalid after correction."}\n\n'
    )

    assert runner.stream_error_messages(events) == [
        "self_correction_invalid_plan: Plan still invalid after correction."
    ]


def test_stream_has_question_checks_combined_rounds() -> None:
    runner = load_live_eval_runner()
    initial_events = runner.parse_builder_stream(
        b'event: requirements_summary\ndata: {"requirements_version":"abc123"}\n\n'
    )
    confirmation_events = runner.parse_builder_stream(
        b'event: question\ndata: {"question_id":"final_output_mode"}\n\n'
    )

    assert runner.stream_has_question(initial_events + confirmation_events) is True


def test_publish_mode_fetches_run_contract_after_publish(tmp_path: Path) -> None:
    runner = load_live_eval_runner()

    class FakeClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def post_stream(self, path: str, payload: dict[str, Any]) -> bytes:
            self.calls.append(("POST_STREAM", path))
            return b'event: status\ndata: {"status":"architecture_committed"}\n\n'

        def post_json(
            self, path: str, payload: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            self.calls.append(("POST", path))
            if path.endswith("/sessions"):
                return {"session_id": "session-1"}
            if path.endswith("/approve"):
                return {"ok": True}
            if path.endswith("/apply"):
                return {"flow_id": "flow-1"}
            if path.endswith("/publish/"):
                return {"id": "flow-1", "published_version": 1}
            raise AssertionError(f"Unexpected POST path: {path}")

        def get_json(self, path: str) -> dict[str, Any]:
            self.calls.append(("GET", path))
            if path.endswith("/sessions/session-1"):
                return {"session_id": "session-1"}
            if path.endswith("/sessions/session-1/plans"):
                return {"plans": [{"plan_id": "plan-1"}]}
            if path.endswith("/plans/plan-1"):
                return {"plan_id": "plan-1"}
            if path.endswith("/flows/flow-1/"):
                return {"id": "flow-1"}
            if path.endswith("/flows/flow-1/graph/"):
                return {"nodes": []}
            if path.endswith("/flows/flow-1/input-policy/"):
                return {"flow_id": "flow-1"}
            if path.endswith("/flows/flow-1/template-files/"):
                return {"files": []}
            if path.endswith("/flows/flow-1/published/"):
                return {"id": "flow-1", "published_version": 1}
            if path.endswith("/flows/flow-1/run-contract/"):
                return {"flow_id": "flow-1", "published_flow_version": 1}
            raise AssertionError(f"Unexpected GET path: {path}")

    client = FakeClient()

    result = runner.run_case(
        client=client,
        case=runner.EvalCase(
            case_id="T1",
            prompt="Skapa ett enkelt testflöde.",
            tags=[],
            desired_signal="",
            failure_signal="",
        ),
        run_no=1,
        space_id="space-1",
        output_dir=tmp_path,
        apply_plan=True,
        publish=True,
        edit_flow_id=None,
    )

    assert result.status == "applied"
    publish_index = client.calls.index(("POST", "/api/v1/flows/flow-1/publish/"))
    run_contract_index = client.calls.index(
        ("GET", "/api/v1/flows/flow-1/run-contract/")
    )
    assert publish_index < run_contract_index
