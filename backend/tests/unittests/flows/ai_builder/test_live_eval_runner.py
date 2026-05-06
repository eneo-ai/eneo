from __future__ import annotations

import importlib.util
import sys
import urllib.error
from dataclasses import asdict
from pathlib import Path
from types import ModuleType
from typing import Any

EXPECTED_STEP_METRIC_ROW_KEYS = {
    "step_order",
    "metrics_source",
    "binding_bytes",
    "fan_in_width",
    "source_duplication_count",
    "whole_output_reference_count",
    "structured_field_count",
    "all_previous_steps_count",
}


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
                return {
                    "plan_id": "plan-1",
                    "envelope": {
                        "spec": {
                            "flow_name": "Test",
                            "steps": [
                                {
                                    "plan_step_ref": "step_a",
                                    "name": "Answer",
                                    "assistant_spec": {"instructions": "Answer."},
                                    "input_source": "flow_input",
                                    "input_type": "text",
                                    "output_type": "text",
                                }
                            ],
                        }
                    },
                }
            if path.endswith("/flows/flow-1/"):
                return {
                    "id": "flow-1",
                    "steps": [
                        {
                            "step_order": 1,
                            "input_source": "flow_input",
                            "input_type": "text",
                            "output_type": "text",
                            "input_bindings": {"question": "{{ step_input.text }}"},
                        }
                    ],
                }
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
    assert result.metrics_implementation == "automated"
    assert result.metrics.binding_bytes == len("{{ step_input.text }}".encode("utf-8"))
    assert len(result.step_metrics) == 1
    assert asdict(result.step_metrics[0]) == {
        "step_order": 1,
        "metrics_source": "flow_artifact",
        "binding_bytes": len("{{ step_input.text }}".encode("utf-8")),
        "fan_in_width": 0,
        "source_duplication_count": 0,
        "whole_output_reference_count": 0,
        "structured_field_count": 0,
        "all_previous_steps_count": 0,
    }
    publish_index = client.calls.index(("POST", "/api/v1/flows/flow-1/publish/"))
    run_contract_index = client.calls.index(
        ("GET", "/api/v1/flows/flow-1/run-contract/")
    )
    assert publish_index < run_contract_index


def test_http_error_after_plan_keeps_plan_envelope_material_metrics(
    tmp_path: Path,
) -> None:
    runner = load_live_eval_runner()
    result = run_case_after_plan_apply_failure(
        runner,
        tmp_path,
        urllib.error.HTTPError(
            url="/apply",
            code=500,
            msg="apply failed",
            hdrs={},
            fp=None,
        ),
    )

    assert result.status == "http_error"
    assert result.metrics_implementation == "automated"
    assert result.step_metrics
    assert {row.metrics_source for row in result.step_metrics} == {"plan_envelope"}


def test_connection_error_after_plan_keeps_plan_envelope_material_metrics(
    tmp_path: Path,
) -> None:
    runner = load_live_eval_runner()
    result = run_case_after_plan_apply_failure(
        runner,
        tmp_path,
        urllib.error.URLError("connection lost"),
    )

    assert result.status == "connection_error"
    assert result.metrics_implementation == "automated"
    assert result.step_metrics
    assert {row.metrics_source for row in result.step_metrics} == {"plan_envelope"}


def test_generic_error_after_plan_keeps_plan_envelope_material_metrics(
    tmp_path: Path,
) -> None:
    runner = load_live_eval_runner()
    result = run_case_after_plan_apply_failure(
        runner,
        tmp_path,
        RuntimeError("apply crashed"),
    )

    assert result.status == "error"
    assert result.metrics_implementation == "automated"
    assert result.step_metrics
    assert {row.metrics_source for row in result.step_metrics} == {"plan_envelope"}


def run_case_after_plan_apply_failure(
    runner: ModuleType,
    tmp_path: Path,
    apply_error: Exception,
) -> Any:
    class FakeClient:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def post_stream(self, path: str, payload: dict[str, Any]) -> bytes:
            return b'event: status\ndata: {"status":"architecture_committed"}\n\n'

        def post_json(
            self, path: str, payload: dict[str, Any] | None = None
        ) -> dict[str, Any]:
            if path.endswith("/sessions"):
                return {"session_id": "session-1"}
            if path.endswith("/approve"):
                return {"ok": True}
            if path.endswith("/apply"):
                raise self.error
            raise AssertionError(f"Unexpected POST path: {path}")

        def get_json(self, path: str) -> dict[str, Any]:
            if path.endswith("/sessions/session-1"):
                return {"session_id": "session-1"}
            if path.endswith("/sessions/session-1/plans"):
                return {"plans": [{"plan_id": "plan-1"}]}
            if path.endswith("/plans/plan-1"):
                return plan_envelope_fixture()
            raise AssertionError(f"Unexpected GET path: {path}")

    return runner.run_case(
        client=FakeClient(apply_error),
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
        publish=False,
        edit_flow_id=None,
    )


def plan_envelope_fixture() -> dict[str, Any]:
    return {
        "plan_id": "plan-1",
        "envelope": {
            "spec": {
                "flow_name": "Test",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Draft",
                        "assistant_spec": {"instructions": "Draft."},
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_type": "text",
                    },
                    {
                        "plan_step_ref": "step_b",
                        "name": "Revise",
                        "assistant_spec": {"instructions": "Revise."},
                        "input_source": "previous_step",
                        "input_type": "text",
                        "output_type": "text",
                        "input_bindings": {"question": "{{ step_a.output.text }}"},
                    },
                ],
            }
        },
    }


def test_plan_only_run_computes_material_metrics_from_plan(tmp_path: Path) -> None:
    runner = load_live_eval_runner()

    case_dir = tmp_path / "Q1-run1"
    case_dir.mkdir()
    runner.write_json(
        case_dir / "plan.json",
        {
            "envelope": {
                "spec": {
                    "flow_name": "Quality chain",
                    "steps": [
                        {
                            "plan_step_ref": "step_a",
                            "name": "Draft",
                            "assistant_spec": {"instructions": "Draft."},
                            "input_source": "flow_input",
                            "input_type": "text",
                            "output_type": "text",
                        },
                        {
                            "plan_step_ref": "step_b",
                            "name": "Critique",
                            "assistant_spec": {"instructions": "Critique."},
                            "input_source": "previous_step",
                            "input_type": "text",
                            "output_type": "json",
                        },
                        {
                            "plan_step_ref": "step_c",
                            "name": "Revise",
                            "assistant_spec": {"instructions": "Revise."},
                            "input_source": "previous_step",
                            "input_type": "json",
                            "output_type": "text",
                            "input_bindings": {
                                "question": "{{ step_b.output.structured }}\n{{ step_a.output.text }}"
                            },
                        },
                    ],
                }
            }
        },
    )

    result = runner.CaseRunResult(
        case_id="Q1",
        run_no=1,
        suite="supplemental",
        space_id="space-1",
        status="planned",
        output_dir=str(case_dir),
    )

    runner.attach_material_metrics(result, case_dir)

    assert result.metrics_implementation == "automated"
    assert result.metrics.fan_in_width == 2
    assert result.metrics.whole_output_reference_count == 2
    assert result.metrics.source_duplication_count == 0
    assert [row.metrics_source for row in result.step_metrics] == [
        "plan_envelope",
        "plan_envelope",
        "plan_envelope",
    ]
    assert [row.step_order for row in result.step_metrics] == [1, 2, 3]
    assert all(
        set(asdict(row)) == EXPECTED_STEP_METRIC_ROW_KEYS for row in result.step_metrics
    )
    assert sum(row.binding_bytes for row in result.step_metrics) == (
        result.metrics.binding_bytes
    )
    assert sum(row.source_duplication_count for row in result.step_metrics) == (
        result.metrics.source_duplication_count
    )
    assert sum(row.whole_output_reference_count for row in result.step_metrics) == (
        result.metrics.whole_output_reference_count
    )
    assert sum(row.structured_field_count for row in result.step_metrics) == (
        result.metrics.structured_field_count
    )
    assert result.score_axes == {axis: None for axis in runner.SCORE_AXES}


def test_applied_edit_run_computes_material_metrics_from_flow_only(
    tmp_path: Path,
) -> None:
    runner = load_live_eval_runner()
    case_dir = tmp_path / "E1-run1"
    case_dir.mkdir()
    runner.write_json(
        case_dir / "flow.json",
        {
            "steps": [
                {
                    "step_order": 1,
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_type": "text",
                },
                {
                    "step_order": 2,
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "text",
                    "input_bindings": {"question": "{{ step_1.output.text }}"},
                },
            ]
        },
    )
    result = runner.CaseRunResult(
        case_id="E1",
        run_no=1,
        suite="edit",
        space_id="space-1",
        status="applied",
        output_dir=str(case_dir),
    )

    runner.attach_material_metrics(result, case_dir)

    assert result.metrics_implementation == "automated"
    assert result.metrics.fan_in_width == 1
    assert result.metrics.source_duplication_count == 1
    assert [row.metrics_source for row in result.step_metrics] == [
        "flow_artifact",
        "flow_artifact",
    ]
    assert [row.step_order for row in result.step_metrics] == [1, 2]
    assert all(
        set(asdict(row)) == EXPECTED_STEP_METRIC_ROW_KEYS for row in result.step_metrics
    )
    assert sum(row.source_duplication_count for row in result.step_metrics) == 1


def test_missing_artifact_statuses_keep_empty_metrics(tmp_path: Path) -> None:
    runner = load_live_eval_runner()
    result = runner.CaseRunResult(
        case_id="C1",
        run_no=1,
        suite="create",
        space_id="space-1",
        status="builder_error",
        output_dir=str(tmp_path),
    )

    runner.attach_material_metrics(result, tmp_path)

    assert result.metrics_implementation == "missing_artifacts"
    assert result.metrics.binding_bytes is None
    assert result.metrics.fan_in_width is None
    assert result.step_metrics == []


def test_malformed_artifact_marks_metrics_missing(tmp_path: Path) -> None:
    runner = load_live_eval_runner()
    (tmp_path / "flow.json").write_text("{", encoding="utf-8")
    result = runner.CaseRunResult(
        case_id="C1",
        run_no=1,
        suite="create",
        space_id="space-1",
        status="applied",
        output_dir=str(tmp_path),
    )

    runner.attach_material_metrics(result, tmp_path)

    assert result.metrics_implementation == "missing_artifacts"
    assert result.step_metrics == []


def test_redacted_baseline_summary_preserves_step_metrics(tmp_path: Path) -> None:
    runner = load_live_eval_runner()
    case_dir = tmp_path / "E1-run1"
    case_dir.mkdir()
    runner.write_json(
        case_dir / "flow.json",
        {
            "steps": [
                {
                    "step_order": 1,
                    "input_source": "flow_input",
                    "input_type": "audio",
                    "output_type": "text",
                },
                {
                    "step_order": 2,
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "text",
                    "input_bindings": {"question": "{{ step_1.output.text }}"},
                },
            ]
        },
    )
    result = runner.CaseRunResult(
        case_id="E1",
        run_no=1,
        suite="edit",
        space_id="space-1",
        status="applied",
        output_dir=str(case_dir),
    )

    runner.attach_material_metrics(result, case_dir)
    summary = {
        "generated_at": "2026-05-06T00:00:00+00:00",
        "api_base": "http://localhost:8123",
        "spaces": ["space-1"],
        "runs": 1,
        "applied": True,
        "published": False,
        "score_axes": runner.SCORE_AXES,
        "scoring": {
            "score_source": "manual",
            "metrics_source": "automated_plan_or_flow_artifacts",
        },
        "aggregate": {},
        "results": [asdict(result)],
    }

    redacted = runner.redacted_baseline_summary(summary)

    assert redacted["results"][0]["step_metrics"] == [
        asdict(row) for row in result.step_metrics
    ]


def test_live_eval_runner_does_not_assign_score_axes_from_metrics() -> None:
    runner_path = Path(__file__).resolve().parents[5] / (
        "docs/goals/material-efficiency/run_flow_ai_builder_live_eval.py"
    )
    source = runner_path.read_text(encoding="utf-8")

    assert "score_axes: dict[str, int | None] = field(" in source
    assert ".score_axes[" not in source
