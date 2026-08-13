from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import time
from collections.abc import Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID

from pytest import CaptureFixture, MonkeyPatch, mark, raises

_TEST_SESSION_ID = "00000000-0000-0000-0000-000000000001"


def _battle_harness() -> ModuleType:
    module_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_battle_test.py"
    )
    spec = importlib.util.spec_from_file_location(
        "ai_builder_api_battle_test", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _allow_clean_measurement_space(
    harness: ModuleType,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        harness,
        "_require_clean_measurement_space",
        lambda **_kwargs: None,
    )


def test_harness_create_session_never_requests_session_supersession(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    requests: list[dict[str, object]] = []

    def request_json(**kwargs: object) -> dict[str, str]:
        requests.append(kwargs)
        return {"session_id": "session-1"}

    monkeypatch.setattr(harness, "_request_json", request_json)

    result = harness._create_session(
        config=harness.ApiConfig(
            base_url="http://localhost/api/v1",
            api_key="local-test-key",
            timeout_seconds=1,
        ),
        space_id="space-1",
    )

    assert result == {"session_id": "session-1"}
    assert requests == [
        {
            "config": harness.ApiConfig(
                base_url="http://localhost/api/v1",
                api_key="local-test-key",
                timeout_seconds=1,
            ),
            "method": "POST",
            "path": "/flows/ai-builder/sessions",
            "payload": {
                "target_kind": "create",
                "space_id": "space-1",
                "force_new": False,
            },
        }
    ]


def test_force_new_is_not_a_battle_harness_cli_option(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    harness = _battle_harness()
    monkeypatch.setattr(
        sys,
        "argv",
        ["ai_builder_api_battle_test.py", "--force-new"],
    )

    with raises(SystemExit) as exc_info:
        harness._parse_args()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --force-new" in capsys.readouterr().err


def test_sealed_targeted_suite_is_incompatible_with_full_release_suite(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    harness = _battle_harness()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ai_builder_api_battle_test.py",
            "--run-suite",
            "--sealed-targeted-suite",
            "--case-id",
            "simple_document_metadata_json",
        ],
    )

    with raises(SystemExit) as exc_info:
        harness._parse_args()

    assert exc_info.value.code == 2
    assert "not allowed with argument --run-suite" in capsys.readouterr().err


@mark.parametrize(
    ("case_ids", "expected_case_ids"),
    [
        (
            ["interview_open_meeting_audio"],
            ["interview_open_meeting_audio"],
        ),
        (
            [
                "simple_document_metadata_json",
                "interview_open_meeting_audio",
            ],
            [
                "simple_document_metadata_json",
                "interview_open_meeting_audio",
            ],
        ),
    ],
)
def test_sealed_targeted_suite_promotes_every_selected_case_to_required(
    case_ids: list[str],
    expected_case_ids: list[str],
) -> None:
    harness = _battle_harness()

    cases = harness._cases_from_args(
        SimpleNamespace(
            cases_file=None,
            run_suite=False,
            sealed_targeted_suite=True,
            case_id=case_ids,
            cohort=None,
            max_cases=None,
            file_ids=None,
        )
    )

    assert [case.case_id for case in cases] == expected_case_ids
    assert all(case.required for case in cases)


def test_sealed_targeted_suite_requires_an_explicit_selection() -> None:
    harness = _battle_harness()

    with raises(ValueError, match="requires at least one --case-id or --cohort"):
        harness._cases_from_args(
            SimpleNamespace(
                cases_file=None,
                run_suite=False,
                sealed_targeted_suite=True,
                case_id=None,
                cohort=None,
                max_cases=None,
                file_ids=None,
            )
        )


def test_sealed_targeted_suite_accepts_a_cohort_selection() -> None:
    harness = _battle_harness()

    cases = harness._cases_from_args(
        SimpleNamespace(
            cases_file=None,
            run_suite=False,
            sealed_targeted_suite=True,
            case_id=None,
            cohort=["smoke_v3"],
            max_cases=None,
            file_ids=None,
        )
    )

    assert len(cases) == 12
    assert all("smoke_v3" in case.cohorts and case.required for case in cases)


@mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"file_ids": ["arbitrary-file-id"]}, "--file-id"),
        ({"max_cases": 1}, "--max-cases"),
    ],
)
def test_sealed_targeted_suite_rejects_exploratory_input_or_truncation_overrides(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    harness = _battle_harness()
    arguments: dict[str, object] = {
        "cases_file": None,
        "run_suite": False,
        "sealed_targeted_suite": True,
        "case_id": ["attachment_docx_template_placeholders_to_fields"],
        "cohort": None,
        "max_cases": None,
        "file_ids": None,
    }
    arguments.update(overrides)

    with raises(ValueError, match=expected_message):
        harness._cases_from_args(SimpleNamespace(**arguments))


def test_single_case_sealed_targeted_suite_uses_release_acquisition_and_repetitions(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    captured: dict[str, object] = {}
    args = SimpleNamespace(
        reanalyze_bundle=None,
        api_key="test-key",
        output_dir=str(tmp_path),
        replacement_suite_dir=None,
        space_id="space-1",
        base_url="http://localhost:8123/api/v1",
        timeout_seconds=1,
        cases_file=None,
        run_suite=False,
        sealed_targeted_suite=True,
        case_id=["interview_open_meeting_audio"],
        cohort=None,
        max_cases=None,
        file_ids=None,
        repetitions=3,
        concurrency=1,
        model_id="model-a",
    )

    monkeypatch.setattr(harness, "_parse_args", lambda: args)

    def run_suite(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(harness, "_run_suite", run_suite)

    assert harness.main() == 0
    cases = captured["cases"]
    assert isinstance(cases, list)
    assert [case.case_id for case in cases] == ["interview_open_meeting_audio"]
    assert all(case.required for case in cases)
    assert captured["args"] is args
    assert args.repetitions == 3
    acquisition_contract = captured["acquisition_contract"]
    assert acquisition_contract.required_case_ids == ("interview_open_meeting_audio",)
    assert acquisition_contract.require_clean_source is True
    assert (
        acquisition_contract.artifact_schema_version
        == harness.SUPPORTED_RECEIPT_ARTIFACT_VERSION
    )


def test_sealed_targeted_suite_uses_release_identity_preflight_gates(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    args = SimpleNamespace(
        cases_file=None,
        run_suite=False,
        sealed_targeted_suite=True,
        case_id=["interview_open_meeting_audio"],
        cohort=None,
        max_cases=None,
        file_ids=None,
        repetitions=1,
        concurrency=1,
        space_id="space-1",
        model_id="model-a",
    )
    cases = harness._cases_from_args(args)
    acquisition_contract = harness._acquisition_contract_from_args(
        args,
        selected_cases=cases,
    )
    config = harness.ApiConfig(
        base_url="http://localhost:8123/api/v1",
        api_key="test-key",
        timeout_seconds=1,
    )
    captured: dict[str, object] = {}

    def stop_after_identity_preflight(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        raise ValueError("identity preflight reached")

    monkeypatch.setattr(
        harness,
        "_release_run_identity",
        stop_after_identity_preflight,
    )

    with raises(ValueError, match="identity preflight reached"):
        harness._run_suite(
            cases=cases,
            config=config,
            args=args,
            output_dir=tmp_path,
            acquisition_contract=acquisition_contract,
        )

    assert captured == {
        "cases": cases,
        "cases_path": harness.DEFAULT_CASES_FILE,
        "requested_model_id": "model-a",
        "require_clean_source": True,
        # Passing config is what makes the canonical identity owner verify
        # target /version; exploratory suites pass None here.
        "config": config,
    }
    assert list(tmp_path.iterdir()) == []


def test_full_release_suite_selection_remains_unfiltered_and_unmodified(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    cases = [
        harness.BattleCase(case_id="required", prompt="Build it.", required=True),
        harness.BattleCase(case_id="benchmark", prompt="Build that."),
    ]
    monkeypatch.setattr(harness, "_read_cases_file", lambda _path: cases)

    selected = harness._cases_from_args(
        SimpleNamespace(
            cases_file=None,
            run_suite=True,
            sealed_targeted_suite=False,
            case_id=None,
            cohort=None,
            max_cases=None,
            file_ids=None,
        )
    )

    assert selected == cases
    assert [case.required for case in selected] == [True, False]


def test_observation_acquisition_serializes_repetitions_of_one_case() -> None:
    harness = _battle_harness()
    first = harness.BattleCase(case_id="first", prompt="Build the first Flow.")
    second = harness.BattleCase(case_id="second", prompt="Build the second Flow.")
    observations = [
        (1, 1, first),
        (1, 2, second),
        (2, 1, first),
    ]
    different_cases_started = Barrier(2)
    state_lock = Lock()
    active_by_case: dict[str, int] = {}
    maximum_active_by_case: dict[str, int] = {}
    maximum_total_active = 0

    def acquire(item: tuple[int, int, Any]) -> dict[str, object]:
        nonlocal maximum_total_active
        repetition, _, case = item
        with state_lock:
            active_by_case[case.case_id] = active_by_case.get(case.case_id, 0) + 1
            maximum_active_by_case[case.case_id] = max(
                maximum_active_by_case.get(case.case_id, 0),
                active_by_case[case.case_id],
            )
            maximum_total_active = max(
                maximum_total_active,
                sum(active_by_case.values()),
            )
        if repetition == 1:
            different_cases_started.wait(timeout=2)
        with state_lock:
            active_by_case[case.case_id] -= 1
        return {"case_id": case.case_id, "repetition": repetition}

    results = harness._acquire_observations_with_case_isolation(
        observations=observations,
        max_concurrency=3,
        acquire=acquire,
    )

    assert results == [
        {"case_id": "first", "repetition": 1},
        {"case_id": "second", "repetition": 1},
        {"case_id": "first", "repetition": 2},
    ]
    assert maximum_active_by_case == {"first": 1, "second": 1}
    assert maximum_total_active == 2


def test_suite_context_records_per_case_concurrency_limit() -> None:
    harness = _battle_harness()

    context = harness._suite_run_context(SimpleNamespace(repetitions=3, concurrency=6))

    assert context["max_concurrency"] == 6
    assert context["max_concurrent_observations_per_case"] == 1
    assert context["flow_isolation_semantics_version"] == 1


def test_measurement_space_must_have_no_active_flows(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    config = harness.ApiConfig(
        base_url="http://localhost/api/v1",
        api_key="local-test-key",
        timeout_seconds=1,
    )
    requests: list[dict[str, object]] = []

    def request_json(**kwargs: object) -> dict[str, object]:
        requests.append(kwargs)
        return {"count": 1, "items": [{"id": "existing-flow"}], "has_more": True}

    monkeypatch.setattr(harness, "_request_json", request_json)

    with raises(ValueError, match="dedicated empty space"):
        harness._require_clean_measurement_space(
            config=config,
            space_id="00000000-0000-0000-0000-000000000123",
        )

    assert requests == [
        {
            "config": config,
            "method": "GET",
            "path": (
                "/flows/?space_id=00000000-0000-0000-0000-000000000123&limit=1&offset=0"
            ),
        }
    ]


def test_empty_measurement_space_passes_preflight(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    monkeypatch.setattr(
        harness,
        "_request_json",
        lambda **_kwargs: {"count": 0, "items": [], "has_more": False},
    )

    baseline = harness._require_clean_measurement_space(
        config=harness.ApiConfig(
            base_url="http://localhost/api/v1",
            api_key="local-test-key",
            timeout_seconds=1,
        ),
        space_id="00000000-0000-0000-0000-000000000123",
    )

    assert baseline is None


def test_send_and_fetch_supplies_fresh_caller_owned_turn_identity(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    turn_ids = (
        UUID("00000000-0000-0000-0000-000000000901"),
        UUID("00000000-0000-0000-0000-000000000902"),
    )
    generated_turn_ids = iter(turn_ids)
    sent_payloads: list[dict[str, object]] = []

    monkeypatch.setattr(harness, "uuid4", lambda: next(generated_turn_ids))

    def send_message_stream(**kwargs: object) -> Iterator[dict[str, object]]:
        payload = kwargs["payload"]
        assert isinstance(payload, dict)
        sent_payloads.append(payload)
        return iter(())

    monkeypatch.setattr(harness, "_send_message_stream", send_message_stream)
    monkeypatch.setattr(harness, "_request_json", lambda **_kwargs: {})

    config = harness.ApiConfig(
        base_url="http://localhost/api/v1",
        api_key="local-test-key",
        timeout_seconds=1,
    )
    results = [
        harness._send_and_fetch(
            config=config,
            session_id="session-1",
            message="Bygg ett flöde.",
            model_id=None,
            file_ids=(),
            ui_language="sv",
            question_answer=None,
        )
        for _ in turn_ids
    ]

    expected_payload = {
        "message": "Bygg ett flöde.",
        "model_id": None,
        "file_ids": None,
        "question_answer": None,
        "ui_language": "sv",
    }
    assert sent_payloads == [
        {
            **expected_payload,
            "client_turn_id": str(turn_id),
        }
        for turn_id in turn_ids
    ]
    assert [result["client_turn_id"] for result in results] == [
        str(turn_id) for turn_id in turn_ids
    ]


def test_send_failure_preserves_turn_identity_for_failure_bundle(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    turn_id = UUID("00000000-0000-0000-0000-000000000903")

    monkeypatch.setattr(harness, "uuid4", lambda: turn_id)

    def fail_send(**_kwargs: object) -> Iterator[dict[str, object]]:
        raise harness.URLError("connection reset")

    monkeypatch.setattr(harness, "_send_message_stream", fail_send)

    with raises(harness.BattleTurnError) as exc_info:
        harness._send_and_fetch(
            config=harness.ApiConfig(
                base_url="http://localhost/api/v1",
                api_key="local-test-key",
                timeout_seconds=1,
            ),
            session_id="session-1",
            message="Bygg ett flöde.",
            model_id=None,
            file_ids=(),
            ui_language="sv",
            question_answer=None,
        )

    assert exc_info.value.client_turn_id == str(turn_id)
    assert harness._failure_error_fields(exc_info.value) == {
        "error": "<urlopen error connection reset>",
        "client_turn_id": str(turn_id),
    }


def _document_plan(
    *,
    terminal_mode: str,
    terminal_input_source: str,
    terminal_output_type: str = "pdf",
) -> dict[str, Any]:
    return {
        "proposal": {
            "spec": {
                "flow_name": "Document report",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Read source",
                        "input_source": "flow_input",
                        "input_type": "document",
                        "output_type": "json",
                        "output_mode": "pass_through",
                        "output_contract": {
                            "type": "object",
                            "properties": {"summary": {"type": "string"}},
                        },
                    },
                    {
                        "plan_step_ref": "step_b",
                        "name": "Render report",
                        "input_source": terminal_input_source,
                        "input_type": "text",
                        "output_type": terminal_output_type,
                        "output_mode": terminal_mode,
                    },
                ],
            }
        }
    }


def _document_plan_with_extra_text_helper() -> dict[str, Any]:
    return {
        "proposal": {
            "spec": {
                "flow_name": "Document report",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Read source",
                        "input_source": "flow_input",
                        "input_type": "document",
                        "output_type": "json",
                        "output_mode": "pass_through",
                        "output_contract": {
                            "type": "object",
                            "properties": {"summary": {"type": "string"}},
                        },
                    },
                    {
                        "plan_step_ref": "step_b",
                        "name": "Write report body",
                        "input_source": "previous_step",
                        "input_type": "text",
                        "output_type": "text",
                        "output_mode": "pass_through",
                    },
                    {
                        "plan_step_ref": "step_c",
                        "name": "Make PDF",
                        "input_source": "previous_step",
                        "input_type": "text",
                        "output_type": "text",
                        "output_mode": "pass_through",
                    },
                    {
                        "plan_step_ref": "step_d",
                        "name": "Render PDF",
                        "input_source": "previous_step",
                        "input_type": "text",
                        "output_type": "pdf",
                        "output_mode": "render_verbatim",
                    },
                ],
            }
        }
    }


def _review_policy_plan(*, mode: str = "view") -> dict[str, object]:
    return {
        "proposal": {
            "spec": {
                "flow_name": "Procurement report",
                "steps": [
                    {
                        "plan_step_ref": "extract_matrix",
                        "name": "Extract scoring matrix",
                        "input_source": "flow_input",
                        "input_type": "document",
                        "output_type": "json",
                        "output_mode": "pass_through",
                        "output_contract": {
                            "type": "object",
                            "properties": {
                                "supplier": {"type": "string"},
                                "score": {"type": "number"},
                            },
                        },
                        "review_policy": {"mode": mode},
                    },
                    {
                        "plan_step_ref": "write_report",
                        "name": "Write report",
                        "input_source": "previous_step",
                        "input_type": "json",
                        "output_type": "text",
                        "output_mode": "pass_through",
                    },
                    {
                        "plan_step_ref": "render_report",
                        "name": "Render report",
                        "input_source": "previous_step",
                        "input_type": "text",
                        "output_type": "pdf",
                        "output_mode": "render_verbatim",
                    },
                ],
            }
        }
    }


def _complex_authoring_plan() -> dict[str, object]:
    return {
        "proposal": {
            "spec": {
                "flow_name": "Meeting report",
                "steps": [
                    {
                        "plan_step_ref": "transcribe_audio",
                        "name": "Transcribe audio",
                        "input_source": "flow_input",
                        "input_type": "audio",
                        "output_type": "text",
                        "output_mode": "transcribe_only",
                        "review_policy": {"mode": "edit"},
                    },
                    {
                        "plan_step_ref": "analyze_transcript",
                        "name": "Analyze transcript",
                        "input_source": "previous_step",
                        "input_type": "text",
                        "output_type": "json",
                        "output_mode": "pass_through",
                        "output_contract": {
                            "type": "object",
                            "properties": {
                                "summary_facts": {"type": "string"},
                                "analysis_findings": {"type": "string"},
                                "recommendations": {"type": "string"},
                            },
                        },
                        "assistant_spec": {
                            "instructions": "Extract stable typed report facts."
                        },
                    },
                    {
                        "plan_step_ref": "write_report",
                        "name": "Write report",
                        "input_source": "previous_step",
                        "input_type": "json",
                        "output_type": "text",
                        "output_mode": "pass_through",
                        "review_policy": {"mode": "edit"},
                        "assistant_spec": {
                            "instructions": (
                                "Write one report with the headings Sammanfattning, "
                                "Analys, and Rekommendationer."
                            )
                        },
                    },
                    {
                        "plan_step_ref": "render_docx",
                        "name": "Render DOCX",
                        "input_source": "previous_step",
                        "input_type": "text",
                        "output_type": "docx",
                        "output_mode": "render_verbatim",
                    },
                ],
            }
        }
    }


def _review_plan_steps(plan: Mapping[str, object]) -> list[dict[str, object]]:
    proposal = plan.get("proposal")
    assert isinstance(proposal, Mapping)
    spec = proposal.get("spec")
    assert isinstance(spec, Mapping)
    raw_steps = spec.get("steps")
    assert isinstance(raw_steps, list)
    steps: list[dict[str, object]] = []
    for step in raw_steps:
        assert isinstance(step, dict)
        assert all(isinstance(key, str) for key in step)
        steps.append(step)
    return steps


def _insert_review_plan_step(
    plan: Mapping[str, object],
    index: int,
    step: dict[str, object],
) -> None:
    proposal = plan.get("proposal")
    assert isinstance(proposal, Mapping)
    spec = proposal.get("spec")
    assert isinstance(spec, Mapping)
    raw_steps = spec.get("steps")
    assert isinstance(raw_steps, list)
    raw_steps.insert(index, step)


def _applied_flow_from_plan(plan: dict[str, object]) -> dict[str, object]:
    steps = _review_plan_steps(plan)
    return {
        "id": "flow-1",
        "steps": [
            {
                **step,
                "step_order": index,
                "user_description": step["name"],
            }
            for index, step in enumerate(steps, start=1)
        ],
    }


def _six_file_runtime_evidence() -> dict[str, object]:
    documents = [
        {
            "source_file_id": f"file-{index}",
            "source_label": f"source-{index}.pdf",
            "title": f"Document {index}",
            "year": "2026",
            "category": "Policy",
            "type": "Report",
            "author": "Municipality",
            "conclusions": "Conclusion",
            "summary": "Summary",
        }
        for index in range(1, 7)
    ]
    artifact_sections = [
        (
            f"Source: {document['source_label']}\n"
            f"Title: {document['title']}\n"
            f"Year: {document['year']}\n"
            f"Category: {document['category']}\n"
            f"Type: {document['type']}\n"
            f"Author: {document['author']}\n"
            f"Conclusions: {document['conclusions']}\n"
            f"Summary: {document['summary']}\n"
            "Extraction quality: "
            + (
                "pdf_text_likely_reversed; värde framgår ej"
                if index == 6
                else "full extraction"
            )
        )
        for index, document in enumerate(documents, start=1)
    ]
    return {
        "provider_calls": {
            "items": [
                {"event_id": f"provider-call-{index}", "status": "succeeded"}
                for index in range(1, 8)
            ],
            "count": 7,
            "total_count": 7,
            "total_count_truncated": False,
            "has_more": False,
            "next_after_event_id": None,
        },
        "run": {
            "status": "completed",
            "result": {
                "kind": "artifact",
                "files": [{"file_id": "artifact-1", "name": "report.pdf"}],
            },
            "token_usage": {
                "num_tokens_input": 1200,
                "num_tokens_output": 300,
                "num_tokens_total": 1500,
            },
        },
        "step_results": [
            {
                "step_order": 1,
                "status": "completed",
                "runtime_input_file_ids": [f"file-{index}" for index in range(1, 7)],
                "output_payload_json": {"documents": documents},
                "model_parameters_json": {
                    "runtime_input_execution_mode": "per_source",
                    "per_source_call_count": 6,
                },
                "num_tokens_input": 1000,
                "num_tokens_output": 200,
                "diagnostics": [
                    {
                        "code": "runtime_input_source_extraction_warning",
                        "message": "pdf_text_likely_reversed",
                    }
                ],
            },
            {
                "step_order": 2,
                "status": "completed",
                "output_payload_json": {"overview": "Aggregate overview"},
                "num_tokens_input": 200,
                "num_tokens_output": 100,
            },
            {
                "step_order": 3,
                "status": "completed",
                "output_payload_json": {"text": "Deterministic composed report"},
                "num_tokens_input": None,
                "num_tokens_output": None,
            },
            {
                "step_order": 4,
                "status": "completed",
                "result_files": [{"file_id": "artifact-1", "name": "report.pdf"}],
                "num_tokens_input": None,
                "num_tokens_output": None,
            },
        ],
        "final_artifact": {
            "file_id": "artifact-1",
            "sha256": "d" * 64,
            "text": "\n\n".join(artifact_sections),
        },
    }


def _applied_flow_steps(flow: Mapping[str, object]) -> list[dict[str, object]]:
    raw_steps = flow.get("steps")
    assert isinstance(raw_steps, list)
    steps: list[dict[str, object]] = []
    for step in raw_steps:
        assert isinstance(step, dict)
        assert all(isinstance(key, str) for key in step)
        steps.append(step)
    return steps


def _runtime_step_results(
    evidence: Mapping[str, object],
) -> list[dict[str, object]]:
    raw_steps = evidence.get("step_results")
    assert isinstance(raw_steps, list)
    steps: list[dict[str, object]] = []
    for step in raw_steps:
        assert isinstance(step, dict)
        assert all(isinstance(key, str) for key in step)
        steps.append(step)
    return steps


def _runtime_documents(evidence: Mapping[str, object]) -> list[dict[str, object]]:
    first_step = _runtime_step_results(evidence)[0]
    payload = first_step.get("output_payload_json")
    assert isinstance(payload, Mapping)
    raw_documents = payload.get("documents")
    assert isinstance(raw_documents, list)
    documents: list[dict[str, object]] = []
    for document in raw_documents:
        assert isinstance(document, dict)
        assert all(isinstance(key, str) for key in document)
        documents.append(document)
    return documents


def _append_first_runtime_document(evidence: Mapping[str, object]) -> None:
    first_step = _runtime_step_results(evidence)[0]
    payload = first_step.get("output_payload_json")
    assert isinstance(payload, Mapping)
    raw_documents = payload.get("documents")
    assert isinstance(raw_documents, list)
    assert raw_documents
    raw_documents.append(raw_documents[0])


def _insert_runtime_step_result(
    evidence: Mapping[str, object],
    index: int,
    step: dict[str, object],
) -> None:
    raw_steps = evidence.get("step_results")
    assert isinstance(raw_steps, list)
    raw_steps.insert(index, step)


def _runtime_final_artifact(evidence: Mapping[str, object]) -> dict[str, object]:
    artifact = evidence.get("final_artifact")
    assert isinstance(artifact, dict)
    assert all(isinstance(key, str) for key in artifact)
    return artifact


def _classifier_diagnostics() -> dict[str, object]:
    return {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "classifier_runs": [
            {
                "message_id": "assistant-1",
                "schema_version": 20,
                "outcome": "resolved",
                "prompt_hash": "a" * 64,
                "model": "openai/gpt-test",
                "provider": "openai",
                "source_inventory": [
                    {
                        "source_id": "user_message:user-1",
                        "kind": "user_message",
                        "source_sha256": "b" * 64,
                        "message_id": "user-1",
                    },
                    {
                        "source_id": "uploaded_file:file-1",
                        "kind": "uploaded_file",
                        "source_sha256": "c" * 64,
                        "file_id": "file-1",
                        "coverage": "fully_seen",
                    },
                ],
                "slots": [
                    {
                        "slot_name": "report_disposition",
                        "value": "both",
                        "confidence": "high",
                        "reason": "explicit source sections and overview",
                        "evidence": [
                            {
                                "source_id": "user_message:user-1",
                                "quote": "källavsnitt och en samlad rapport",
                            }
                        ],
                        "evidence_level": "explicit",
                    }
                ],
                "file_roles": [
                    {
                        "file_id": "file-1",
                        "role": "example_output",
                        "confidence": "high",
                        "reason": "user calls it an example",
                        "evidence": [
                            {
                                "source_id": "user_message:user-1",
                                "quote": "bifogade exempelrapporten",
                            }
                        ],
                        "evidence_level": "explicit",
                    }
                ],
                "secondary_obligations": [],
                "form_intake": None,
                "assumptions": ["Source labels remain visible."],
                "contradictions": [],
            }
        ],
    }


def _release_identity_fixture(
    harness: ModuleType,
    *,
    case_id: str,
    prompt: str,
    revision: str = "a" * 40,
    harness_sha256: str = "b" * 64,
    cases_sha256: str = "c" * 64,
    requested_model_id: str | None = "model-a",
) -> dict[str, object]:
    stable_build = {
        "source_revision": revision,
        "harness_sha256": harness_sha256,
        "cases_sha256": cases_sha256,
    }
    build = {"app_version": harness.LOCAL_APP_VERSION, **stable_build}
    model = {"requested_id": requested_model_id}
    prompt_hashes = {
        case_id: hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    return {
        "source": {
            "revision": revision,
            "revision_sha256": hashlib.sha256(revision.encode("utf-8")).hexdigest(),
            "tracked_clean": True,
        },
        "build": {**build, "sha256": harness._canonical_sha256(stable_build)},
        "model": {**model, "sha256": harness._canonical_sha256(model)},
        "prompts": {
            "case_sha256_by_id": prompt_hashes,
            "sha256": harness._canonical_sha256(prompt_hashes),
        },
    }


def _live_provenance_fixture(
    harness: ModuleType,
    *,
    revision: str = "a" * 40,
    harness_sha256: str = "b" * 64,
    cases_sha256: str = "c" * 64,
    requested_model_id: str | None = "model-a",
    prompt: str,
) -> dict[str, object]:
    stable_build = {
        "source_revision": revision,
        "harness_sha256": harness_sha256,
        "cases_sha256": cases_sha256,
    }
    build = {"app_version": harness.LOCAL_APP_VERSION, **stable_build}
    model = {
        "requested_id": requested_model_id,
        "resolved_id": requested_model_id,
        "resolved_name": "gpt-a",
        "resolved_provider": "openai",
        "expected_observed_ids": ["openai/gpt-a"],
        "planner_interaction_count": 1,
        "planner_observations": [{"interaction_index": 1, "model_id": "openai/gpt-a"}],
        "missing_planner_interaction_indices": [],
        "terminal_error_interaction_indices": [],
        "planner_observed_ids": ["openai/gpt-a"],
        "classifier_observed_ids": ["openai/gpt-a"],
        "observed_ids": ["openai/gpt-a"],
        "observed_matches_resolved": True,
    }
    classifier_hashes = ["d" * 64]
    progress_payload = {
        "source": "single_call_committed_session_summary",
        "call_count": 1,
        "repair_attempts": 0,
        "parse_repair_attempts": 0,
        "attempts": [
            {
                "attempt": 1,
                "kind": "initial",
                "call_count": 1,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "elapsed_ms": 1,
                "elapsed_scope": "proposal_turn_upper_bound",
                "token_usage_source": "provider",
                "token_usage_estimated": False,
            }
        ],
        "provider_failure_status": "none",
        "public_error_code_count": 0,
    }
    return {
        "source": {
            "revision": revision,
            "revision_sha256": hashlib.sha256(revision.encode("utf-8")).hexdigest(),
            "tracked_clean": True,
        },
        "build": {**build, "sha256": harness._canonical_sha256(stable_build)},
        "model": {**model, "sha256": harness._canonical_sha256(model)},
        "prompt": {
            "case_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "classifier_hashes": classifier_hashes,
        },
        "capability": {
            "source": "slot_classification_prompt_hash_composite",
            "classifier_prompt_hashes": classifier_hashes,
            "classifier_request_composite_fingerprint": harness._canonical_sha256(
                {"classifier_prompt_hashes": classifier_hashes}
            ),
        },
        "proposal_progress": {
            **progress_payload,
            "fingerprint": harness._canonical_sha256(progress_payload),
        },
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "model_calls": 1,
            "repair_attempts": 0,
            "parse_repair_attempts": 0,
            "elapsed_ms": 1,
            "raw_reads": {
                "classifier_run_count": 1,
                "source_inventory_entry_count": 0,
                "uploaded_file_raw_read_count": 0,
                "distinct_uploaded_file_count": 0,
                "uploaded_file_reread_count": 0,
                "truncated_source_count": 0,
            },
        },
    }


def _empty_observation_input_identity(harness: ModuleType) -> dict[str, object]:
    payload = {
        "attachment_evidence_sha256s": [],
        "runtime_fixture_sha256s": [],
        "runtime_source_sha256s": [],
    }
    return {
        **payload,
        "attachment_file_ids": [],
        "attachment_fixture_bindings": [],
        "attachment_fixtures": [],
        "classifier_session_id": _TEST_SESSION_ID,
        "attachment_evidence_status": "not_required",
        "runtime_evidence_status": "not_required",
        "verified": True,
        "mismatches": [],
        "sha256": harness._canonical_sha256(payload),
    }


def _complete_reanalysis_bundle(
    harness: ModuleType,
    *,
    case_id: str,
    expected: Mapping[str, object],
    prompt: str = "Build it.",
) -> dict[str, object]:
    case = harness.BattleCase(
        case_id=case_id,
        prompt=prompt,
        expected=dict(expected),
    )
    case_contract = harness._case_contract_payload(case)
    return {
        "artifact_schema_version": harness.SUPPORTED_RECEIPT_ARTIFACT_VERSION,
        "artifact_mode": "live_execution",
        "live_execution_provenance": _live_provenance_fixture(
            harness,
            prompt=prompt,
        ),
        "case": {
            "id": case_id,
            "prompt": prompt,
            "complexity": case.complexity,
            "domain": case.domain,
            "required": case.required,
            "apply_plan": case.apply_plan,
            "execute_flow": case.execute_flow,
            "release_dimensions": [],
            "expected": dict(expected),
            "file_ids": [],
            "direct_file_slot_count": 0,
            "attachments": [],
            "runtime_files": [],
            "synthetic_user_profile": None,
            "cohorts": [],
            "configured_question_answers": {},
            "question_answer_sources": {},
        },
        "case_identity": harness._case_identity(case),
        "case_contract": case_contract,
        "case_contract_sha256": harness._canonical_sha256(case_contract),
        "repetition": 1,
        "session_id": _TEST_SESSION_ID,
        "interactions": [
            {
                "events": [
                    {
                        "event": "usage",
                        "data": {"last_model": "openai/gpt-a"},
                    }
                ]
            }
        ],
        "plan": None,
        "observation_input_identity": _empty_observation_input_identity(harness),
        "classifier_diagnostics": {
            "session_id": _TEST_SESSION_ID,
            "classifier_runs": [
                {
                    "message_id": "assistant-1",
                    "schema_version": 20,
                    "outcome": "resolved",
                    "prompt_hash": "d" * 64,
                    "model": "gpt-a",
                    "provider": "openai",
                    "source_inventory": [],
                }
            ],
        },
        "quality_report": {
            "checks": [
                {
                    "name": "plan_created",
                    "passed": True,
                    "actual": True,
                    "expected": True,
                }
            ],
            "warnings": [],
            "metrics": {},
        },
    }


def _complete_live_case_bundle(
    harness: ModuleType,
    case: object,
    *,
    quality_checks: list[dict[str, object]] | None = None,
    requested_model_id: str | None = "model-a",
) -> dict[str, object]:
    assert isinstance(case, harness.BattleCase)
    case_contract = harness._case_contract_payload(case)
    bundle = _complete_reanalysis_bundle(
        harness,
        case_id=case.case_id,
        expected=case.expected or {},
        prompt=case.prompt,
    )
    bundle.update(
        {
            "created_at": "20260713T120001",
            "live_execution_provenance": _live_provenance_fixture(
                harness,
                prompt=case.prompt,
                requested_model_id=requested_model_id,
            ),
            "case": {
                "id": case.case_id,
                "prompt": case.prompt,
                "complexity": case.complexity,
                "domain": case.domain,
                "required": case.required,
                "apply_plan": case.apply_plan,
                "execute_flow": case.execute_flow,
                "release_dimensions": list(case.release_dimensions),
                "expected": case.expected or {},
                "file_ids": list(case.file_ids),
                "direct_file_slot_count": len(case.file_ids),
                "attachments": harness._fixture_contract(case.attachments),
                "runtime_files": harness._fixture_contract(case.runtime_files),
                "synthetic_user_profile": case.synthetic_user_profile,
                "cohorts": list(case.cohorts),
                "configured_question_answers": (case.configured_question_answers or {}),
                "question_answer_sources": case.question_answer_sources or {},
            },
            "case_identity": harness._case_identity(case),
            "case_contract": case_contract,
            "case_contract_sha256": harness._canonical_sha256(case_contract),
            "session_id": _TEST_SESSION_ID,
            "plan_id": "plan-1",
            "plan_summary": {"step_count": 1},
            "event_summary": {},
            "quality_report": {
                "checks": quality_checks or [],
                "warnings": [],
                "metrics": {},
            },
        }
    )
    return bundle


def test_cases_file_rejects_misspelled_classifier_expectation(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": 8,
                "cases": [
                    {
                        "id": "bad-classifier-expectation",
                        "prompt": "Build a report.",
                        "expected": {
                            "expected_classifier_slots": [
                                {
                                    "slot_nam": "terminal_output",
                                    "value": "pdf_document",
                                }
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with raises(ValueError, match="unknown keys: slot_nam"):
        _battle_harness()._read_cases_file(cases_path)


def test_cases_file_rejects_unsupported_version(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps({"version": 3, "cases": []}),
        encoding="utf-8",
    )

    with raises(ValueError, match="version must be 8"):
        _battle_harness()._read_cases_file(cases_path)


def test_cases_file_rejects_duplicate_case_ids_and_prompts(tmp_path: Path) -> None:
    harness = _battle_harness()
    duplicate_cases = [
        {"id": "case-a", "prompt": "Build a report."},
        {"id": "case-b", "prompt": "Build a report."},
    ]
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps({"version": 8, "cases": duplicate_cases}), encoding="utf-8"
    )

    with raises(ValueError, match="duplicate prompt"):
        harness._read_cases_file(cases_path)

    duplicate_cases[1] = {"id": "case-a", "prompt": "Build another report."}
    cases_path.write_text(
        json.dumps({"version": 8, "cases": duplicate_cases}), encoding="utf-8"
    )

    with raises(ValueError, match="duplicate case id"):
        harness._read_cases_file(cases_path)


def test_cases_file_rejects_misspelled_evidence_posture_key(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": 8,
                "cases": [
                    {
                        "id": "bad-posture-key",
                        "prompt": "Build a report.",
                        "expected": {
                            "expected_classifier_slotz": [
                                {"slot_name": "terminal_output"}
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with raises(ValueError, match="unknown evidence-posture keys"):
        _battle_harness()._read_cases_file(cases_path)


def test_harness_checks_document_render_mode_and_renderer_binding() -> None:
    harness = _battle_harness()
    plan = _document_plan(
        terminal_mode="render_verbatim",
        terminal_input_source="previous_step",
    )

    summary = harness._summarize_plan(plan)
    report = harness._quality_report(
        plan=plan,
        summary=summary,
        expected={
            "terminal_output_type": "pdf",
            "expected_output_modes": ["pass_through", "render_verbatim"],
            "forbid_input_sources": ["all_previous_steps"],
        },
        event_summary={},
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["expected_output_modes"]["passed"] is True
    assert checks["forbid_input_sources"]["passed"] is True
    assert checks["terminal_document_output_mode"]["passed"] is True
    assert checks["terminal_document_output_mode"]["expected"] == "render_verbatim"
    assert checks["renderer_previous_step_bound"]["passed"] is True
    assert report["metrics"]["renderer_is_previous_step_bound"] is True

    bad_plan = _document_plan(
        terminal_mode="pass_through",
        terminal_input_source="all_previous_steps",
    )
    bad_summary = harness._summarize_plan(bad_plan)
    bad_report = harness._quality_report(
        plan=bad_plan,
        summary=bad_summary,
        expected={
            "terminal_output_type": "pdf",
            "expected_output_modes": ["pass_through", "render_verbatim"],
            "forbid_input_sources": ["all_previous_steps"],
        },
        event_summary={},
    )

    bad_checks = {check["name"]: check for check in bad_report["checks"]}
    assert bad_checks["expected_output_modes"]["passed"] is False
    assert bad_checks["forbid_input_sources"]["passed"] is False
    assert bad_checks["terminal_document_output_mode"]["passed"] is False
    assert bad_checks["renderer_previous_step_bound"]["passed"] is False
    assert bad_report["metrics"]["renderer_is_previous_step_bound"] is False


def test_classifier_posture_gate_rejects_each_mutated_dimension() -> None:
    harness = _battle_harness()
    expected = {
        "expected_classifier_slots": [
            {
                "slot_name": "report_disposition",
                "value": "both",
                "confidence": "high",
                "evidence_level": "explicit",
                "required_source_kinds": ["user_message"],
                "evidence_contains": ["samlad rapport"],
            }
        ],
        "expected_file_roles": [
            {
                "file_index": 0,
                "role": "example_output",
                "confidence": "high",
                "evidence_level": "explicit",
                "coverage": "fully_seen",
                "required_source_kinds": ["user_message"],
            }
        ],
        "expected_assumption_topics": ["source labels"],
        "forbidden_assumption_topics": ["invented default"],
    }

    def checks_for(diagnostics: dict[str, object]) -> dict[str, dict[str, object]]:
        report = harness._quality_report(
            plan={},
            summary={},
            expected=expected,
            event_summary={},
            classifier_diagnostics=diagnostics,
            attached_file_ids=("file-1",),
        )
        return {check["name"]: check for check in report["checks"]}

    baseline_checks = checks_for(_classifier_diagnostics())
    assert baseline_checks["classifier_slot:report_disposition"]["passed"] is True
    assert baseline_checks["classifier_file_role:file_index_0"]["passed"] is True
    assert baseline_checks["expected_assumption_topics"]["passed"] is True
    assert baseline_checks["forbidden_assumption_topics"]["passed"] is True

    mutations = (
        (
            "slots",
            "value",
            "synthesized_overview",
            "classifier_slot:report_disposition",
        ),
        ("slots", "confidence", "low", "classifier_slot:report_disposition"),
        ("slots", "evidence_level", "inferred", "classifier_slot:report_disposition"),
        (
            "file_roles",
            "role",
            "reference_material",
            "classifier_file_role:file_index_0",
        ),
        ("file_roles", "confidence", "medium", "classifier_file_role:file_index_0"),
        (
            "file_roles",
            "evidence_level",
            "inferred",
            "classifier_file_role:file_index_0",
        ),
    )
    for collection, field, value, check_name in mutations:
        mutated = json.loads(json.dumps(_classifier_diagnostics()))
        mutated["classifier_runs"][0][collection][0][field] = value
        assert checks_for(mutated)[check_name]["passed"] is False

    wrong_source = json.loads(json.dumps(_classifier_diagnostics()))
    wrong_source["classifier_runs"][0]["source_inventory"][0]["kind"] = "uploaded_file"
    assert (
        checks_for(wrong_source)["classifier_slot:report_disposition"]["passed"]
        is False
    )

    wrong_coverage = json.loads(json.dumps(_classifier_diagnostics()))
    wrong_coverage["classifier_runs"][0]["source_inventory"][1]["coverage"] = (
        "inventory_only"
    )
    assert (
        checks_for(wrong_coverage)["classifier_file_role:file_index_0"]["passed"]
        is False
    )

    forbidden_assumption = json.loads(json.dumps(_classifier_diagnostics()))
    forbidden_assumption["classifier_runs"][0]["assumptions"].append(
        "Invented default for report layout."
    )
    assert (
        checks_for(forbidden_assumption)["forbidden_assumption_topics"]["passed"]
        is False
    )

    negative_report = harness._quality_report(
        plan={},
        summary={},
        expected={"forbid_classifier_commit_grade_slots": ["report_disposition"]},
        event_summary={},
        classifier_diagnostics=_classifier_diagnostics(),
    )
    negative_checks = {check["name"]: check for check in negative_report["checks"]}
    assert negative_checks["forbid_classifier_commit_grade_slots"]["passed"] is False


def test_harness_allows_template_fill_document_terminal_without_renderer_binding() -> (
    None
):
    harness = _battle_harness()
    plan = _document_plan(
        terminal_mode="template_fill",
        terminal_input_source="flow_input",
        terminal_output_type="docx",
    )

    summary = harness._summarize_plan(plan)
    report = harness._quality_report(
        plan=plan,
        summary=summary,
        expected={
            "terminal_output_type": "docx",
            "terminal_document_output_mode": "template_fill",
        },
        event_summary={},
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["terminal_document_output_mode"]["passed"] is True
    assert "renderer_previous_step_bound" not in checks


def test_harness_can_fail_extra_post_json_text_helper() -> None:
    harness = _battle_harness()
    plan = _document_plan_with_extra_text_helper()

    summary = harness._summarize_plan(plan)
    report = harness._quality_report(
        plan=plan,
        summary=summary,
        expected={
            "terminal_output_type": "pdf",
            "max_post_json_text_cleanup_steps": 1,
        },
        event_summary={},
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["max_post_json_text_cleanup_steps"]["passed"] is False
    assert checks["max_post_json_text_cleanup_steps"]["actual"] == 2
    assert report["metrics"]["post_json_text_cleanup_step_count"] == 2


def test_harness_checks_question_count_before_plan_exists() -> None:
    harness = _battle_harness()

    report = harness._quality_report(
        plan=None,
        summary={"has_plan": False},
        expected={
            "allow_question_instead_of_plan": True,
            "expected_question_event_count": 1,
            "min_question_event_count": 1,
            "max_question_event_count": 1,
            "expected_question_event_ids": ["report_disposition"],
        },
        event_summary={
            "question_event_count": 1,
            "question_event_ids": ["report_disposition"],
        },
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert checks["plan_or_structured_question"]["passed"] is True
    assert checks["expected_question_event_count"]["passed"] is True
    assert checks["min_question_event_count"]["passed"] is True
    assert checks["max_question_event_count"]["passed"] is True
    assert checks["expected_question_event_ids"]["passed"] is True

    bad_report = harness._quality_report(
        plan=None,
        summary={"has_plan": False},
        expected={
            "allow_question_instead_of_plan": True,
            "expected_question_event_count": 1,
            "forbidden_question_event_ids": ["docx_output_mode"],
        },
        event_summary={
            "question_event_count": 2,
            "question_event_ids": ["docx_output_mode", "report_disposition"],
        },
    )
    bad_checks = {check["name"]: check for check in bad_report["checks"]}
    assert bad_checks["expected_question_event_count"]["passed"] is False
    assert bad_checks["forbidden_question_event_ids"]["passed"] is False


def test_harness_checks_directional_schema_fragments() -> None:
    harness = _battle_harness()
    valid_schema = {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"timestamp": {"type": "string"}},
                    "required": ["timestamp"],
                },
            }
        },
        "required": ["events"],
    }
    plan = {
        "proposal": {
            "spec": {
                "steps": [
                    {
                        "name": "Map events",
                        "input_source": "flow_input",
                        "input_type": "json",
                        "output_type": "json",
                        "input_contract": {
                            "type": "object",
                            "properties": {"payload": {"type": "object"}},
                        },
                        "output_contract": valid_schema,
                    }
                ]
            }
        }
    }
    expected = {
        "expected_input_contract_schema": {
            "type": "object",
            "properties": {"payload": {"type": "object"}},
        },
        "expected_output_contract_schema": valid_schema,
    }

    checks = {
        check["name"]: check
        for check in harness._quality_report(
            plan=plan,
            summary=harness._summarize_plan(plan),
            expected=expected,
            applied_flow={
                "steps": [
                    {
                        "step_order": 1,
                        "input_source": "flow_input",
                        "input_type": "json",
                        "output_type": "json",
                        "input_contract": plan["proposal"]["spec"]["steps"][0][
                            "input_contract"
                        ],
                        "output_contract": valid_schema,
                    }
                ]
            },
        )["checks"]
    }
    assert checks["expected_input_contract_schema"]["passed"] is True
    assert checks["expected_output_contract_schema"]["passed"] is True
    assert checks["applied_expected_input_contract_schema"]["passed"] is True
    assert checks["applied_expected_output_contract_schema"]["passed"] is True

    missing_applied_checks = {
        check["name"]: check
        for check in harness._quality_report(
            plan=plan,
            summary=harness._summarize_plan(plan),
            expected=expected,
            applied_flow={
                "steps": [
                    {
                        "step_order": 1,
                        "input_source": "flow_input",
                        "input_type": "json",
                        "output_type": "json",
                    }
                ]
            },
        )["checks"]
    }
    assert (
        missing_applied_checks["applied_expected_input_contract_schema"]["passed"]
        is False
    )
    assert (
        missing_applied_checks["applied_expected_output_contract_schema"]["passed"]
        is False
    )

    flat_plan = {
        "proposal": {
            "spec": {
                "steps": [
                    {
                        "name": "Flatten events",
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_type": "json",
                        "output_contract": {
                            "type": "object",
                            "properties": {
                                "events": {"type": "string"},
                                "timestamp": {"type": "string"},
                            },
                        },
                    }
                ]
            }
        }
    }
    flat_checks = {
        check["name"]: check
        for check in harness._quality_report(
            plan=flat_plan,
            summary=harness._summarize_plan(flat_plan),
            expected=expected,
        )["checks"]
    }
    assert flat_checks["expected_input_contract_schema"]["passed"] is False
    assert flat_checks["expected_output_contract_schema"]["passed"] is False

    swapped_plan = {
        "proposal": {
            "spec": {
                "steps": [
                    {
                        "name": "Swap contracts",
                        "input_source": "flow_input",
                        "input_type": "json",
                        "output_type": "json",
                        "input_contract": valid_schema,
                        "output_contract": plan["proposal"]["spec"]["steps"][0][
                            "input_contract"
                        ],
                    }
                ]
            }
        }
    }
    swapped_checks = {
        check["name"]: check
        for check in harness._quality_report(
            plan=swapped_plan,
            summary=harness._summarize_plan(swapped_plan),
            expected=expected,
        )["checks"]
    }
    assert swapped_checks["expected_input_contract_schema"]["passed"] is False
    assert swapped_checks["expected_output_contract_schema"]["passed"] is False


def test_artifact_warning_allows_document_body_copy() -> None:
    harness = _battle_harness()
    summary = {
        "terminal_output_type": "pdf",
        "steps": [
            {"order": 1, "output_type": "json", "name": "Läs dokument"},
            {
                "order": 2,
                "output_type": "text",
                "name": "Sammanställ rapport",
                "instruction_excerpt": "Presentera resultaten dokument för dokument.",
            },
            {"order": 3, "output_type": "pdf", "name": "Rendera PDF"},
        ],
    }

    assert harness._non_terminal_artifact_confusion_steps(summary) == []

    summary["steps"][1]["instruction_excerpt"] = "Rendera PDF-innehållet."

    assert harness._non_terminal_artifact_confusion_steps(summary) == [2]


def test_field_expectations_require_explicit_aliases() -> None:
    harness = _battle_harness()
    summary = {
        "steps": [
            {
                "output_contract_properties": ["document_date"],
                "output_contract_leaf_properties": ["document_date"],
            }
        ]
    }

    missing_alias_report = harness._quality_report(
        plan={},
        summary=summary,
        expected={"expected_leaf_output_field_groups": [["date"]]},
        event_summary={},
    )
    explicit_alias_report = harness._quality_report(
        plan={},
        summary=summary,
        expected={"expected_leaf_output_field_groups": [["date", "document_date"]]},
        event_summary={},
    )

    missing_checks = {check["name"]: check for check in missing_alias_report["checks"]}
    explicit_checks = {
        check["name"]: check for check in explicit_alias_report["checks"]
    }
    assert missing_checks["expected_leaf_output_fields"]["passed"] is False
    assert explicit_checks["expected_leaf_output_fields"]["passed"] is True


def test_field_expectations_include_nested_container_properties() -> None:
    harness = _battle_harness()
    plan = {
        "proposal": {
            "spec": {
                "flow_name": "Nested output",
                "steps": [
                    {
                        "plan_step_ref": "step_a",
                        "name": "Read source",
                        "input_source": "flow_input",
                        "input_type": "document",
                        "output_type": "json",
                        "output_mode": "pass_through",
                        "output_contract": {
                            "type": "object",
                            "properties": {
                                "saknade_uppgifter": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "punkt": {"type": "string"},
                                        },
                                    },
                                }
                            },
                        },
                    }
                ],
            }
        }
    }

    summary = harness._summarize_plan(plan)
    report = harness._quality_report(
        plan=plan,
        summary=summary,
        expected={
            "expected_leaf_output_field_groups": [
                ["missing_information", "saknade_uppgifter"]
            ]
        },
        event_summary={},
    )

    checks = {check["name"]: check for check in report["checks"]}
    assert summary["steps"][0]["output_contract_nested_properties"] == [
        "saknade_uppgifter",
        "punkt",
    ]
    assert checks["expected_leaf_output_fields"]["passed"] is True


def test_leaf_retention_uses_terminal_json_but_keeps_document_analysis_fields() -> None:
    harness = _battle_harness()
    summary = {
        "terminal_output_type": "json",
        "steps": [
            {
                "output_type": "json",
                "output_contract_leaf_properties": ["decision", "owner"],
            },
            {
                "output_type": "json",
                "output_contract_leaf_properties": ["summary"],
            },
        ],
    }
    expected = {
        "expected_leaf_output_field_groups": [
            ["decision"],
            ["owner"],
        ]
    }

    terminal_json_report = harness._quality_report(
        plan={},
        summary=summary,
        expected=expected,
        event_summary={},
    )
    summary["terminal_output_type"] = "pdf"
    document_report = harness._quality_report(
        plan={},
        summary=summary,
        expected=expected,
        event_summary={},
    )

    terminal_check = {check["name"]: check for check in terminal_json_report["checks"]}[
        "expected_leaf_output_fields"
    ]
    document_check = {check["name"]: check for check in document_report["checks"]}[
        "expected_leaf_output_fields"
    ]
    assert terminal_check["passed"] is False
    assert terminal_check["actual"] == {
        "boundary": "terminal_json",
        "fields": ["summary"],
        "intermediate_only_matches": ["decision", "owner"],
    }
    assert document_check["passed"] is True
    assert document_check["actual"]["boundary"] == "all_steps"


def test_context_balance_pdf_case_sets_cleanup_cap() -> None:
    harness = _battle_harness()
    cases = harness._read_cases_file(
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_context_balance_cases.json"
    )

    pdf_case = next(
        case
        for case in cases
        if case.case_id == "document_pdf_source_retention_balance"
    )

    assert pdf_case.expected["max_post_json_text_cleanup_steps"] == 1


def test_case_fixtures_resolve_from_provisioning_not_environment() -> None:
    """A case names a fixture; the harness owns turning that into a file id.

    Under the previous binding a case named an environment variable, so a case
    ran only where someone had exported the right value and the corpus was not
    portable at all.
    """

    harness = _battle_harness()
    case = harness.BattleCase(
        case_id="attachment_docx_template_placeholders_to_fields",
        prompt="Build a DOCX flow.",
        attachments=("generic_case_template.docx",),
    )
    provisioned = {
        "generic_case_template.docx": {
            "file_id": "file-template-1",
            "content_sha256": "0" * 64,
            "path": "scripts/fixtures/ai_builder_battle/generic_case_template.docx",
        }
    }

    assert harness._case_file_ids(case, provisioned) == ("file-template-1",)

    with raises(ValueError, match="was never provisioned"):
        harness._case_file_ids(case, {})


def test_unknown_fixture_name_fails_when_the_corpus_is_read(tmp_path: Path) -> None:
    """A broken fixture reference costs a second, not forty minutes.

    The old binding could only discover a missing fixture live, mid-suite, and
    then skipped the case rather than stopping — which is how the flagship
    runtime sentinel dropped out of six consecutive passes unnoticed.
    """

    harness = _battle_harness()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": harness.SUPPORTED_CASES_FILE_VERSION,
                "cases": [
                    {
                        "id": "bad-fixture",
                        "prompt": "Bygg ett flöde från den bifogade mallen.",
                        "attachments": ["no_such_template.docx"],
                        "expected": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with raises(ValueError, match="names unknown fixture"):
        harness._read_cases_file(cases_path)


def test_fixture_whose_bytes_drifted_stops_the_run(tmp_path: Path) -> None:
    """Content, not a name, is what a case attaches.

    Verifying before upload is what makes the question a case asks portable:
    edited or corrupted fixture bytes stop the suite instead of quietly
    changing what was measured.
    """

    harness = _battle_harness()
    manifest = harness._fixture_manifest()
    name = "05_lokalkalkyl.csv"

    assert harness._verified_fixture_path(name, manifest).is_file()

    with raises(ValueError, match="does not match its manifest hash"):
        harness._verified_fixture_path(name, {**manifest, name: "0" * 64})

    with raises(ValueError, match="Unknown battle fixture"):
        harness._verified_fixture_path("no_such_fixture.docx", manifest)


def test_live_bundle_is_immutable_and_owner_only(tmp_path: Path) -> None:
    harness = _battle_harness()
    bundle = {"created_at": "20260713T120000", "marker": "original"}

    bundle_path = harness._write_bundle(tmp_path, bundle, suffix="required-case")

    assert bundle_path.stat().st_mode & 0o777 == 0o600
    with raises(FileExistsError):
        harness._write_bundle(
            tmp_path,
            {**bundle, "marker": "replacement"},
            suffix="required-case",
        )
    assert json.loads(bundle_path.read_text())["marker"] == "original"


def test_reanalysis_preserves_live_provenance_and_records_source_hash(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    source_path = tmp_path / "live.json"
    source_bundle = _complete_reanalysis_bundle(
        harness,
        case_id="live-case",
        expected={},
    )
    source_provenance = source_bundle["live_execution_provenance"]
    source_path.write_text(
        json.dumps(source_bundle),
        encoding="utf-8",
    )
    source_bytes = source_path.read_bytes()

    output_dir = tmp_path / "reanalyzed"
    assert (
        harness._reanalyze_bundles(
            bundle_paths=[source_path],
            output_dir=output_dir,
        )
        == 0
    )

    assert source_path.read_bytes() == source_bytes
    reanalyzed = json.loads(next(output_dir.iterdir()).read_text())
    assert reanalyzed["artifact_mode"] == "reanalysis"
    assert reanalyzed["live_execution_provenance"] == source_provenance
    assert reanalyzed["reanalysis_provenance"]["source_bundle_sha256"] == (
        hashlib.sha256(source_bytes).hexdigest()
    )
    assert (
        reanalyzed["reanalysis_provenance"]["source_authenticity"]
        == "unverified_standalone"
    )
    assert "evidence_report" not in reanalyzed


def test_evidence_report_rejects_co_mutated_model_identity() -> None:
    harness = _battle_harness()
    bundle = _complete_reanalysis_bundle(harness, case_id="model-drift", expected={})
    bundle["interactions"][0]["events"][0]["data"]["last_model"] = "openai/gpt-b"
    bundle["classifier_diagnostics"]["classifier_runs"][0]["model"] = "gpt-b"
    model = bundle["live_execution_provenance"]["model"]
    model.update(
        {
            "expected_observed_ids": ["openai/gpt-b"],
            "planner_observations": [
                {"interaction_index": 1, "model_id": "openai/gpt-b"}
            ],
            "planner_observed_ids": ["openai/gpt-b"],
            "classifier_observed_ids": ["openai/gpt-b"],
            "observed_ids": ["openai/gpt-b"],
            "observed_matches_resolved": True,
        }
    )
    model_payload = {key: value for key, value in model.items() if key != "sha256"}
    model["sha256"] = harness._canonical_sha256(model_payload)

    report = harness._observation_evidence_report(bundle)

    assert report["valid"] is False
    assert "observation_model_provenance_consistent" in {
        check["name"] for check in report["failed_checks"]
    }


def test_classifier_evidence_requires_the_product_api_contract() -> None:
    harness = _battle_harness()
    valid = _complete_reanalysis_bundle(
        harness,
        case_id="classifier-contract",
        expected={},
    )["classifier_diagnostics"]
    assert harness._classifier_evidence_contract_is_valid(valid) is True

    for required_field in ("schema_version", "outcome", "model", "provider"):
        invalid = json.loads(json.dumps(valid))
        invalid["classifier_runs"][0].pop(required_field)
        assert harness._classifier_evidence_contract_is_valid(invalid) is False


def test_evidence_report_recomputes_attachment_identity_from_classifier() -> None:
    harness = _battle_harness()
    case = harness.BattleCase(
        case_id="attachment-identity",
        prompt="Build from the attachment.",
        attachments=("generic_case_template.docx",),
    )
    bundle = _complete_live_case_bundle(harness, case)
    bundle["case"]["file_ids"] = ["file-1"]
    bundle["classifier_diagnostics"]["classifier_runs"][0]["source_inventory"] = [
        {
            "source_id": "uploaded_file:file-1",
            "kind": "uploaded_file",
            "source_sha256": "e" * 64,
            "file_id": "file-1",
            "coverage": "fully_seen",
        }
    ]

    report = harness._observation_evidence_report(bundle)

    assert report["valid"] is False
    assert "observation_input_identity_consistent" in {
        check["name"] for check in report["failed_checks"]
    }


def test_evidence_report_rejects_classifier_diagnostics_from_another_session() -> None:
    harness = _battle_harness()
    bundle = _complete_reanalysis_bundle(
        harness,
        case_id="classifier-session-drift",
        expected={},
    )
    bundle["classifier_diagnostics"]["session_id"] = (
        "00000000-0000-0000-0000-000000000009"
    )

    report = harness._observation_evidence_report(bundle)

    assert report["valid"] is False
    assert "observation_input_identity_consistent" in {
        check["name"] for check in report["failed_checks"]
    }


def test_verified_reanalysis_requires_unchanged_suite_receipt_member(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    bundle_path = tmp_path / "live.json"
    bundle = _complete_reanalysis_bundle(harness, case_id="receipt-case", expected={})
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    bundle_sha256 = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    summary_path = tmp_path / "suite-summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "receipt_integrity": {"status": "complete"},
                "results": [
                    {
                        "case_id": "receipt-case",
                        "repetition": 1,
                        "case_contract_sha256": bundle["case_contract_sha256"],
                        "bundle_file": bundle_path.name,
                        "bundle_sha256": bundle_sha256,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    output_dir = tmp_path / "verified"
    assert (
        harness._reanalyze_bundles(
            bundle_paths=[bundle_path],
            output_dir=output_dir,
            suite_summary_path=summary_path,
        )
        == 0
    )
    reanalyzed = json.loads(next(output_dir.iterdir()).read_text())
    assert (
        reanalyzed["reanalysis_provenance"]["source_authenticity"]
        == "suite_receipt_verified"
    )

    bundle["unreceipted_change"] = True
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")
    assert (
        harness._reanalyze_bundles(
            bundle_paths=[bundle_path],
            output_dir=tmp_path / "modified",
            suite_summary_path=summary_path,
        )
        == 1
    )


def test_reanalysis_rejects_incomplete_or_non_live_evidence(tmp_path: Path) -> None:
    harness = _battle_harness()
    valid_bundle = _complete_reanalysis_bundle(
        harness,
        case_id="live-case",
        expected={},
    )
    invalid_bundles = [
        {**valid_bundle, "artifact_schema_version": "ai-builder-live-release.v2"},
        {**valid_bundle, "artifact_mode": "live_execution_failure"},
        {**valid_bundle, "interactions": []},
        {**valid_bundle, "live_execution_provenance": None},
    ]

    bad_contract = json.loads(json.dumps(valid_bundle))
    bad_contract["case_contract_sha256"] = "f" * 64
    invalid_bundles.append(bad_contract)

    bad_source = json.loads(json.dumps(valid_bundle))
    bad_source["live_execution_provenance"]["source"]["revision_sha256"] = "f" * 64
    invalid_bundles.append(bad_source)

    bad_input = json.loads(json.dumps(valid_bundle))
    bad_input["observation_input_identity"]["sha256"] = "f" * 64
    invalid_bundles.append(bad_input)

    missing_interaction_model = json.loads(json.dumps(valid_bundle))
    missing_interaction_model["interactions"].append({"events": []})
    invalid_bundles.append(missing_interaction_model)

    boolean_usage = json.loads(json.dumps(valid_bundle))
    boolean_usage["live_execution_provenance"]["usage"]["model_calls"] = True
    invalid_bundles.append(boolean_usage)

    boolean_raw_read = json.loads(json.dumps(valid_bundle))
    boolean_raw_read["live_execution_provenance"]["usage"]["raw_reads"][
        "classifier_run_count"
    ] = False
    invalid_bundles.append(boolean_raw_read)

    for invalid_bundle in invalid_bundles:
        with raises(ValueError):
            harness._validated_reanalysis_bundle(
                tmp_path / "invalid.json", invalid_bundle
            )


def test_suite_result_does_not_evaluate_invalid_live_evidence(tmp_path: Path) -> None:
    harness = _battle_harness()
    bundle = _complete_reanalysis_bundle(
        harness,
        case_id="invalid-evidence",
        expected={},
    )
    bundle["observation_input_identity"]["sha256"] = "f" * 64
    bundle_path = tmp_path / "invalid-evidence.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    result = harness._suite_result(harness.seal_observation(bundle), bundle_path)

    assert result["observation_status"] == "invalid_evidence"
    assert result["expectation_verdict"] == "not_evaluated"
    assert result["evidence_valid"] is False
    assert result["evidence_failed_check_count"] > 0


def test_suite_result_keeps_error_terminated_journey_outcome(
    tmp_path: Path,
) -> None:
    # An error-terminated turn has no provenance to validate; the journey
    # outcome is the truth (13 builder_error rows were masked as
    # invalid_evidence in the 2026-08-06 checkpoint).
    harness = _battle_harness()
    bundle = _complete_reanalysis_bundle(
        harness,
        case_id="error-terminated",
        expected={},
    )
    bundle["observation_input_identity"]["sha256"] = "f" * 64
    journey = bundle.setdefault("journey", {})
    assert isinstance(journey, dict)
    journey["outcome_class"] = "builder_error"
    bundle_path = tmp_path / "error-terminated.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    result = harness._suite_result(harness.seal_observation(bundle), bundle_path)

    assert result["outcome_class"] == "builder_error"
    assert result["observation_status"] == "error_terminated"
    assert result["expectation_verdict"] == "not_evaluated"


@mark.parametrize(
    ("diagnostics_session_id", "expected_error"),
    [
        (_TEST_SESSION_ID, None),
        (
            "00000000-0000-0000-0000-000000000009",
            "Classifier diagnostics do not belong to the session",
        ),
    ],
)
def test_execute_flow_case_requires_matching_diagnostics_before_scoring_error(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    diagnostics_session_id: str,
    expected_error: str | None,
) -> None:
    harness = _battle_harness()
    case = harness.BattleCase(
        case_id="typed-builder-error",
        prompt="Build and run the Flow.",
        apply_plan=True,
        execute_flow=True,
        runtime_files=("05_lokalkalkyl.csv",),
        expected={
            "expected_runtime_evidence": {
                "source_file_count": 1,
                "source_record_count": 1,
                "required_final_field_label_groups": [["summary"]],
                "required_visible_degradation_markers": [["framgår ej"]],
                "source_display_count": 1,
                "model_call_count": 1,
                "max_total_tokens": 10,
            }
        },
    )
    config = harness.ApiConfig(
        base_url="http://localhost:8123/api/v1",
        api_key="test-key",
        timeout_seconds=1,
    )

    def request_json(**kwargs: object) -> dict[str, object]:
        path = kwargs["path"]
        method = kwargs["method"]
        if method == "POST" and path == "/flows/ai-builder/sessions":
            return {"session_id": _TEST_SESSION_ID}
        if path == f"/flows/ai-builder/sessions/{_TEST_SESSION_ID}/models":
            return {
                "default_model_id": "model-a",
                "models": [{"id": "model-a", "name": "gpt-a", "provider": "openai"}],
            }
        if path == f"/flows/ai-builder/sessions/{_TEST_SESSION_ID}":
            return {
                "latest_plan_id": None,
                "telemetry": {
                    "llm_calls_made_total": 0,
                    "repair_attempts_total": 0,
                    "parse_repair_attempts_total": 0,
                    "prompt_tokens_total": 0,
                    "completion_tokens_total": 0,
                    "total_tokens_total": 0,
                    "wall_clock_ms_total": 1,
                },
            }
        if path.endswith("/_diagnostics/classifier-slots"):
            return {"session_id": diagnostics_session_id, "classifier_runs": []}
        raise AssertionError(f"unexpected request: {method} {path}")

    monkeypatch.setattr(harness, "_request_json", request_json)
    monkeypatch.setattr(
        harness,
        "_send_message_stream",
        lambda **_kwargs: iter(
            [
                {
                    "event": "error",
                    "data": {
                        "code": "session_message_in_progress",
                        "message": "Another message is already in progress.",
                    },
                }
            ]
        ),
    )
    monkeypatch.setattr(harness, "_optional_request_json", lambda **_kwargs: None)
    monkeypatch.setattr(
        harness,
        "_git_output",
        lambda *args: "a" * 40 if args == ("rev-parse", "HEAD") else "",
    )

    def run_case() -> dict[str, object]:
        return harness._run_case(
            case=case,
            config=config,
            args=SimpleNamespace(
                space_id="space-1",
                model_id="model-a",
                file_ids=(),
                ui_language="sv",
                auto_confirm_requirements=False,
                confirm_message=harness.DEFAULT_CONFIRM_MESSAGE,
                timeout_seconds=1,
            ),
            existing_session_id=None,
            artifact_output_dir=tmp_path,
        )

    if expected_error is not None:
        with raises(ValueError, match=expected_error):
            run_case()
        return

    bundle = run_case()

    assert bundle["artifact_mode"] == "live_execution"
    assert bundle["journey"]["outcome_class"] == "builder_error"
    runtime_checks = [
        check
        for check in bundle["quality_report"]["checks"]
        if check["name"].startswith("runtime_")
    ]
    assert runtime_checks
    assert all(check["passed"] is False for check in runtime_checks)

    bundle["case_contract_sha256"] = harness._case_contract_sha256(case)
    bundle["repetition"] = 1
    observation_row = {
        **harness.seal_observation(bundle)["observation"],
        "bundle_file": "typed-builder-error.json",
        "bundle_sha256": "b" * 64,
    }
    observation = harness.observation_from_row(
        observation_row,
        where="typed builder error",
    )
    assert observation.observation_status == "error_terminated"
    assert observation.outcome_class == "builder_error"
    assert harness.observation_is_replacement_eligible(observation) is False


def test_acquisition_validity_ignores_product_failures_and_catches_execution_failures() -> (
    None
):
    """The instrument judges measurement, never the product.

    A product expectation failure must not invalidate a receipt - that is the
    release evaluator's call - while an execution failure must, because it
    means the observation was never measured cleanly.
    """
    harness = _battle_harness()

    clean = harness.acquisition_validity_checks(
        execution_failure_observation_count=0,
        invalid_evidence_observation_count=0,
    )
    assert all(check["passed"] for check in clean)
    assert not any("expectation" in check["name"] for check in clean)
    assert not any("quality" in check["name"] for check in clean)

    dirty = harness.acquisition_validity_checks(
        execution_failure_observation_count=1,
        invalid_evidence_observation_count=2,
    )
    assert (
        next(
            check
            for check in dirty
            if check["name"] == "execution_failure_observations"
        )["passed"]
        is False
    )
    invalid_evidence = next(
        check for check in dirty if check["name"] == "invalid_evidence_observations"
    )
    assert invalid_evidence["passed"] is False
    assert invalid_evidence["actual"] == 2


def test_acquisition_contract_is_non_configurable_and_reported(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)
    gate = harness.AcquisitionContract(
        required_case_ids=("required-positive",),
    )
    case = harness.BattleCase(
        case_id="required-positive",
        prompt="Build the required positive case.",
        required=True,
    )
    benchmark_case = harness.BattleCase(
        case_id="benchmark-negative",
        prompt="Build a non-sentinel benchmark case.",
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    monkeypatch.setattr(
        harness,
        "_release_run_identity",
        lambda **_: release_identity,
    )

    def execute_case(**kwargs: object) -> dict[str, object]:
        selected_case = kwargs["case"]
        assert isinstance(selected_case, harness.BattleCase)
        # The REQUIRED observation FAILS a product expectation. The
        # instrument must still exit 0: judging the product is the release
        # evaluator's job, and acquisition here is clean. The deleted
        # `max_required_quality_failures` gate failed exactly this run.
        return _complete_live_case_bundle(
            harness,
            selected_case,
            quality_checks=(
                [
                    {
                        "name": "expected_step_count",
                        "passed": False,
                        "expected": 2,
                        "actual": 1,
                    }
                ]
                if selected_case.required
                else []
            ),
        )

    monkeypatch.setattr(harness, "_run_case", execute_case)
    release_args = type(
        "Args",
        (),
        {"repetitions": 1, "space_id": "space-1", "model_id": "model-a"},
    )()
    exit_code = harness._run_suite(
        cases=[case, benchmark_case],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=release_args,
        output_dir=tmp_path,
        acquisition_contract=gate,
    )

    assert exit_code == 0
    suite_dir = next(tmp_path.glob("ai-builder-api-battle-suite-*"))
    assert suite_dir.stat().st_mode & 0o777 == 0o700
    manifest = json.loads((suite_dir / "release-manifest.json").read_text())
    # The acquisition contract is non-configurable, so the manifest declares
    # no thresholds: there is nothing an operator could have set.
    assert "thresholds" not in manifest
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    assert all(check["passed"] for check in summary["sentinel_acquisition_checks"])
    assert summary["sentinel_verdict"] == "pass"
    assert "release_verdict" not in summary
    assert summary["expectation_failed_observation_count"] == 1
    assert summary["required_expectation_failed_observation_count"] == 1
    assert summary["invalid_evidence_observation_count"] == 0
    assert summary["required_invalid_evidence_observation_count"] == 0
    required_result = next(
        result
        for result in summary["results"]
        if result["case_id"] == "required-positive"
    )
    assert required_result["observation_status"] == "completed"
    assert required_result["expectation_verdict"] == "fail"
    assert summary["sentinel_gate_scope"] == {
        "case_count": 1,
        "selected_case_count": 2,
        "observation_count": 1,
        "selected_observation_count": 2,
        "case_ids": ["required-positive"],
    }
    assert summary["artifact_mode"] == "live_execution_summary"


def test_release_run_fails_on_invalid_evidence_even_for_benchmark_cases(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Acquisition validity spans every SELECTED observation.

    A corrupt observation on a non-required benchmark case invalidates the
    whole release receipt: the instrument cannot certify a measurement it
    did not acquire cleanly, regardless of which case broke.
    """
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)
    gate = harness.AcquisitionContract(
        required_case_ids=("required-positive",),
    )
    case = harness.BattleCase(
        case_id="required-positive",
        prompt="Build the required positive case.",
        required=True,
    )
    benchmark_case = harness.BattleCase(
        case_id="benchmark-negative",
        prompt="Build a non-sentinel benchmark case.",
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    monkeypatch.setattr(
        harness,
        "_release_run_identity",
        lambda **_: release_identity,
    )

    def execute_case(**kwargs: object) -> dict[str, object]:
        selected_case = kwargs["case"]
        assert isinstance(selected_case, harness.BattleCase)
        bundle = _complete_live_case_bundle(harness, selected_case)
        if not selected_case.required:
            bundle["observation_input_identity"]["sha256"] = "f" * 64
        return bundle

    monkeypatch.setattr(harness, "_run_case", execute_case)
    release_args = type(
        "Args",
        (),
        {"repetitions": 1, "space_id": "space-1", "model_id": "model-a"},
    )()
    exit_code = harness._run_suite(
        cases=[case, benchmark_case],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=release_args,
        output_dir=tmp_path,
        acquisition_contract=gate,
    )

    assert exit_code == 1
    suite_dir = next(tmp_path.glob("ai-builder-api-battle-suite-*"))
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    assert summary["sentinel_verdict"] == "fail"
    assert summary["invalid_evidence_observation_count"] == 1
    assert summary["required_invalid_evidence_observation_count"] == 0
    failed_check = next(
        check
        for check in summary["sentinel_acquisition_checks"]
        if check["name"] == "invalid_evidence_observations"
    )
    assert failed_check["passed"] is False
    assert failed_check["actual"] == 1


def test_release_run_fails_on_benchmark_execution_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """An execution failure on a NON-required case fails acquisition."""
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)
    gate = harness.AcquisitionContract(
        required_case_ids=("required-positive",),
    )
    case = harness.BattleCase(
        case_id="required-positive",
        prompt="Build the required positive case.",
        required=True,
    )
    benchmark_case = harness.BattleCase(
        case_id="benchmark-negative",
        prompt="Build a non-sentinel benchmark case.",
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
        harness_sha256=hashlib.sha256(Path(harness.__file__).read_bytes()).hexdigest(),
        cases_sha256=hashlib.sha256(
            harness.DEFAULT_CASES_FILE.read_bytes()
        ).hexdigest(),
    )
    release_identity["target"] = {
        "expected_source_revision": "a" * 40,
        "verified": True,
    }
    monkeypatch.setattr(
        harness,
        "_release_run_identity",
        lambda **_: release_identity,
    )

    def execute_case(**kwargs: object) -> dict[str, object]:
        selected_case = kwargs["case"]
        assert isinstance(selected_case, harness.BattleCase)
        if not selected_case.required:
            raise ValueError("HTTP 404 from POST /sessions")
        bundle = _complete_live_case_bundle(harness, selected_case)
        build = release_identity["build"]
        assert isinstance(build, dict)
        bundle["live_execution_provenance"] = _live_provenance_fixture(
            harness,
            prompt=selected_case.prompt,
            harness_sha256=str(build["harness_sha256"]),
            cases_sha256=str(build["cases_sha256"]),
        )
        return bundle

    monkeypatch.setattr(harness, "_run_case", execute_case)
    release_args = type(
        "Args",
        (),
        {"repetitions": 1, "space_id": "space-1", "model_id": "model-a"},
    )()
    exit_code = harness._run_suite(
        cases=[case, benchmark_case],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=release_args,
        output_dir=tmp_path,
        acquisition_contract=gate,
    )

    assert exit_code == 1
    suite_dir = next(tmp_path.glob("ai-builder-api-battle-suite-*"))
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    assert summary["sentinel_verdict"] == "fail"
    assert summary["execution_failure_observation_count"] == 1
    failed_check = next(
        check
        for check in summary["sentinel_acquisition_checks"]
        if check["name"] == "execution_failure_observations"
    )
    assert failed_check["passed"] is False
    receipt = harness.load_recoverable_release_receipt(suite_dir)
    assert receipt.observations[1].observation_status == "execution_failure"
    failure_bundle = json.loads(
        (suite_dir / receipt.observations[1].bundle_file).read_text()
    )
    assert set(failure_bundle["live_execution_provenance"]) == {
        "mode",
        "source",
        "build",
        "model",
    }
    assert failure_bundle["live_execution_provenance"] == {
        "mode": "live_execution_failure",
        "source": release_identity["source"],
        "build": release_identity["build"],
        "model": release_identity["model"],
    }


def test_release_run_passes_when_a_required_case_dies_in_the_product(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """An error-terminated observation is a PRODUCT outcome, not a fault.

    The builder dying on a required case is exactly what a release run must
    be able to measure and report. The old `evidence_valid is False`
    predicate failed the whole receipt here; the status-based contract
    scores it.
    """
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)
    gate = harness.AcquisitionContract(
        required_case_ids=("required-positive",),
    )
    fixtures = (
        "01_protokoll_bun_2026_02_25.pdf",
        "02_tjansteskrivelse_underlag.docx",
        "03_barnkonsekvensanalys.docx",
        "04_remissvar.docx",
        "05_lokalkalkyl.csv",
        "06_tidigare_beslut.pdf",
    )
    case = harness.BattleCase(
        case_id="required-positive",
        prompt="Build the required positive case.",
        required=True,
        apply_plan=True,
        execute_flow=True,
        attachments=fixtures,
        runtime_files=fixtures,
    )
    manifest = harness._fixture_manifest()
    provisioned = {
        name: {
            "file_id": f"fixture-file-{index}",
            "content_sha256": manifest[name],
            "path": f"scripts/fixtures/ai_builder_battle/{name}",
        }
        for index, name in enumerate(fixtures, start=1)
    }
    monkeypatch.setattr(
        harness,
        "_provision_fixtures",
        lambda **_kwargs: provisioned,
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
        harness_sha256=hashlib.sha256(Path(harness.__file__).read_bytes()).hexdigest(),
        cases_sha256=hashlib.sha256(
            harness.DEFAULT_CASES_FILE.read_bytes()
        ).hexdigest(),
    )
    release_identity["target"] = {
        "expected_source_revision": "a" * 40,
        "verified": True,
    }
    monkeypatch.setattr(
        harness,
        "_release_run_identity",
        lambda **_: release_identity,
    )

    def execute_case(**kwargs: object) -> dict[str, object]:
        selected_case = kwargs["case"]
        assert isinstance(selected_case, harness.BattleCase)
        selected_provisioned = kwargs["provisioned_fixtures"]
        assert isinstance(selected_provisioned, Mapping)
        attached_file_ids = harness._case_file_ids(
            selected_case,
            selected_provisioned,
        )
        bundle = _complete_live_case_bundle(harness, selected_case)
        bundle_case = bundle["case"]
        assert isinstance(bundle_case, dict)
        bundle_case["file_ids"] = list(attached_file_ids)
        build = release_identity["build"]
        assert isinstance(build, dict)
        provenance = _live_provenance_fixture(
            harness,
            prompt=selected_case.prompt,
            harness_sha256=str(build["harness_sha256"]),
            cases_sha256=str(build["cases_sha256"]),
        )
        terminal_model = harness._resolved_model_identity(
            session_models={
                "models": [{"id": "model-a", "name": "gpt-a", "provider": "openai"}]
            },
            requested_model_id="model-a",
            planner_observed_model_ids=[],
            classifier_observed_model_ids=[],
            planner_interaction_count=1,
            planner_observations=[],
            missing_planner_interaction_indices=[],
            terminal_error_interaction_indices=[1],
        )
        provenance["model"] = {
            **terminal_model,
            "sha256": harness._canonical_sha256(terminal_model),
        }
        bundle.update(
            {
                "plan_id": None,
                "plan": None,
                "plan_summary": {},
                "interactions": [{"events": [{"event": "error", "data": {}}]}],
                "journey": {"outcome_class": "builder_error"},
                "classifier_diagnostics": {
                    "session_id": "00000000-0000-0000-0000-000000000001",
                    "classifier_runs": [],
                },
                "runtime_evidence": None,
                "live_execution_provenance": provenance,
                "observation_input_identity": harness._observation_input_identity(
                    case=selected_case,
                    session_id=_TEST_SESSION_ID,
                    attached_file_ids=attached_file_ids,
                    classifier_diagnostics={
                        "session_id": "00000000-0000-0000-0000-000000000001",
                        "classifier_runs": [],
                    },
                    runtime_evidence=None,
                    provisioned_fixtures=selected_provisioned,
                ),
            }
        )
        return bundle

    monkeypatch.setattr(harness, "_run_case", execute_case)
    release_args = type(
        "Args",
        (),
        {"repetitions": 1, "space_id": "space-1", "model_id": "model-a"},
    )()
    exit_code = harness._run_suite(
        cases=[case],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=release_args,
        output_dir=tmp_path,
        acquisition_contract=gate,
    )

    assert exit_code == 0
    suite_dir = next(tmp_path.glob("ai-builder-api-battle-suite-*"))
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    assert summary["sentinel_verdict"] == "pass"
    assert summary["invalid_evidence_observation_count"] == 0
    assert summary["required_invalid_evidence_observation_count"] == 0
    assert summary["identity_failed_check_count"] == 0
    result = summary["results"][0]
    assert result["observation_status"] == "error_terminated"
    assert result["outcome_class"] == "builder_error"
    assert result["evidence_valid"] is False
    receipt = harness.load_recoverable_release_receipt(suite_dir)
    assert receipt.observations[0].observation_status == "error_terminated"
    assert harness.observation_is_replacement_eligible(receipt.observations[0]) is False


@mark.parametrize(
    ("attachment_state", "expected_status", "expected_pass"),
    [
        ("not_required", "not_required", True),
        ("not_observed", "not_observed", True),
        ("complete", "complete", True),
        ("invalid", "invalid", False),
        ("wrong_session", "invalid", False),
        ("incomplete", "incomplete", False),
    ],
)
def test_terminal_input_identity_accepts_only_valid_classifier_phases(
    attachment_state: str,
    expected_status: str,
    expected_pass: bool,
) -> None:
    harness = _battle_harness()
    attachment_fixture = "generic_case_template.docx"
    attachment_file_id = "00000000-0000-0000-0000-000000000002"
    runtime_fixture = "generic_case_template.docx"
    attachments = (
        ()
        if attachment_state in {"not_required", "invalid", "wrong_session"}
        else (attachment_fixture,)
    )
    case = harness.BattleCase(
        case_id=f"terminal-{attachment_state}",
        prompt="Build and run the Flow.",
        required=True,
        apply_plan=True,
        execute_flow=True,
        attachments=attachments,
        runtime_files=(runtime_fixture,),
    )
    manifest = harness._fixture_manifest()
    provisioned = (
        {
            attachment_fixture: {
                "file_id": attachment_file_id,
                "content_sha256": manifest[attachment_fixture],
                "path": f"scripts/fixtures/ai_builder_battle/{attachment_fixture}",
            }
        }
        if attachments
        else {}
    )
    attached_file_ids = (attachment_file_id,) if attachments else ()
    if attachment_state == "invalid":
        classifier_diagnostics: dict[str, object] = {
            "session_id": "not-a-uuid",
            "classifier_runs": [],
        }
    elif attachment_state == "wrong_session":
        classifier_diagnostics = {
            "session_id": "00000000-0000-0000-0000-000000000009",
            "classifier_runs": [],
        }
    elif attachment_state in {"not_required", "not_observed"}:
        classifier_diagnostics = {
            "session_id": "00000000-0000-0000-0000-000000000001",
            "classifier_runs": [],
        }
    else:
        classifier_diagnostics = _classifier_diagnostics()
        classifier_runs = classifier_diagnostics["classifier_runs"]
        assert isinstance(classifier_runs, list)
        classifier_run = classifier_runs[0]
        assert isinstance(classifier_run, dict)
        source_inventory = classifier_run["source_inventory"]
        assert isinstance(source_inventory, list)
        uploaded_source = source_inventory[-1]
        assert isinstance(uploaded_source, dict)
        uploaded_source["file_id"] = attachment_file_id
        file_roles = classifier_run["file_roles"]
        assert isinstance(file_roles, list)
        file_role = file_roles[0]
        assert isinstance(file_role, dict)
        file_role["file_id"] = attachment_file_id
        if attachment_state == "incomplete":
            other_file_id = "00000000-0000-0000-0000-000000000003"
            uploaded_source["file_id"] = other_file_id
            file_role["file_id"] = other_file_id

    input_identity = harness._observation_input_identity(
        case=case,
        session_id=_TEST_SESSION_ID,
        attached_file_ids=attached_file_ids,
        classifier_diagnostics=classifier_diagnostics,
        runtime_evidence=None,
        provisioned_fixtures=provisioned,
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    provenance = _live_provenance_fixture(harness, prompt=case.prompt)
    terminal_model = harness._resolved_model_identity(
        session_models={
            "models": [{"id": "model-a", "name": "gpt-a", "provider": "openai"}]
        },
        requested_model_id="model-a",
        planner_observed_model_ids=[],
        classifier_observed_model_ids=[],
        planner_interaction_count=1,
        planner_observations=[],
        missing_planner_interaction_indices=[],
        terminal_error_interaction_indices=[1],
    )
    provenance["model"] = {
        **terminal_model,
        "sha256": harness._canonical_sha256(terminal_model),
    }

    checks = harness._required_case_identity_checks(
        case=case,
        release_identity=release_identity,
        provenance=provenance,
        journey_outcome="builder_error",
        observation_input_identity=input_identity,
    )

    input_check = next(
        check for check in checks if check["name"] == "suite_observation_input_identity"
    )
    assert input_identity["attachment_evidence_status"] == expected_status
    assert input_check["passed"] is expected_pass


def test_terminal_input_identity_rejects_unmapped_direct_attachment() -> None:
    harness = _battle_harness()
    fixture = "05_lokalkalkyl.csv"
    case = harness.BattleCase(
        case_id="terminal-unmapped-attachment",
        prompt="Build and run the Flow.",
        required=True,
        apply_plan=True,
        execute_flow=True,
        file_ids=("direct-file",),
        attachments=(fixture,),
        runtime_files=(fixture,),
    )
    manifest = harness._fixture_manifest()
    provisioned = {
        fixture: {
            "file_id": "fixture-file",
            "content_sha256": manifest[fixture],
            "path": f"scripts/fixtures/ai_builder_battle/{fixture}",
        }
    }
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    provenance = _live_provenance_fixture(harness, prompt=case.prompt)
    terminal_model = harness._resolved_model_identity(
        session_models={
            "models": [{"id": "model-a", "name": "gpt-a", "provider": "openai"}]
        },
        requested_model_id="model-a",
        planner_observed_model_ids=[],
        classifier_observed_model_ids=[],
        planner_interaction_count=1,
        planner_observations=[],
        missing_planner_interaction_indices=[],
        terminal_error_interaction_indices=[1],
    )
    provenance["model"] = {
        **terminal_model,
        "sha256": harness._canonical_sha256(terminal_model),
    }

    input_identity = harness._observation_input_identity(
        case=case,
        session_id=_TEST_SESSION_ID,
        attached_file_ids=("direct-file", "fixture-file"),
        classifier_diagnostics={
            "session_id": "00000000-0000-0000-0000-000000000001",
            "classifier_runs": [],
        },
        runtime_evidence=None,
        provisioned_fixtures=provisioned,
    )
    checks = harness._required_case_identity_checks(
        case=case,
        release_identity=release_identity,
        provenance=provenance,
        journey_outcome="builder_error",
        observation_input_identity=input_identity,
    )

    input_check = next(
        check for check in checks if check["name"] == "suite_observation_input_identity"
    )
    assert input_check["passed"] is False


@mark.parametrize(
    ("prior_usage_events", "expected_pass"),
    [
        (
            [{"event": "usage", "data": {"last_model": "openai/gpt-a"}}],
            True,
        ),
        (
            [{"event": "usage", "data": {"last_model": "openai/gpt-wrong"}}],
            False,
        ),
        (
            [
                {"event": "usage", "data": {"last_model": "openai/gpt-a"}},
                {"event": "usage", "data": {"last_model": "openai/gpt-other"}},
            ],
            False,
        ),
    ],
)
def test_terminal_model_identity_validates_prior_model_evidence(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    prior_usage_events: list[dict[str, object]],
    expected_pass: bool,
) -> None:
    harness = _battle_harness()
    case = harness.BattleCase(
        case_id="terminal-wrong-prior-model",
        prompt="Build the Flow.",
        required=True,
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    monkeypatch.setattr(
        harness,
        "_git_output",
        lambda *args: (
            ""
            if args == ("status", "--porcelain", "--untracked-files=no")
            else "a" * 40
        ),
    )
    cases_path = tmp_path / "cases.json"
    cases_path.write_text("{}", encoding="utf-8")
    provenance = harness._live_execution_provenance(
        case=case,
        cases_path=cases_path,
        latest_session={},
        classifier_diagnostics={
            "session_id": "00000000-0000-0000-0000-000000000001",
            "classifier_runs": [],
        },
        requested_model_id="model-a",
        session_models={
            "models": [{"id": "model-a", "name": "gpt-a", "provider": "openai"}]
        },
        interactions=[
            {"events": prior_usage_events},
            {"events": [{"event": "error", "data": {}}]},
        ],
    )

    checks = harness._required_case_identity_checks(
        case=case,
        release_identity=release_identity,
        provenance=provenance,
        journey_outcome="builder_error",
    )

    model_check = next(
        check for check in checks if check["name"] == "suite_requested_model_identity"
    )
    assert model_check["passed"] is expected_pass


def test_release_run_requires_explicit_model_before_execution(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    case = harness.BattleCase(
        case_id="required-model",
        prompt="Build it.",
        required=True,
    )
    gate = harness.AcquisitionContract(
        required_case_ids=(case.case_id,),
    )
    executed = False

    def run_case(**_: object) -> dict[str, object]:
        nonlocal executed
        executed = True
        return {}

    monkeypatch.setattr(harness, "_run_case", run_case)

    with raises(ValueError, match="requires --model-id"):
        harness._run_suite(
            cases=[case],
            config=harness.ApiConfig(
                base_url="http://localhost:8123/api/v1",
                api_key="test-key",
                timeout_seconds=1,
            ),
            args=SimpleNamespace(
                repetitions=1,
                space_id="space-1",
                model_id=None,
            ),
            output_dir=tmp_path,
            acquisition_contract=gate,
        )

    assert executed is False
    assert list(tmp_path.iterdir()) == []

    # Acquisition validity is measurement quality only: a product
    # expectation failure must NOT fail it, an execution failure must.
    assert all(
        check["passed"]
        for check in harness.acquisition_validity_checks(
            execution_failure_observation_count=0,
            invalid_evidence_observation_count=0,
        )
    )
    assert (
        next(
            check
            for check in harness.acquisition_validity_checks(
                execution_failure_observation_count=1,
                invalid_evidence_observation_count=0,
            )
            if check["name"] == "execution_failure_observations"
        )["passed"]
        is False
    )


def test_release_run_validates_failure_identity_before_acquisition(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    case = harness.BattleCase(
        case_id="required-identity",
        prompt="Build it.",
        required=True,
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    release_identity.pop("model")
    acquired = False

    monkeypatch.setattr(harness, "_release_run_identity", lambda **_: release_identity)

    def run_case(**_: object) -> dict[str, object]:
        nonlocal acquired
        acquired = True
        return {}

    monkeypatch.setattr(harness, "_run_case", run_case)

    with raises(ValueError, match="release identity has no model component"):
        harness._run_suite(
            cases=[case],
            config=harness.ApiConfig(
                base_url="http://localhost:8123/api/v1",
                api_key="test-key",
                timeout_seconds=1,
            ),
            args=SimpleNamespace(
                repetitions=1,
                space_id="space-1",
                model_id="model-1",
            ),
            output_dir=tmp_path,
            acquisition_contract=harness.AcquisitionContract(
                required_case_ids=(case.case_id,),
            ),
        )

    assert acquired is False
    assert list(tmp_path.iterdir()) == []


def test_release_receipt_version_defaults_to_v5_and_rejects_other_versions(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()

    gate = harness.AcquisitionContract(
        required_case_ids=("required-case",),
    )

    assert gate.artifact_schema_version == "ai-builder-live-release.v5"
    assert gate.artifact_schema_version == harness.SUPPORTED_RECEIPT_ARTIFACT_VERSION

    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": 8,
                "acquisition_contract": {
                    "artifact_schema_version": "ai-builder-live-release.unsupported",
                    "require_clean_source": False,
                },
                "cases": [
                    {
                        "id": "required-case",
                        "prompt": "Build the required case.",
                        "required": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cases = harness._read_cases_file(cases_path)
    with raises(ValueError, match="artifact_schema_version must be"):
        harness._read_acquisition_contract(cases_path, cases=cases)


def test_suite_receipts_preserve_canonical_case_identity_for_every_outcome(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)
    cases = [
        harness.BattleCase(
            case_id="success-case",
            prompt="Build the successful case.",
            required=True,
            complexity="medium",
            domain="municipality_records",
            cohorts=("foundation", "json"),
        ),
        harness.BattleCase(
            case_id="failed-case",
            prompt="Build the failed case.",
            complexity="hard",
            domain="municipality_procurement",
            cohorts=("runtime", "review"),
        ),
    ]
    release_identity = _release_identity_fixture(
        harness,
        case_id=cases[0].case_id,
        prompt=cases[0].prompt,
    )
    monkeypatch.setattr(harness, "_release_run_identity", lambda **_: release_identity)
    monkeypatch.setattr(harness, "_provision_fixtures", lambda **_: {})

    def run_case(*, case: object, **_: object) -> dict[str, object]:
        assert isinstance(case, harness.BattleCase)
        if case.case_id == "failed-case":
            raise ValueError("verified failure")
        return _complete_live_case_bundle(harness, case)

    monkeypatch.setattr(harness, "_run_case", run_case)

    exit_code = harness._run_suite(
        cases=cases,
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=type("Args", (), {"repetitions": 1, "space_id": "space-1"})(),
        output_dir=tmp_path,
    )

    assert exit_code == 0
    expected_identities = {
        case.case_id: {
            "id": case.case_id,
            "required": case.required,
            "complexity": case.complexity,
            "domain": case.domain,
            "cohorts": list(case.cohorts),
        }
        for case in cases
    }
    suite_dir = next(tmp_path.glob("ai-builder-api-battle-suite-*"))
    manifest = json.loads((suite_dir / "release-manifest.json").read_text())
    assert {
        row["case_identity"]["id"]: row["case_identity"]
        for row in manifest["selected_cases"]
    } == expected_identities

    bundles = [
        json.loads(path.read_text())
        for path in suite_dir.glob("ai-builder-api-battle-test-*.json")
    ]
    assert {
        bundle["case_identity"]["id"]: bundle["case_identity"] for bundle in bundles
    } == expected_identities

    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    assert {
        result["case_identity"]["id"]: result["case_identity"]
        for result in summary["results"]
    } == expected_identities
    results_by_case_id = {
        result["case_identity"]["id"]: result for result in summary["results"]
    }
    assert results_by_case_id["success-case"]["artifact_mode"] == "live_execution"
    assert results_by_case_id["success-case"]["observation_status"] == "completed"
    assert results_by_case_id["success-case"]["expectation_verdict"] == "pass"
    assert results_by_case_id["success-case"]["error"] is None
    assert (
        results_by_case_id["failed-case"]["artifact_mode"] == "live_execution_failure"
    )
    assert results_by_case_id["failed-case"]["observation_status"] == (
        "execution_failure"
    )
    assert results_by_case_id["failed-case"]["expectation_verdict"] == ("not_evaluated")
    assert results_by_case_id["failed-case"]["error"] == "verified failure"
    for result in results_by_case_id.values():
        bundle_path = suite_dir / result["bundle_file"]
        assert bundle_path.is_file()
        bundle = json.loads(bundle_path.read_text())
        sealed_row = {
            key: value
            for key, value in result.items()
            if key not in harness.BUNDLE_REFERENCE_FIELDS
        }
        assert sealed_row == bundle["observation"]
        assert (
            result["bundle_sha256"]
            == hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        )
        assert "bundle_path" not in result
    assert summary["outcome_class_summary"]["counts"] == {
        "execution_failure": 1,
        "unclassified": 1,
    }
    assert summary["receipt_integrity"]["status"] == "complete"
    assert summary["sentinel_verdict"] is None
    assert summary["artifact_mode"] == "live_execution_exploratory_summary"
    assert summary["observation_summary"] == {
        "status_counts": {
            "completed": 1,
            "execution_failure": 1,
        },
        "verdict_counts": {"not_evaluated": 1, "pass": 1},
    }


def test_case_contract_identity_covers_rubric_answers_fixtures_and_lifecycle() -> None:
    harness = _battle_harness()

    def contract_hash(**changes: object) -> str:
        values: dict[str, object] = {
            "case_id": "same-case",
            "prompt": "Bygg ett kommunalt flöde.",
            "expected": {"max_steps": 3},
            "configured_question_answers": {
                "terminal_output": {"selected_option_id": "structured_json"}
            },
            "attachments": ("generic_case_template.docx",),
        }
        values.update(changes)
        return harness._case_contract_sha256(harness.BattleCase(**values))

    baseline = contract_hash(file_ids=("space-a-file-id",))

    assert contract_hash(file_ids=("space-b-file-id",)) == baseline
    assert contract_hash(expected={"max_steps": 4}) != baseline
    assert (
        contract_hash(
            configured_question_answers={
                "terminal_output": {"selected_option_id": "pdf_document"}
            }
        )
        != baseline
    )
    # Attaching different bytes asks a different question, so the contract
    # hash must move. The env-var binding could not see this at all: the blob
    # behind a name could be replaced with the hash unchanged.
    assert contract_hash(attachments=("decision_letter_template.docx",)) != baseline
    assert contract_hash(attachments=()) != baseline
    assert contract_hash(apply_plan=True) != baseline


def test_suite_receipt_integrity_detects_missing_and_duplicate_observations(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    bundle_path = tmp_path / "case-a.json"
    harness._write_json_exclusive(bundle_path, {"case": "a"})
    bundle_sha256 = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
    expected = [
        {"case_id": "a", "repetition": 1, "case_contract_sha256": "a" * 64},
        {"case_id": "b", "repetition": 1, "case_contract_sha256": "b" * 64},
    ]
    duplicate = {
        "case_id": "a",
        "repetition": 1,
        "case_contract_sha256": "a" * 64,
        "bundle_file": bundle_path.name,
        "bundle_sha256": bundle_sha256,
    }

    integrity = harness._suite_receipt_integrity(
        expected_observations=expected,
        results=[duplicate, dict(duplicate)],
        suite_dir=tmp_path,
    )

    assert integrity["status"] == "partial"
    assert integrity["missing_observation_keys"] == [{"case_id": "b", "repetition": 1}]
    assert integrity["duplicate_observation_keys"] == [
        {"case_id": "a", "repetition": 1}
    ]


def test_suite_bundle_reference_survives_move_and_detects_tampering(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    bundle_path = suite_dir / "case-a.json"
    harness._write_json_exclusive(bundle_path, {"case": "a"})
    expected = [{"case_id": "a", "repetition": 1, "case_contract_sha256": "a" * 64}]
    result = {
        "case_id": "a",
        "repetition": 1,
        "case_contract_sha256": "a" * 64,
        "bundle_file": bundle_path.name,
        "bundle_sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
    }

    assert (
        harness._suite_receipt_integrity(
            expected_observations=expected,
            results=[result],
            suite_dir=suite_dir,
        )["status"]
        == "complete"
    )

    moved_suite_dir = tmp_path / "moved-suite"
    suite_dir.rename(moved_suite_dir)
    assert (
        harness._suite_receipt_integrity(
            expected_observations=expected,
            results=[result],
            suite_dir=moved_suite_dir,
        )["status"]
        == "complete"
    )

    (moved_suite_dir / result["bundle_file"]).write_text("tampered")
    tampered = harness._suite_receipt_integrity(
        expected_observations=expected,
        results=[result],
        suite_dir=moved_suite_dir,
    )
    assert tampered["status"] == "partial"
    assert tampered["invalid_bundle_references"] == [
        {"case_id": "a", "repetition": 1, "reason": "sha256_mismatch"}
    ]


def test_suite_identity_rechecks_a_to_b_before_green_summary(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)
    case = harness.BattleCase(
        case_id="required-identity",
        prompt="Build the required identity case.",
        required=True,
    )
    identity_a = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    identity_b = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
        harness_sha256="d" * 64,
    )
    identities = iter((identity_a, identity_b))
    monkeypatch.setattr(
        harness,
        "_release_run_identity",
        lambda **_: next(identities),
    )

    def successful_case(**_: object) -> dict[str, object]:
        return {
            "created_at": "20260713T120002",
            "artifact_mode": "live_execution",
            "live_execution_provenance": _live_provenance_fixture(
                harness,
                prompt=case.prompt,
            ),
            "observation_input_identity": _empty_observation_input_identity(harness),
            "case": {"id": case.case_id, "required": True},
            "session_id": "session-1",
            "plan_id": "plan-1",
            "plan_summary": {"step_count": 1},
            "event_summary": {},
            "quality_report": {"checks": [], "warnings": [], "metrics": {}},
        }

    monkeypatch.setattr(harness, "_run_case", successful_case)
    acquisition_contract = harness.AcquisitionContract(
        required_case_ids=(case.case_id,),
    )

    exit_code = harness._run_suite(
        cases=[case],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=type(
            "Args",
            (),
            {
                "repetitions": 1,
                "space_id": "space-1",
                "model_id": "model-a",
            },
        )(),
        output_dir=tmp_path,
        acquisition_contract=acquisition_contract,
    )

    assert exit_code == 1
    suite_dir = next(tmp_path.glob("ai-builder-api-battle-suite-*"))
    case_bundle = json.loads(
        next(suite_dir.glob("ai-builder-api-battle-test-*.json")).read_text()
    )
    assert case_bundle["release_identity"] == identity_a
    identity_check_names = {
        check["name"] for check in case_bundle["release_identity_checks"]
    }
    assert identity_check_names == {
        "suite_source_revision_identity",
        "suite_build_input_identity",
        "suite_requested_model_identity",
        "suite_case_prompt_identity",
        "suite_observation_input_identity",
    }
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    final_checks = {
        check["name"]: check for check in summary["release_identity_recheck_checks"]
    }
    assert final_checks["suite_build_identity_unchanged"]["passed"] is False
    assert summary["identity_failed_check_count"] == 1
    assert summary["sentinel_verdict"] == "fail"


def test_final_identity_probe_failure_still_writes_failed_summary(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)
    case = harness.BattleCase(
        case_id="required-final-probe",
        prompt="Build it.",
        required=True,
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    release_identity["target"] = {
        "expected_source_revision": "a" * 40,
        "verified": True,
    }
    calls = 0

    def release_identity_or_network_failure(**_: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return release_identity
        raise harness.URLError("target unavailable")

    monkeypatch.setattr(
        harness,
        "_release_run_identity",
        release_identity_or_network_failure,
    )
    monkeypatch.setattr(
        harness,
        "_run_case",
        lambda **_: {
            "created_at": "20260804T120000",
            "artifact_mode": "live_execution",
            "live_execution_provenance": _live_provenance_fixture(
                harness,
                prompt=case.prompt,
            ),
            "observation_input_identity": _empty_observation_input_identity(harness),
            "case": {"id": case.case_id, "required": True},
            "session_id": "session-1",
            "plan_id": "plan-1",
            "plan_summary": {"step_count": 1},
            "event_summary": {},
            "quality_report": {"checks": [], "warnings": [], "metrics": {}},
        },
    )
    gate = harness.AcquisitionContract(
        required_case_ids=(case.case_id,),
    )

    exit_code = harness._run_suite(
        cases=[case],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=SimpleNamespace(
            repetitions=1,
            space_id="space-1",
            model_id="model-a",
        ),
        output_dir=tmp_path,
        acquisition_contract=gate,
    )

    assert exit_code == 1
    summary = json.loads(
        next(
            tmp_path.glob("ai-builder-api-battle-suite-*/suite-summary.json")
        ).read_text()
    )
    assert summary["sentinel_verdict"] == "fail"
    assert summary["suite_identity_failed_check_count"] == 6
    assert summary["release_identity_recheck_checks"] == (
        harness._release_identity_recheck_checks(
            expected=release_identity,
            actual=summary["release_identity_recheck"],
            require_verified_target=True,
        )
    )
    assert all(
        check["passed"] is False for check in summary["release_identity_recheck_checks"]
    )


@mark.parametrize(
    "scenario",
    [
        "success",
        "confirmation-drift",
        "scheduling-drift",
        "flow-isolation-drift",
        "target-collision",
        "completed-clean",
    ],
)
def test_replacement_batch_reuses_context_and_preflights_publication(
    scenario: str,
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)
    suite_dir = tmp_path / "release-suite"
    suite_dir.mkdir()
    output_dir = tmp_path / "replacement-output"
    cases = [
        harness.BattleCase(
            case_id="provider-a",
            prompt="Build A.",
            attachments=("01_protokoll_bun_2026_02_25.pdf",),
        ),
        harness.BattleCase(case_id="provider-b", prompt="Build B."),
        harness.BattleCase(case_id="completed-clean", prompt="Build clean."),
    ]
    release_identity = _release_identity_fixture(
        harness, case_id=cases[0].case_id, prompt=cases[0].prompt
    )
    release_identity["target"] = {
        "expected_source_revision": "a" * 40,
        "verified": True,
    }
    provider_slots = {
        ("provider-a", 4): SimpleNamespace(
            slot=("provider-a", 4),
            observation_status="error_terminated",
            provider_dispositions=("provider_outcome_unknown",),
            bundle_sha256="1" * 64,
            case_contract_sha256=harness._case_contract_sha256(cases[0]),
        ),
        ("provider-b", 2): SimpleNamespace(
            slot=("provider-b", 2),
            observation_status="execution_failure",
            provider_dispositions=(),
            bundle_sha256="2" * 64,
            case_contract_sha256=harness._case_contract_sha256(cases[1]),
        ),
        ("completed-clean", 1): SimpleNamespace(
            slot=("completed-clean", 1),
            observation_status="completed",
            provider_dispositions=(),
            bundle_sha256="3" * 64,
            case_contract_sha256=harness._case_contract_sha256(cases[2]),
        ),
    }
    observations = tuple(provider_slots.values()) + tuple(
        SimpleNamespace(
            slot=(f"clean-{index}", 1),
            observation_status="completed",
            provider_dispositions=(),
        )
        for index in range(37)
    )
    receipt = SimpleNamespace(
        observations=observations,
        artifact_schema_version=harness.SUPPORTED_RECEIPT_ARTIFACT_VERSION,
        repetitions=5,
        summary={
            "base_url": "http://localhost:8123/api/v1",
            "space_id": "space-1",
            "release_identity": release_identity,
            "run_context": {
                "ui_language": "sv",
                "auto_confirm_requirements": True,
                "confirm_message_sha256": hashlib.sha256(
                    harness.DEFAULT_CONFIRM_MESSAGE.encode()
                ).hexdigest(),
                "repetitions": 5,
                "max_concurrency": 2,
                "max_concurrent_observations_per_case": 1,
                "flow_isolation_semantics_version": 1,
            },
        },
    )
    monkeypatch.setattr(harness, "load_recoverable_release_receipt", lambda _: receipt)
    monkeypatch.setattr(harness, "_read_cases_file", lambda _: cases)
    monkeypatch.setattr(harness, "_release_run_identity", lambda **_: release_identity)
    monkeypatch.setattr(
        harness,
        "_release_identity_recheck_checks",
        lambda **_: [{"name": "identity", "passed": True}],
    )
    provisioned = {"fixture": {"file_id": "file-1"}}
    provisioned_cases: list[list[Any]] = []

    def provision(**kwargs: Any) -> dict[str, dict[str, str]]:
        provisioned_cases.append(kwargs["cases"])
        assert kwargs["cases"][0].attachments == ("01_protokoll_bun_2026_02_25.pdf",)
        return provisioned

    monkeypatch.setattr(harness, "_provision_fixtures", provision)
    acquired: list[tuple[str, int, object]] = []

    def acquire(**kwargs: Any) -> dict[str, Any]:
        case = kwargs["case"]
        repetition = kwargs["repetition"]
        staging_dir = kwargs["artifact_output_dir"]
        assert isinstance(case, harness.BattleCase)
        assert isinstance(staging_dir, Path)
        acquired.append((case.case_id, repetition, kwargs["provisioned_fixtures"]))
        bundle_path = staging_dir / f"{case.case_id}-r{repetition}.json"
        bundle_path.write_text(
            json.dumps({"case_id": case.case_id, "repetition": repetition})
        )
        digest = hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        return {
            "case_id": case.case_id,
            "repetition": repetition,
            "required": False,
            "artifact_mode": "live_execution",
            "observation_status": "completed",
            "outcome_class": "plan_first_pass",
            "expectation_verdict": "pass",
            "case_contract_sha256": harness._case_contract_sha256(case),
            "bundle_file": bundle_path.name,
            "bundle_sha256": digest,
            "failed_checks": [],
            "failure_summary": {"failure_codes": [], "error_details": []},
            "journey": {
                "outcome_class": "plan_first_pass",
                "architecture": {"chosen_patterns": ["document_to_structured_report"]},
                "plan_outcome": {
                    "repair_attempts": 0,
                    "attempt_failure_ladder": [],
                },
            },
            "authoring_usage": {
                "model_calls": 1,
                "total_tokens": 100,
                "elapsed_ms": 100,
            },
            "evidence_valid": True,
            "evidence_failed_check_count": 0,
            "identity_failed_check_count": 0,
            "identity_failed_checks": [],
        }

    monkeypatch.setattr(harness, "_acquire_suite_observation", acquire)
    args = SimpleNamespace(
        replacement_suite_dir=str(suite_dir),
        replacement_slot=(
            ["completed-clean:1"]
            if scenario == "completed-clean"
            else ["provider-a:4", "provider-b:2"]
        ),
        replacement_reason="failed observation in original receipt",
        output_dir=str(output_dir),
        cases_file=None,
        confirm_message=(
            "Different confirmation"
            if scenario == "confirmation-drift"
            else harness.DEFAULT_CONFIRM_MESSAGE
        ),
        timeout_seconds=1,
    )
    collision_path = suite_dir / "replacement-provider-b-r2.json"
    if scenario == "scheduling-drift":
        receipt.summary["run_context"]["max_concurrent_observations_per_case"] = 2
    if scenario == "flow-isolation-drift":
        receipt.summary["run_context"]["flow_isolation_semantics_version"] = 0
    if scenario == "target-collision":
        collision_path.write_text("occupied", encoding="utf-8")

    if scenario != "success":
        match = (
            "confirm-message does not match"
            if scenario == "confirmation-drift"
            else (
                "does not serialize concurrent repetitions"
                if scenario == "scheduling-drift"
                else (
                    "does not own applied benchmark Flow cleanup"
                    if scenario == "flow-isolation-drift"
                    else (
                        "may not be re-measured"
                        if scenario == "completed-clean"
                        else "target already exists"
                    )
                )
            )
        )
        with raises(ValueError, match=match):
            harness._run_replacement_batch(
                args=args,
                api_key="test-key",
                output_dir=output_dir,
            )

        assert not (suite_dir / "replacements.json").exists()
        assert not (suite_dir / "replacement-provider-a-r4.json").exists()
        if scenario in {
            "confirmation-drift",
            "scheduling-drift",
            "flow-isolation-drift",
            "completed-clean",
        }:
            assert provisioned_cases == []
            assert acquired == []
        else:
            assert collision_path.read_text(encoding="utf-8") == "occupied"
        return

    exit_code = harness._run_replacement_batch(
        args=args,
        api_key="test-key",
        output_dir=output_dir,
    )

    assert exit_code == 0
    assert len(provisioned_cases) == 1
    assert acquired == [
        ("provider-a", 4, provisioned),
        ("provider-b", 2, provisioned),
    ]
    descriptors = json.loads((suite_dir / "replacements.json").read_text())
    assert [(item["case_id"], item["repetition"]) for item in descriptors] == [
        ("provider-a", 4),
        ("provider-b", 2),
    ]
    for descriptor in descriptors:
        replacement_files = [
            path
            for path in suite_dir.glob("replacement-*.json")
            if hashlib.sha256(path.read_bytes()).hexdigest()
            == descriptor["replacement_bundle_sha256"]
        ]
        assert len(replacement_files) == 1


def test_required_identity_drift_does_not_become_builder_expectation_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)
    case = harness.BattleCase(
        case_id="required-identity-drift",
        prompt="Build the required identity case.",
        required=True,
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    monkeypatch.setattr(
        harness,
        "_release_run_identity",
        lambda **_: release_identity,
    )

    def successful_case(**_: object) -> dict[str, object]:
        return _complete_live_case_bundle(
            harness,
            case,
            requested_model_id="model-b",
        )

    monkeypatch.setattr(harness, "_run_case", successful_case)
    acquisition_contract = harness.AcquisitionContract(
        required_case_ids=(case.case_id,),
    )

    exit_code = harness._run_suite(
        cases=[case],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=type(
            "Args",
            (),
            {"repetitions": 1, "space_id": "space-1", "model_id": "model-a"},
        )(),
        output_dir=tmp_path,
        acquisition_contract=acquisition_contract,
    )

    assert exit_code == 1
    summary_path = next(
        tmp_path.glob("ai-builder-api-battle-suite-*/suite-summary.json")
    )
    summary = json.loads(summary_path.read_text())
    result = summary["results"][0]
    assert result["expectation_verdict"] == "pass"
    assert result["failed_expectation_check_count"] == 0
    assert result["identity_failed_check_count"] == 1
    assert summary["expectation_failed_observation_count"] == 0
    assert summary["identity_failed_check_count"] == 1
    assert summary["sentinel_verdict"] == "fail"
    assert "case identity checks failed: suite_requested_model_identity" in (
        capsys.readouterr().err
    )


def test_release_run_rejects_dirty_source_before_creating_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    gate = harness.AcquisitionContract(
        required_case_ids=("required-positive",),
        require_clean_source=True,
    )

    monkeypatch.setattr(
        harness,
        "_git_output",
        lambda *args: " M backend/scripts/ai_builder_api_battle_test.py"
        if args == ("status", "--porcelain", "--untracked-files=no")
        else "23fab2d4a638ef1411a4d5808981aa77cb17f59d",
    )

    with raises(ValueError, match="clean tracked source"):
        harness._run_suite(
            cases=[
                harness.BattleCase(
                    case_id="required-positive",
                    prompt="Build the required positive case.",
                    required=True,
                )
            ],
            config=harness.ApiConfig(
                base_url="http://localhost:8123/api/v1",
                api_key="test-key",
                timeout_seconds=1,
            ),
            args=type(
                "Args",
                (),
                {
                    "repetitions": 1,
                    "space_id": "space-1",
                    "model_id": "model-1",
                },
            )(),
            output_dir=tmp_path,
            acquisition_contract=gate,
        )

    assert list(tmp_path.iterdir()) == []


def test_release_identity_rejects_untracked_case_input(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    case = harness.BattleCase(case_id="required-input", prompt="Build it.")

    def git_output(*args: str) -> str:
        if args and args[0] == "ls-files":
            raise subprocess.CalledProcessError(1, ["git", *args])
        if args == ("status", "--porcelain", "--untracked-files=no"):
            return ""
        return "a" * 40

    monkeypatch.setattr(harness, "_git_output", git_output)

    with raises(ValueError, match="tracked repository input"):
        harness._release_run_identity(
            cases=[case],
            cases_path=harness.DEFAULT_CASES_FILE,
            requested_model_id="model-a",
            require_clean_source=True,
        )


def test_live_provenance_captures_source_build_model_prompt_and_usage(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    monkeypatch.setattr(
        harness,
        "_git_output",
        lambda *args: ""
        if args == ("status", "--porcelain", "--untracked-files=no")
        else "23fab2d4a638ef1411a4d5808981aa77cb17f59d",
    )
    case = harness.BattleCase(
        case_id="provenance-case",
        prompt="Build a source-faithful report.",
        required=True,
    )
    latest_session = {
        "telemetry": {
            "prompt_tokens_total": 101,
            "completion_tokens_total": 17,
            "total_tokens_total": 118,
            "llm_calls_made_total": 3,
            "last_model": "openai/gpt-test",
        }
    }
    classifier_diagnostics = _classifier_diagnostics()
    cases_path = tmp_path / "selected-cases.json"
    cases_path.write_text('{"version":4,"cases":[]}', encoding="utf-8")

    provenance = harness._live_execution_provenance(
        case=case,
        cases_path=cases_path,
        latest_session=latest_session,
        classifier_diagnostics=classifier_diagnostics,
        requested_model_id="model-a",
        session_models={
            "models": [{"id": "model-a", "name": "gpt-test", "provider": "openai"}],
            "default_model_id": "model-a",
        },
    )

    assert provenance["mode"] == "live_execution"
    assert provenance["source"]["revision"]
    assert len(provenance["source"]["revision_sha256"]) == 64
    assert provenance["build"]["app_version"] == harness.LOCAL_APP_VERSION
    assert (
        provenance["build"]["cases_sha256"]
        == hashlib.sha256(cases_path.read_bytes()).hexdigest()
    )
    assert provenance["build"]["sha256"] == harness._canonical_sha256(
        {
            "source_revision": provenance["build"]["source_revision"],
            "harness_sha256": provenance["build"]["harness_sha256"],
            "cases_sha256": provenance["build"]["cases_sha256"],
        }
    )
    assert provenance["model"]["observed_ids"] == ["openai/gpt-test"]
    assert len(provenance["model"]["sha256"]) == 64
    assert (
        provenance["prompt"]["case_sha256"]
        == hashlib.sha256(case.prompt.encode("utf-8")).hexdigest()
    )
    assert provenance["prompt"]["classifier_hashes"] == ["a" * 64]
    assert provenance["usage"] == {
        "prompt_tokens": 101,
        "completion_tokens": 17,
        "total_tokens": 118,
        "model_calls": 3,
        "repair_attempts": None,
        "parse_repair_attempts": None,
        "elapsed_ms": None,
        "raw_reads": {
            "classifier_run_count": 1,
            "source_inventory_entry_count": 2,
            "uploaded_file_raw_read_count": 1,
            "distinct_uploaded_file_count": 1,
            "uploaded_file_reread_count": 0,
            "truncated_source_count": 0,
            "uploaded_file_coverage_counts": {"fully_seen": 1},
        },
    }
    assert all(
        check["passed"] is True for check in harness._live_provenance_checks(provenance)
    )

    mixed_model_provenance = harness._live_execution_provenance(
        case=case,
        cases_path=cases_path,
        latest_session=latest_session,
        classifier_diagnostics=classifier_diagnostics,
        requested_model_id="model-a",
        session_models={
            "models": [{"id": "model-a", "name": "gpt-test", "provider": "openai"}],
            "default_model_id": "model-a",
        },
        interactions=[
            {
                "events": [
                    {
                        "event": "usage",
                        "data": {"last_model": "openai/gpt-test"},
                    }
                ]
            },
            {
                "events": [
                    {
                        "event": "usage",
                        "data": {"last_model": "openai/gpt-other"},
                    }
                ]
            },
        ],
    )
    assert mixed_model_provenance["model"]["planner_observed_ids"] == [
        "openai/gpt-test",
        "openai/gpt-other",
    ]
    assert mixed_model_provenance["model"]["observed_matches_resolved"] is False

    missing_interaction_model = harness._live_execution_provenance(
        case=case,
        cases_path=cases_path,
        latest_session=latest_session,
        classifier_diagnostics=classifier_diagnostics,
        requested_model_id="model-a",
        session_models={
            "models": [{"id": "model-a", "name": "gpt-test", "provider": "openai"}],
            "default_model_id": "model-a",
        },
        interactions=[
            {
                "events": [
                    {
                        "event": "usage",
                        "data": {"last_model": "openai/gpt-test"},
                    }
                ]
            },
            # A planner-less interaction (server-resolved turn) is
            # identity-neutral under the auto-resolution semantics.
            {"events": []},
            # Ambiguous usage stays a hard identity failure.
            {
                "events": [
                    {"event": "usage", "data": {"last_model": "openai/gpt-test"}},
                    {"event": "usage", "data": {"last_model": "openai/other"}},
                ]
            },
        ],
    )
    assert missing_interaction_model["model"]["planner_interaction_count"] == 3
    assert missing_interaction_model["model"]["planner_observations"] == [
        {"interaction_index": 1, "model_id": "openai/gpt-test"}
    ]
    assert missing_interaction_model["model"][
        "missing_planner_interaction_indices"
    ] == [3]
    assert missing_interaction_model["model"]["observed_matches_resolved"] is False

    missing_model = {**provenance, "model": {"observed_ids": [], "sha256": "0" * 64}}
    assert (
        next(
            check
            for check in harness._live_provenance_checks(missing_model)
            if check["name"] == "live_model_provenance_complete"
        )["passed"]
        is False
    )


def test_release_identity_binds_target_version_and_observed_model(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    expected_revision = "a" * 40
    from eneo.main import config as app_config

    missing_manifest = tmp_path / "missing-release-manifest.json"
    monkeypatch.setattr(app_config, "_DOCKER_MANIFEST", missing_manifest)
    monkeypatch.setattr(app_config, "_LOCAL_MANIFEST", missing_manifest)
    monkeypatch.setenv("GIT_COMMIT", expected_revision)
    monkeypatch.delenv("BUILD_ID", raising=False)
    expected_app_version = app_config._set_app_version()
    served_version = expected_app_version

    class VersionResponse:
        def __enter__(self) -> VersionResponse:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"version": served_version}).encode()

    requested_urls: list[str] = []

    def open_version(request: object, **_kwargs: object) -> VersionResponse:
        requested_urls.append(str(getattr(request, "full_url")))
        return VersionResponse()

    monkeypatch.setattr(harness, "urlopen", open_version)
    target = harness._target_runtime_identity(
        harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        expected_source_revision=expected_revision,
    )

    assert requested_urls == ["http://localhost:8123/version"]
    assert target["verified"] is True
    assert target["version"] == expected_app_version
    assert target["expected_app_version"] == expected_app_version
    assert target["expected_source_revision"] == expected_revision
    assert target["source_revision_verification"] == "git_commit_prefix_via_app_version"
    assert len(target["sha256"]) == 64
    drifted_target = {
        **target,
        "version": "release-other",
        "sha256": "0" * 64,
    }
    target_checks = {
        check["name"]: check
        for check in harness._release_identity_recheck_checks(
            expected={"target": target},
            actual={"target": drifted_target},
            require_verified_target=True,
        )
    }
    assert target_checks["suite_target_identity_unchanged"]["passed"] is False

    served_version = "release-other"
    monkeypatch.setattr(
        harness,
        "_git_output",
        lambda *args: ""
        if args == ("status", "--porcelain", "--untracked-files=no")
        else expected_revision,
    )
    monkeypatch.setattr(
        harness, "_release_input_sha256", lambda *_args, **_kwargs: "c" * 64
    )
    with raises(ValueError, match="does not match the local source revision"):
        harness._release_run_identity(
            cases=[harness.BattleCase(case_id="target-mismatch", prompt="Build it.")],
            cases_path=harness.DEFAULT_CASES_FILE,
            requested_model_id="model-a",
            require_clean_source=False,
            config=harness.ApiConfig(
                base_url="http://localhost:8123/api/v1",
                api_key="test-key",
                timeout_seconds=1,
            ),
        )

    bare_model = harness._resolved_model_identity(
        session_models={
            "models": [{"id": "model-a", "name": "gpt-a", "provider": "openai"}],
            "default_model_id": "model-a",
        },
        requested_model_id="model-a",
        planner_observed_model_ids=["gpt-a"],
        classifier_observed_model_ids=[],
    )
    assert bare_model["expected_observed_ids"] == ["openai/gpt-a"]
    assert bare_model["observed_matches_resolved"] is False

    case = harness.BattleCase(
        case_id="model-evidence",
        prompt="Build it.",
        required=True,
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )
    wrong_observed_model = _live_provenance_fixture(
        harness,
        prompt=case.prompt,
    )
    wrong_observed_model["model"] = {
        "requested_id": "model-a",
        "resolved_id": "model-a",
        "resolved_name": "gpt-a",
        "resolved_provider": "openai",
        "expected_observed_ids": ["openai/gpt-a"],
        "observed_ids": ["openai/gpt-b"],
        "observed_matches_resolved": False,
    }
    checks = {
        check["name"]: check
        for check in harness._required_case_identity_checks(
            case=case,
            release_identity=release_identity,
            provenance=wrong_observed_model,
            observation_input_identity={
                "verified": True,
                "sha256": "d" * 64,
            },
        )
    }
    assert checks["suite_requested_model_identity"]["passed"] is False


def test_observation_input_identity_distinguishes_fixture_bytes_from_runtime_content() -> (
    None
):
    harness = _battle_harness()
    runtime_fixture = "05_lokalkalkyl.csv"
    runtime_fixture_sha256 = harness._fixture_manifest()[runtime_fixture]
    runtime_source_sha256 = "b" * 64
    extracted_evidence_sha256 = "a" * 64
    attachment_file_id = "00000000-0000-0000-0000-000000000002"
    case = harness.BattleCase(
        case_id="fixture-identity",
        prompt="Build it.",
        attachments=("generic_case_template.docx",),
        runtime_files=(runtime_fixture,),
    )
    diagnostics = _classifier_diagnostics()
    classifier_runs = diagnostics["classifier_runs"]
    assert isinstance(classifier_runs, list)
    classifier_run = classifier_runs[0]
    assert isinstance(classifier_run, dict)
    source_inventory = classifier_run["source_inventory"]
    assert isinstance(source_inventory, list)
    uploaded_source = source_inventory[1]
    assert isinstance(uploaded_source, dict)
    uploaded_source["file_id"] = attachment_file_id
    uploaded_source["source_sha256"] = extracted_evidence_sha256
    file_roles = classifier_run["file_roles"]
    assert isinstance(file_roles, list)
    file_role = file_roles[0]
    assert isinstance(file_role, dict)
    file_role["file_id"] = attachment_file_id
    attachment_fixture = "generic_case_template.docx"
    attachment_fixture_sha256 = harness._fixture_manifest()[attachment_fixture]
    provisioned_fixtures = {
        attachment_fixture: {
            "file_id": attachment_file_id,
            "content_sha256": attachment_fixture_sha256,
            "path": f"scripts/fixtures/ai_builder_battle/{attachment_fixture}",
        }
    }
    runtime_evidence = {
        "run_contract": {
            "steps_requiring_input": [{"step_id": "reader-step"}],
        },
        "uploaded_files": [{"id": "runtime-file-1", "size": 358}],
        "step_results": [
            {
                "step_id": "reader-step",
                "status": "completed",
                "current_attempt_no": 1,
                "runtime_input_file_ids": ["runtime-file-1"],
            }
        ],
        "step_attempts": [
            {
                "id": "attempt-1",
                "step_id": "reader-step",
                "attempt_no": 1,
                "status": "completed",
                "superseded_by_attempt_id": None,
                "resolved_input_lineage": {
                    "status": "tracked",
                    "schema_version": 1,
                    "edges": [
                        {
                            "source": {
                                "kind": "runtime_file",
                                "input_file_ordinal": 0,
                                "file_id": "runtime-file-1",
                                "checksum": runtime_source_sha256,
                                "byte_size": 358,
                            },
                            "selection": {"encoding": "bound_file"},
                        }
                    ],
                },
            }
        ],
    }

    identity = harness._observation_input_identity(
        case=case,
        session_id=_TEST_SESSION_ID,
        attached_file_ids=(attachment_file_id,),
        classifier_diagnostics=diagnostics,
        runtime_evidence=runtime_evidence,
        provisioned_fixtures=provisioned_fixtures,
    )
    assert identity["verified"] is True
    assert identity["runtime_fixture_sha256s"] == [runtime_fixture_sha256]
    assert identity["runtime_source_sha256s"] == [runtime_source_sha256]
    assert "declared_runtime_sha256s" not in identity
    assert len(identity["sha256"]) == 64

    # Runtime lineage identifies the extracted content the step consumed. A
    # different valid digest is observed product behaviour, not evidence that
    # the git-pinned upload bytes changed, and it must move the fingerprint.
    runtime_edge = runtime_evidence["step_attempts"][0]["resolved_input_lineage"][
        "edges"
    ][0]
    runtime_edge["source"]["checksum"] = "c" * 64
    changed_projection = harness._observation_input_identity(
        case=case,
        session_id=_TEST_SESSION_ID,
        attached_file_ids=(attachment_file_id,),
        classifier_diagnostics=diagnostics,
        runtime_evidence=runtime_evidence,
        provisioned_fixtures=provisioned_fixtures,
    )
    assert changed_projection["verified"] is True
    assert changed_projection["sha256"] != identity["sha256"]
    runtime_edge["source"]["checksum"] = runtime_source_sha256

    # The upload response and resolved-input lineage describe the same selected
    # content variant, so disagreement between their sizes is invalid evidence.
    runtime_edge["source"]["byte_size"] = 359
    mismatched_size = harness._observation_input_identity(
        case=case,
        session_id=_TEST_SESSION_ID,
        attached_file_ids=(attachment_file_id,),
        classifier_diagnostics=diagnostics,
        runtime_evidence=runtime_evidence,
        provisioned_fixtures=provisioned_fixtures,
    )
    assert mismatched_size["verified"] is False
    assert mismatched_size["mismatches"] == ["runtime_evidence"]
    runtime_edge["source"]["byte_size"] = 358

    # An attachment that produced no well-formed extraction digest is an
    # unevaluable observation; which digest it produced is reported, never
    # pinned to a constant captured months ago.
    uploaded_source["source_sha256"] = "nope"
    missing_evidence = harness._observation_input_identity(
        case=case,
        session_id=_TEST_SESSION_ID,
        attached_file_ids=(attachment_file_id,),
        classifier_diagnostics=diagnostics,
        runtime_evidence=runtime_evidence,
        provisioned_fixtures=provisioned_fixtures,
    )
    assert missing_evidence["verified"] is False
    assert missing_evidence["mismatches"] == ["attachment_evidence"]

    uploaded_source["source_sha256"] = extracted_evidence_sha256
    stale_attempt = runtime_evidence["step_attempts"][0]
    stale_attempt["superseded_by_attempt_id"] = "attempt-2"
    runtime_evidence["step_attempts"].append(
        {
            "id": "attempt-2",
            "step_id": "reader-step",
            "attempt_no": 2,
            "status": "completed",
            "superseded_by_attempt_id": None,
            "resolved_input_lineage": {"status": "not_tracked"},
        }
    )
    runtime_evidence["step_results"][0]["current_attempt_no"] = 2
    untracked = harness._observation_input_identity(
        case=case,
        session_id=_TEST_SESSION_ID,
        attached_file_ids=(attachment_file_id,),
        classifier_diagnostics=diagnostics,
        runtime_evidence=runtime_evidence,
        provisioned_fixtures=provisioned_fixtures,
    )
    assert untracked["verified"] is False
    assert untracked["mismatches"] == ["runtime_evidence"]


def test_complex_first_pass_provenance_rejects_each_missing_or_amplified_fact(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    monkeypatch.setattr(
        harness,
        "_git_output",
        lambda *args: ""
        if args == ("status", "--porcelain", "--untracked-files=no")
        else "23fab2d4a638ef1411a4d5808981aa77cb17f59d",
    )
    cases_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_battle_cases.json"
    )
    case = next(
        case
        for case in harness._read_cases_file(cases_path)
        if case.case_id == "complex_authoring_spec_first_pass"
    )
    latest_session = {
        "telemetry": {
            "prompt_tokens_total": 101,
            "completion_tokens_total": 17,
            "total_tokens_total": 118,
            "llm_calls_made_total": 1,
            "repair_attempts_total": 0,
            "parse_repair_attempts_total": 0,
            "wall_clock_ms_total": 321,
            "token_usage_estimated": False,
            "last_token_usage_source": "provider",
            "last_token_usage_estimated": False,
            "last_model": "openai/gpt-test",
        }
    }
    provenance = harness._live_execution_provenance(
        case=case,
        latest_session=latest_session,
        classifier_diagnostics=_classifier_diagnostics(),
        requested_model_id=None,
        event_summary={"event_counts": {"error": 0}, "error_codes": []},
    )

    def checks_for(value: dict[str, object]) -> dict[str, dict[str, object]]:
        assert case.expected is not None
        return {
            check["name"]: check
            for check in harness._live_provenance_checks(
                value,
                expected=case.expected,
            )
        }

    def refresh_progress_fingerprint(value: dict[str, object]) -> None:
        progress = value["proposal_progress"]
        assert isinstance(progress, dict)
        payload_keys = (
            "source",
            "call_count",
            "repair_attempts",
            "parse_repair_attempts",
            "attempts",
            "provider_failure_status",
            "public_error_code_count",
        )
        progress["fingerprint"] = harness._canonical_sha256(
            {key: progress.get(key) for key in payload_keys}
        )

    baseline = checks_for(provenance)
    first_pass_names = {name for name in baseline if name.startswith("first_pass_")}
    assert first_pass_names == {
        "first_pass_classifier_request_composite_fingerprint",
        "first_pass_progress_fingerprint",
        "first_pass_proposal_call_count",
        "first_pass_zero_repairs",
        "first_pass_attempt_evidence",
        "first_pass_provider_failure_provenance",
    }
    assert all(baseline[name]["passed"] is True for name in first_pass_names)

    missing_capability = json.loads(json.dumps(provenance))
    missing_capability["capability"]["classifier_request_composite_fingerprint"] = None
    assert (
        checks_for(missing_capability)[
            "first_pass_classifier_request_composite_fingerprint"
        ]["passed"]
        is False
    )

    changed_diagnostics = _classifier_diagnostics()
    changed_runs = changed_diagnostics["classifier_runs"]
    assert isinstance(changed_runs, list)
    assert isinstance(changed_runs[0], dict)
    changed_runs[0]["prompt_hash"] = "d" * 64
    changed_capability = harness._live_execution_provenance(
        case=case,
        latest_session=latest_session,
        classifier_diagnostics=changed_diagnostics,
        requested_model_id=None,
        event_summary={"event_counts": {"error": 0}, "error_codes": []},
    )
    assert (
        provenance["capability"]["classifier_request_composite_fingerprint"]
        != changed_capability["capability"]["classifier_request_composite_fingerprint"]
    )

    for invalid_diagnostics in (
        {"classifier_runs": []},
        {"classifier_runs": [{"prompt_hash": "not-a-sha256"}]},
    ):
        invalid_capability = harness._live_execution_provenance(
            case=case,
            latest_session=latest_session,
            classifier_diagnostics=invalid_diagnostics,
            requested_model_id=None,
            event_summary={"event_counts": {"error": 0}, "error_codes": []},
        )
        assert (
            invalid_capability["capability"]["classifier_request_composite_fingerprint"]
            is None
        )
        assert (
            checks_for(invalid_capability)[
                "first_pass_classifier_request_composite_fingerprint"
            ]["passed"]
            is False
        )

    missing_progress = json.loads(json.dumps(provenance))
    missing_progress["proposal_progress"]["fingerprint"] = None
    assert (
        checks_for(missing_progress)["first_pass_progress_fingerprint"]["passed"]
        is False
    )

    extra_call = json.loads(json.dumps(provenance))
    extra_call["proposal_progress"]["call_count"] = 2
    refresh_progress_fingerprint(extra_call)
    assert checks_for(extra_call)["first_pass_proposal_call_count"]["passed"] is False

    repair = json.loads(json.dumps(provenance))
    repair["proposal_progress"]["repair_attempts"] = 1
    refresh_progress_fingerprint(repair)
    assert checks_for(repair)["first_pass_zero_repairs"]["passed"] is False

    missing_attempt = json.loads(json.dumps(provenance))
    missing_attempt["proposal_progress"]["attempts"] = []
    refresh_progress_fingerprint(missing_attempt)
    assert checks_for(missing_attempt)["first_pass_attempt_evidence"]["passed"] is False

    missing_failure = json.loads(json.dumps(provenance))
    missing_failure["proposal_progress"].pop("provider_failure_status")
    refresh_progress_fingerprint(missing_failure)
    assert (
        checks_for(missing_failure)["first_pass_provider_failure_provenance"]["passed"]
        is False
    )

    unclassified_failure = json.loads(json.dumps(provenance))
    unclassified_failure["proposal_progress"]["provider_failure_status"] = (
        "unclassified"
    )
    refresh_progress_fingerprint(unclassified_failure)
    assert (
        checks_for(unclassified_failure)["first_pass_provider_failure_provenance"][
            "passed"
        ]
        is False
    )


def test_complex_first_pass_provenance_fails_closed_without_attempt_or_error_facts(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    monkeypatch.setattr(
        harness,
        "_git_output",
        lambda *args: ""
        if args == ("status", "--porcelain", "--untracked-files=no")
        else "23fab2d4a638ef1411a4d5808981aa77cb17f59d",
    )
    case = next(
        case
        for case in harness._read_cases_file(harness.DEFAULT_CASES_FILE)
        if case.case_id == "complex_authoring_spec_first_pass"
    )
    provenance = harness._live_execution_provenance(
        case=case,
        latest_session={
            "telemetry": {
                "llm_calls_made_total": 1,
                "last_token_usage_source": "provider",
                "last_token_usage_estimated": False,
                "last_model": "openai/gpt-test",
            }
        },
        classifier_diagnostics=_classifier_diagnostics(),
        requested_model_id=None,
        event_summary={"event_counts": {"error": 1}, "error_codes": []},
    )
    assert case.expected is not None
    checks = {
        check["name"]: check
        for check in harness._live_provenance_checks(
            provenance,
            expected=case.expected,
        )
    }

    assert checks["first_pass_zero_repairs"]["passed"] is False
    assert checks["first_pass_attempt_evidence"]["passed"] is False
    assert checks["first_pass_provider_failure_provenance"]["passed"] is False
    assert provenance["proposal_progress"]["provider_failure_status"] == (
        "unclassified"
    )
    assert provenance["proposal_progress"]["attempts"] == []

    complete_telemetry = {
        "prompt_tokens_total": 101,
        "completion_tokens_total": 17,
        "total_tokens_total": 118,
        "llm_calls_made_total": 1,
        "repair_attempts_total": 0,
        "parse_repair_attempts_total": 0,
        "wall_clock_ms_total": 321,
        "last_token_usage_source": "provider",
        "last_token_usage_estimated": False,
        "last_model": "openai/gpt-test",
    }
    missing_event_summary = harness._live_execution_provenance(
        case=case,
        latest_session={"telemetry": complete_telemetry},
        classifier_diagnostics=_classifier_diagnostics(),
        requested_model_id=None,
    )
    missing_event_checks = {
        check["name"]: check
        for check in harness._live_provenance_checks(
            missing_event_summary,
            expected=case.expected,
        )
    }
    assert (
        missing_event_checks["first_pass_provider_failure_provenance"]["passed"]
        is False
    )

    for incomplete_summary in (
        {"event_counts": {}, "error_codes": []},
        {"event_counts": {"error": "zero"}, "error_codes": []},
        {"event_counts": {"error": 0}},
        {"event_counts": {"error": 0}, "error_codes": "none"},
    ):
        incomplete_failure = harness._live_execution_provenance(
            case=case,
            latest_session={"telemetry": complete_telemetry},
            classifier_diagnostics=_classifier_diagnostics(),
            requested_model_id=None,
            event_summary=incomplete_summary,
        )
        incomplete_failure_checks = {
            check["name"]: check
            for check in harness._live_provenance_checks(
                incomplete_failure,
                expected=case.expected,
            )
        }
        assert (
            incomplete_failure["proposal_progress"]["provider_failure_status"]
            == "unclassified"
        )
        assert (
            incomplete_failure_checks["first_pass_provider_failure_provenance"][
                "passed"
            ]
            is False
        )

    unknown_outcome = harness._live_execution_provenance(
        case=case,
        latest_session={"telemetry": complete_telemetry},
        classifier_diagnostics=_classifier_diagnostics(),
        requested_model_id=None,
        event_summary={
            "event_counts": {"error": 1},
            "error_codes": ["session_turn_provider_outcome_unknown"],
        },
    )
    assert unknown_outcome["proposal_progress"]["provider_failure_status"] == (
        "outcome_unknown"
    )

    classified_error = harness._live_execution_provenance(
        case=case,
        latest_session={"telemetry": complete_telemetry},
        classifier_diagnostics=_classifier_diagnostics(),
        requested_model_id=None,
        event_summary={
            "event_counts": {"error": 1},
            "error_codes": ["self_correction_invalid_plan"],
        },
    )
    assert classified_error["proposal_progress"]["provider_failure_status"] == (
        "classified_public_error"
    )

    estimated_usage = harness._live_execution_provenance(
        case=case,
        latest_session={
            "telemetry": {
                **complete_telemetry,
                "last_token_usage_source": "litellm_estimate",
                "last_token_usage_estimated": True,
            }
        },
        classifier_diagnostics=_classifier_diagnostics(),
        requested_model_id=None,
        event_summary={"event_counts": {"error": 0}, "error_codes": []},
    )
    estimated_checks = {
        check["name"]: check
        for check in harness._live_provenance_checks(
            estimated_usage,
            expected=case.expected,
        )
    }
    assert estimated_checks["first_pass_attempt_evidence"]["passed"] is True

    for missing_or_incoherent, failing_checks in (
        (
            {"repair_attempts_total": None},
            ("first_pass_zero_repairs", "first_pass_attempt_evidence"),
        ),
        (
            {"parse_repair_attempts_total": None},
            ("first_pass_zero_repairs", "first_pass_attempt_evidence"),
        ),
        ({"prompt_tokens_total": None}, ("first_pass_attempt_evidence",)),
        ({"total_tokens_total": 119}, ("first_pass_attempt_evidence",)),
        ({"wall_clock_ms_total": 0}, ("first_pass_attempt_evidence",)),
        (
            {
                "last_token_usage_source": "provider",
                "last_token_usage_estimated": True,
            },
            ("first_pass_attempt_evidence",),
        ),
        (
            {
                "last_token_usage_source": "litellm_estimate",
                "last_token_usage_estimated": False,
            },
            ("first_pass_attempt_evidence",),
        ),
        (
            {"last_token_usage_source": "none"},
            ("first_pass_attempt_evidence",),
        ),
        (
            {"last_token_usage_source": "unknown"},
            ("first_pass_attempt_evidence",),
        ),
        ({"last_token_usage_source": 7}, ("first_pass_attempt_evidence",)),
        ({"last_token_usage_source": None}, ("first_pass_attempt_evidence",)),
        ({"last_token_usage_estimated": "false"}, ("first_pass_attempt_evidence",)),
        ({"last_token_usage_estimated": None}, ("first_pass_attempt_evidence",)),
    ):
        telemetry = {**complete_telemetry, **missing_or_incoherent}
        incomplete_attempt = harness._live_execution_provenance(
            case=case,
            latest_session={"telemetry": telemetry},
            classifier_diagnostics=_classifier_diagnostics(),
            requested_model_id=None,
            event_summary={"event_counts": {"error": 0}, "error_codes": []},
        )
        incomplete_checks = {
            check["name"]: check
            for check in harness._live_provenance_checks(
                incomplete_attempt,
                expected=case.expected,
            )
        }
        assert incomplete_attempt["proposal_progress"]["attempts"] == []
        assert all(
            incomplete_checks[name]["passed"] is False for name in failing_checks
        )


def test_required_case_identity_rejects_each_manifest_drift() -> None:
    harness = _battle_harness()
    case = harness.BattleCase(
        case_id="required-identity",
        prompt="Build the required identity case.",
        required=True,
    )
    release_identity = _release_identity_fixture(
        harness,
        case_id=case.case_id,
        prompt=case.prompt,
    )

    def checks_for(provenance: dict[str, object]) -> dict[str, dict[str, object]]:
        return {
            check["name"]: check
            for check in harness._required_case_identity_checks(
                case=case,
                release_identity=release_identity,
                provenance=provenance,
                observation_input_identity=_empty_observation_input_identity(harness),
            )
        }

    baseline = checks_for(_live_provenance_fixture(harness, prompt=case.prompt))
    assert all(check["passed"] is True for check in baseline.values())

    dirty_source_provenance = _live_provenance_fixture(harness, prompt=case.prompt)
    source = dirty_source_provenance["source"]
    assert isinstance(source, dict)
    source["tracked_clean"] = False
    dirty_source = checks_for(dirty_source_provenance)
    assert dirty_source["suite_source_revision_identity"]["passed"] is False

    source_drift = checks_for(
        _live_provenance_fixture(
            harness,
            prompt=case.prompt,
            revision="d" * 40,
        )
    )
    assert source_drift["suite_source_revision_identity"]["passed"] is False

    harness_drift = checks_for(
        _live_provenance_fixture(
            harness,
            prompt=case.prompt,
            harness_sha256="e" * 64,
        )
    )
    assert harness_drift["suite_build_input_identity"]["passed"] is False

    cases_drift = checks_for(
        _live_provenance_fixture(
            harness,
            prompt=case.prompt,
            cases_sha256="f" * 64,
        )
    )
    assert cases_drift["suite_build_input_identity"]["passed"] is False

    model_drift = checks_for(
        _live_provenance_fixture(
            harness,
            prompt=case.prompt,
            requested_model_id="model-b",
        )
    )
    assert model_drift["suite_requested_model_identity"]["passed"] is False

    prompt_drift = checks_for(
        _live_provenance_fixture(harness, prompt="Build a different case.")
    )
    assert prompt_drift["suite_case_prompt_identity"]["passed"] is False


def test_review_policy_gate_rejects_wrong_or_unowned_checkpoint_shape() -> None:
    harness = _battle_harness()
    expected = {
        "expected_review_policy": {
            "mode": "view",
            "target_output_type": "json",
            "target_field_groups": [["supplier"], ["score"]],
            "target_must_be_non_terminal": True,
        }
    }

    def checks_for(
        plan: dict[str, object],
        applied_flow: dict[str, object] | None = None,
    ) -> dict[str, dict[str, object]]:
        report = harness._quality_report(
            plan=plan,
            summary=harness._summarize_plan(plan),
            expected=expected,
            event_summary={},
            applied_flow=applied_flow or _applied_flow_from_plan(plan),
        )
        return {check["name"]: check for check in report["checks"]}

    baseline_plan = _review_policy_plan()
    baseline = checks_for(baseline_plan)
    for name in (
        "proposed_review_policy_count",
        "proposed_review_policy_mode",
        "proposed_review_policy_target",
        "proposed_review_policy_topology",
        "proposed_review_policy_not_terminal_or_delivery",
        "applied_review_policy_count",
        "applied_review_policy_mode",
        "applied_review_policy_target",
        "applied_review_policy_topology",
        "applied_review_policy_not_terminal_or_delivery",
    ):
        assert baseline[name]["passed"] is True

    proposed_only_report = harness._quality_report(
        plan=baseline_plan,
        summary=harness._summarize_plan(baseline_plan),
        expected=expected,
        event_summary={},
        applied_flow=None,
    )
    proposed_only_names = {check["name"] for check in proposed_only_report["checks"]}
    assert "proposed_review_policy_count" in proposed_only_names
    assert not any(
        name.startswith("applied_review_policy_") for name in proposed_only_names
    )

    wrong_mode = _review_policy_plan(mode="edit")
    assert checks_for(wrong_mode)["proposed_review_policy_mode"]["passed"] is False

    missing = _review_policy_plan()
    _review_plan_steps(missing)[0]["review_policy"] = None
    assert checks_for(missing)["proposed_review_policy_count"]["passed"] is False

    duplicate = _review_policy_plan()
    _review_plan_steps(duplicate)[1]["review_policy"] = {"mode": "view"}
    assert checks_for(duplicate)["proposed_review_policy_count"]["passed"] is False

    swedish_bypass = _review_policy_plan()
    _insert_review_plan_step(
        swedish_bypass,
        1,
        {
            "plan_step_ref": "matrix_check",
            "name": "Kontrollera poängmatrisen",
            "input_source": "previous_step",
            "input_type": "json",
            "output_type": "json",
            "output_mode": "pass_through",
        },
    )
    swedish_checks = checks_for(swedish_bypass)
    assert swedish_checks["proposed_review_policy_topology"]["passed"] is False
    assert swedish_checks["applied_review_policy_topology"]["passed"] is False

    neutral_bypass = _review_policy_plan()
    _insert_review_plan_step(
        neutral_bypass,
        1,
        {
            "plan_step_ref": "stage_two",
            "name": "Stage 2",
            "input_source": "previous_step",
            "input_type": "json",
            "output_type": "json",
            "output_mode": "pass_through",
        },
    )
    neutral_checks = checks_for(neutral_bypass)
    assert neutral_checks["proposed_review_policy_topology"]["passed"] is False
    assert neutral_checks["applied_review_policy_topology"]["passed"] is False

    terminal = _review_policy_plan()
    terminal_steps = _review_plan_steps(terminal)
    terminal_steps[0]["review_policy"] = None
    terminal_steps[-1]["review_policy"] = {"mode": "view"}
    assert (
        checks_for(terminal)["proposed_review_policy_not_terminal_or_delivery"][
            "passed"
        ]
        is False
    )

    applied_wrong_target = _applied_flow_from_plan(_review_policy_plan())
    applied_steps = _applied_flow_steps(applied_wrong_target)
    applied_steps[0]["review_policy"] = None
    applied_steps[1]["review_policy"] = {"mode": "view"}
    assert (
        checks_for(baseline_plan, applied_wrong_target)["applied_review_policy_target"][
            "passed"
        ]
        is False
    )


def test_applied_flow_lifecycle_preserves_evidence_then_deletes_flow(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    config = harness.ApiConfig(
        base_url="http://localhost:8123/api/v1",
        api_key="test-key",
        timeout_seconds=1,
    )
    calls: list[tuple[str, str]] = []

    def request_json(*, method: str, path: str, **_: object) -> dict[str, object]:
        calls.append((method, path))
        if path == "/flows/ai-builder/plans/plan-1/create":
            return {
                "flow_id": "flow-1",
                "flow_name": "Review flow",
                "steps_created": 3,
                "steps_updated": 0,
                "steps_removed": 0,
            }
        return _applied_flow_from_plan(_review_policy_plan())

    def request_no_content(*, method: str, path: str, **_: object) -> None:
        calls.append((method, path))

    monkeypatch.setattr(harness, "_request_json", request_json)
    monkeypatch.setattr(harness, "_request_no_content", request_no_content)

    evidence, runtime_evidence, lifecycle = harness._apply_execute_and_cleanup_flow(
        case=harness.BattleCase(
            case_id="review-flow",
            prompt="Build a review Flow.",
            apply_plan=True,
        ),
        config=config,
        plan_id="plan-1",
        runtime_file_paths=(),
        timeout_seconds=1,
        artifact_output_dir=Path("/unused"),
    )

    assert runtime_evidence is None
    assert lifecycle == {"status": "deleted", "flow_id": "flow-1"}
    assert calls == [
        ("POST", "/flows/ai-builder/plans/plan-1/create"),
        ("GET", "/flows/flow-1/"),
        ("DELETE", "/flows/flow-1/"),
    ]
    assert evidence["apply_result"]["flow_id"] == "flow-1"
    assert evidence["flow"]["steps"][0]["review_policy"] == {"mode": "view"}
    assert evidence["evidence_scope"] == (
        "compiled_proposal_and_applied_draft_only; "
        "does_not_prove_runtime_checkpoint_pause_or_resume"
    )


def test_applied_flow_lifecycle_deletes_flow_when_fetch_fails(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    config = harness.ApiConfig(
        base_url="http://localhost:8123/api/v1",
        api_key="test-key",
        timeout_seconds=1,
    )
    deleted_paths: list[str] = []

    def request_json(*, path: str, **_: object) -> dict[str, object]:
        if path.endswith("/create"):
            return {"flow_id": "flow-created"}
        raise TimeoutError("flow fetch timed out")

    monkeypatch.setattr(harness, "_request_json", request_json)
    monkeypatch.setattr(
        harness,
        "_request_no_content",
        lambda *, path, **_kwargs: deleted_paths.append(path),
    )

    with raises(harness.BattleFlowLifecycleError) as exc_info:
        harness._apply_execute_and_cleanup_flow(
            case=harness.BattleCase(
                case_id="fetch-failure",
                prompt="Build a Flow.",
                apply_plan=True,
            ),
            config=config,
            plan_id="plan-1",
            runtime_file_paths=(),
            timeout_seconds=1,
            artifact_output_dir=Path("/unused"),
        )

    assert deleted_paths == ["/flows/flow-created/"]
    assert harness._failure_error_fields(exc_info.value) == {
        "error": "flow fetch timed out",
        "flow_lifecycle": {"status": "deleted", "flow_id": "flow-created"},
    }


def test_applied_flow_without_identity_fails_closed_without_guessing_cleanup(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    cleanup_calls: list[object] = []
    monkeypatch.setattr(harness, "_request_json", lambda **_kwargs: {})
    monkeypatch.setattr(
        harness,
        "_request_no_content",
        lambda **kwargs: cleanup_calls.append(kwargs),
    )

    with raises(harness.BattleFlowLifecycleError) as exc_info:
        harness._apply_execute_and_cleanup_flow(
            case=harness.BattleCase(
                case_id="missing-flow-id",
                prompt="Build a Flow.",
                apply_plan=True,
            ),
            config=harness.ApiConfig(
                base_url="http://localhost:8123/api/v1",
                api_key="test-key",
                timeout_seconds=1,
            ),
            plan_id="plan-1",
            runtime_file_paths=(),
            timeout_seconds=1,
            artifact_output_dir=Path("/unused"),
        )

    assert cleanup_calls == []
    assert harness._failure_error_fields(exc_info.value)["flow_lifecycle"] == {
        "status": "flow_identity_missing"
    }


def test_applied_flow_lifecycle_deletes_flow_when_runtime_times_out(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    config = harness.ApiConfig(
        base_url="http://localhost:8123/api/v1",
        api_key="test-key",
        timeout_seconds=1,
    )
    deleted_paths: list[str] = []

    monkeypatch.setattr(
        harness,
        "_request_json",
        lambda *, path, **_kwargs: (
            {"flow_id": "flow-runtime"}
            if path.endswith("/create")
            else _applied_flow_from_plan(_review_policy_plan())
        ),
    )
    monkeypatch.setattr(
        harness,
        "_execute_and_collect_runtime_evidence",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("runtime timed out")),
    )
    monkeypatch.setattr(
        harness,
        "_request_no_content",
        lambda *, path, **_kwargs: deleted_paths.append(path),
    )

    with raises(harness.BattleFlowLifecycleError, match="runtime timed out"):
        harness._apply_execute_and_cleanup_flow(
            case=harness.BattleCase(
                case_id="runtime-failure",
                prompt="Build and run a Flow.",
                apply_plan=True,
                execute_flow=True,
            ),
            config=config,
            plan_id="plan-1",
            runtime_file_paths=(Path("runtime.pdf"),),
            timeout_seconds=1,
            artifact_output_dir=Path("/unused"),
        )

    assert deleted_paths == ["/flows/flow-runtime/"]


def test_cleanup_failure_invalidates_an_otherwise_successful_observation(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    config = harness.ApiConfig(
        base_url="http://localhost:8123/api/v1",
        api_key="test-key",
        timeout_seconds=1,
    )
    monkeypatch.setattr(
        harness,
        "_request_json",
        lambda *, path, **_kwargs: (
            {"flow_id": "flow-leaked"}
            if path.endswith("/create")
            else _applied_flow_from_plan(_review_policy_plan())
        ),
    )
    monkeypatch.setattr(
        harness,
        "_request_no_content",
        lambda **_kwargs: (_ for _ in ()).throw(TimeoutError("delete timed out")),
    )

    with raises(harness.BattleFlowLifecycleError) as exc_info:
        harness._apply_execute_and_cleanup_flow(
            case=harness.BattleCase(
                case_id="cleanup-failure",
                prompt="Build a Flow.",
                apply_plan=True,
            ),
            config=config,
            plan_id="plan-1",
            runtime_file_paths=(),
            timeout_seconds=1,
            artifact_output_dir=Path("/unused"),
        )

    assert harness._failure_error_fields(exc_info.value) == {
        "error": "generated Flow cleanup failed: delete timed out",
        "flow_lifecycle": {"status": "cleanup_failed", "flow_id": "flow-leaked"},
    }


def test_plan_application_is_serialized_across_different_cases(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    config = harness.ApiConfig(
        base_url="http://localhost:8123/api/v1",
        api_key="test-key",
        timeout_seconds=1,
    )
    state_lock = Lock()
    active_applies = 0
    maximum_active_applies = 0

    def request_json(*, method: str, path: str, **_: object) -> dict[str, object]:
        nonlocal active_applies, maximum_active_applies
        if method == "POST":
            with state_lock:
                active_applies += 1
                maximum_active_applies = max(maximum_active_applies, active_applies)
            time.sleep(0.02)
            with state_lock:
                active_applies -= 1
            return {"flow_id": f"flow-{path.rsplit('/', 2)[-2]}"}
        return _applied_flow_from_plan(_review_policy_plan())

    monkeypatch.setattr(harness, "_request_json", request_json)
    monkeypatch.setattr(harness, "_request_no_content", lambda **_kwargs: None)

    def apply(plan_id: str) -> object:
        return harness._apply_execute_and_cleanup_flow(
            case=harness.BattleCase(
                case_id=plan_id,
                prompt="Build a Flow.",
                apply_plan=True,
            ),
            config=config,
            plan_id=plan_id,
            runtime_file_paths=(),
            timeout_seconds=1,
            artifact_output_dir=Path("/unused"),
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(apply, ("plan-a", "plan-b")))

    assert maximum_active_applies == 1


def test_runtime_sentinel_checks_persisted_named_results_and_plan_invariants() -> None:
    harness = _battle_harness()
    plan = _document_plan(
        terminal_mode="render_verbatim",
        terminal_input_source="previous_step",
    )
    diagnostics = _classifier_diagnostics()
    classifier_runs = diagnostics["classifier_runs"]
    assert isinstance(classifier_runs, list)
    classifier_run = classifier_runs[0]
    assert isinstance(classifier_run, dict)
    classifier_run["named_result_evidence"] = {
        "operation": "replace",
        "named_results": [
            {
                "name": "summary",
                "confidence": "high",
                "evidence": ["quote:user_message:user-1:summary"],
            }
        ],
        "confidence": "high",
        "reason": "The result includes a summary.",
        "evidence": [
            {
                "source_id": "user_message:user-1",
                "quote": "summary",
            }
        ],
    }

    later_clear = json.loads(json.dumps(diagnostics))
    later_clear_runs = later_clear["classifier_runs"]
    assert isinstance(later_clear_runs, list)
    later_clear_runs.append(
        {
            "named_result_evidence": {
                "operation": "clear",
                "named_results": [],
            }
        }
    )
    assert harness._persisted_named_result_names(later_clear) == []

    later_no_change = json.loads(json.dumps(diagnostics))
    later_no_change_runs = later_no_change["classifier_runs"]
    assert isinstance(later_no_change_runs, list)
    later_no_change_runs.append({})
    assert harness._persisted_named_result_names(later_no_change) == ["summary"]

    expected = {
        "min_steps": 2,
        "max_steps": 2,
        "terminal_output_type": "pdf",
        "terminal_document_output_mode": "render_verbatim",
        "expected_leaf_output_field_groups": [["summary"]],
        "expected_persisted_named_results": True,
        "expected_plan_invariant_vector": True,
        "expected_runtime_evidence": {},
    }

    def checks_for(
        *,
        candidate_plan: dict[str, Any],
        candidate_diagnostics: dict[str, object],
    ) -> dict[str, dict[str, object]]:
        report = harness._quality_report(
            plan=candidate_plan,
            summary=harness._summarize_plan(candidate_plan),
            expected=expected,
            event_summary={},
            classifier_diagnostics=candidate_diagnostics,
        )
        return {check["name"]: check for check in report["checks"]}

    baseline = checks_for(
        candidate_plan=plan,
        candidate_diagnostics=diagnostics,
    )
    assert baseline["sentinel_named_result_evidence"]["passed"] is True
    assert baseline["sentinel_invariant_vector"]["passed"] is True

    missing_evidence = json.loads(json.dumps(diagnostics))
    missing_classifier_runs = missing_evidence["classifier_runs"]
    assert isinstance(missing_classifier_runs, list)
    missing_classifier_run = missing_classifier_runs[0]
    assert isinstance(missing_classifier_run, dict)
    missing_classifier_run["named_result_evidence"] = None
    assert (
        checks_for(
            candidate_plan=plan,
            candidate_diagnostics=missing_evidence,
        )["sentinel_named_result_evidence"]["passed"]
        is False
    )

    missing_reader = json.loads(json.dumps(plan))
    missing_steps = missing_reader["proposal"]["spec"]["steps"]
    assert isinstance(missing_steps, list)
    missing_steps[0]["input_source"] = "question"
    invariant_check = checks_for(
        candidate_plan=missing_reader,
        candidate_diagnostics=diagnostics,
    )["sentinel_invariant_vector"]
    assert invariant_check["passed"] is False
    assert invariant_check["actual"]["per_source_reader_present"] is False


def test_non_sentinel_quality_report_is_unchanged_without_explicit_checks() -> None:
    harness = _battle_harness()
    plan = _document_plan(
        terminal_mode="render_verbatim",
        terminal_input_source="previous_step",
    )
    expected = {
        "min_steps": 2,
        "max_steps": 2,
        "terminal_output_type": "pdf",
        "terminal_document_output_mode": "render_verbatim",
        "expected_leaf_output_field_groups": [["summary"]],
        "expected_runtime_evidence": {
            "source_file_count": 6,
            "source_record_count": 6,
            "required_final_field_label_groups": [["summary"]],
            "required_visible_degradation_markers": [["framgår ej"]],
            "source_display_count": 6,
            "model_call_count": 7,
            "max_total_tokens": 250000,
        },
    }
    report = harness._quality_report(
        plan=plan,
        summary=harness._summarize_plan(plan),
        expected=expected,
        event_summary={},
        classifier_diagnostics=_classifier_diagnostics(),
        runtime_evidence=_six_file_runtime_evidence(),
    )
    new_check_names = {
        "sentinel_named_result_evidence",
        "sentinel_invariant_vector",
    }

    assert new_check_names.isdisjoint(check["name"] for check in report["checks"])


def test_six_file_runtime_gate_rejects_each_release_dimension() -> None:
    harness = _battle_harness()
    expected = {
        "expected_runtime_evidence": {
            "source_file_count": 6,
            "source_record_count": 6,
            "required_final_field_label_groups": [
                ["title"],
                ["year"],
                ["category"],
                ["type"],
                ["author"],
                ["conclusions"],
                ["summary"],
            ],
            "required_visible_degradation_markers": [
                ["pdf_text_likely_reversed"],
                ["framgår ej"],
            ],
            "source_display_count": 6,
            "model_call_count": 7,
            "max_total_tokens": 2000,
        }
    }

    def checks_for(evidence: dict[str, object]) -> dict[str, dict[str, object]]:
        report = harness._quality_report(
            plan={},
            summary={},
            expected=expected,
            event_summary={},
            runtime_evidence=evidence,
        )
        return {check["name"]: check for check in report["checks"]}

    baseline = checks_for(_six_file_runtime_evidence())
    for name in (
        "runtime_final_artifact",
        "runtime_source_file_count",
        "runtime_source_record_count",
        "runtime_one_record_per_source_file",
        "runtime_source_record_fields",
        "runtime_final_field_labels",
        "runtime_per_source_artifact_fields",
        "runtime_visible_degradation",
        "runtime_degradation_source_association",
        "runtime_source_display",
        "runtime_model_call_count",
        "runtime_total_tokens",
    ):
        assert baseline[name]["passed"] is True

    missing_field = _six_file_runtime_evidence()
    missing_field_artifact = _runtime_final_artifact(missing_field)
    artifact_text = missing_field_artifact.get("text")
    assert isinstance(artifact_text, str)
    missing_field_artifact["text"] = artifact_text.replace("Year: 2026", "2026")
    assert checks_for(missing_field)["runtime_final_field_labels"]["passed"] is False

    one_record_field_loss = _six_file_runtime_evidence()
    _runtime_documents(one_record_field_loss)[5].pop("year")
    assert (
        checks_for(one_record_field_loss)["runtime_source_record_fields"]["passed"]
        is False
    )

    global_only_evidence = _six_file_runtime_evidence()
    global_only_artifact = _runtime_final_artifact(global_only_evidence)
    source_labels = " ".join(
        str(document["source_label"])
        for document in _runtime_documents(global_only_evidence)
    )
    global_only_artifact["text"] = (
        "Title: Report\nYear: 2026\nCategory: Policy\nType: Report\n"
        "Author: Municipality\nConclusions: Conclusion\nSummary: Summary\n"
        "Extraction quality: pdf_text_likely_reversed; värde framgår ej\n"
        f"Sources: {source_labels}"
    )
    global_only_checks = checks_for(global_only_evidence)
    assert global_only_checks["runtime_final_field_labels"]["passed"] is True
    assert global_only_checks["runtime_visible_degradation"]["passed"] is True
    assert global_only_checks["runtime_source_display"]["passed"] is True
    assert global_only_checks["runtime_per_source_artifact_fields"]["passed"] is False
    assert (
        global_only_checks["runtime_degradation_source_association"]["passed"] is False
    )

    cardinality_drift = _six_file_runtime_evidence()
    _append_first_runtime_document(cardinality_drift)
    assert (
        checks_for(cardinality_drift)["runtime_source_record_count"]["passed"] is False
    )

    duplicate_source_mapping = _six_file_runtime_evidence()
    documents = _runtime_documents(duplicate_source_mapping)
    documents[5]["source_file_id"] = documents[0]["source_file_id"]
    assert (
        checks_for(duplicate_source_mapping)["runtime_one_record_per_source_file"][
            "passed"
        ]
        is False
    )

    hidden_degradation = _six_file_runtime_evidence()
    hidden_artifact = _runtime_final_artifact(hidden_degradation)
    hidden_text = hidden_artifact.get("text")
    assert isinstance(hidden_text, str)
    hidden_artifact["text"] = hidden_text.replace(
        "pdf_text_likely_reversed; värde framgår ej", ""
    )
    assert (
        checks_for(hidden_degradation)["runtime_visible_degradation"]["passed"] is False
    )

    missing_source = _six_file_runtime_evidence()
    missing_source_artifact = _runtime_final_artifact(missing_source)
    source_text = missing_source_artifact.get("text")
    assert isinstance(source_text, str)
    missing_source_artifact["text"] = source_text.replace("source-6.pdf", "")
    assert checks_for(missing_source)["runtime_source_display"]["passed"] is False

    misleading_legacy_estimate = _six_file_runtime_evidence()
    step_results = misleading_legacy_estimate["step_results"]
    assert isinstance(step_results, list)
    first_step = step_results[0]
    assert isinstance(first_step, dict)
    parameters = first_step["model_parameters_json"]
    assert isinstance(parameters, dict)
    parameters["per_source_call_count"] = 99
    _insert_runtime_step_result(
        misleading_legacy_estimate,
        2,
        {
            "step_order": 3,
            "status": "completed",
            "num_tokens_input": 10,
            "num_tokens_output": 5,
        },
    )
    provider_call_check = checks_for(misleading_legacy_estimate)[
        "runtime_model_call_count"
    ]
    assert provider_call_check["passed"] is True
    assert provider_call_check["actual"] == {
        "count": 7,
        "evidence_status": "complete",
        "total_count_truncated": False,
    }

    truncated_provider_calls = _six_file_runtime_evidence()
    provider_calls = truncated_provider_calls["provider_calls"]
    assert isinstance(provider_calls, dict)
    provider_calls["total_count_truncated"] = True
    truncated_check = checks_for(truncated_provider_calls)["runtime_model_call_count"]
    assert truncated_check["passed"] is False
    assert truncated_check["actual"]["evidence_status"] == "truncated"

    for invalid_total, invalid_truncation in (
        (None, False),
        (True, False),
        (-1, False),
        (7, "false"),
    ):
        invalid_provider_calls = _six_file_runtime_evidence()
        invalid_page = invalid_provider_calls["provider_calls"]
        assert isinstance(invalid_page, dict)
        invalid_page["total_count"] = invalid_total
        invalid_page["total_count_truncated"] = invalid_truncation
        invalid_check = checks_for(invalid_provider_calls)["runtime_model_call_count"]
        assert invalid_check["passed"] is False
        assert invalid_check["actual"]["evidence_status"] == "invalid"

    missing_artifact = _six_file_runtime_evidence()
    missing_artifact["final_artifact"] = None
    assert checks_for(missing_artifact)["runtime_final_artifact"]["passed"] is False


def test_runtime_evidence_collection_uses_published_contract(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    config = harness.ApiConfig(
        base_url="http://localhost:8123/api/v1",
        api_key="test-key",
        timeout_seconds=1,
    )
    source_paths = tuple(tmp_path / f"source-{index}.pdf" for index in range(1, 7))
    calls: list[tuple[str, str, dict[str, object] | None]] = []

    def request_json(
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        **_: object,
    ) -> dict[str, object]:
        calls.append((method, path, payload))
        if path == "/flows/flow-1/publish/":
            return {"id": "flow-1", "published_version": 4}
        if path == "/flows/flow-1/run-contract/":
            return {
                "published_flow_version": 4,
                "steps_requiring_input": [{"step_id": "reader-step"}],
            }
        if path == "/flows/flow-1/runs/" and method == "POST":
            return {"id": "run-1", "status": "queued"}
        if path == "/flows/flow-1/runs/run-1/":
            return {
                "id": "run-1",
                "status": "completed",
                "result": {
                    "kind": "artifact",
                    "files": [{"file_id": "artifact-1", "name": "report.pdf"}],
                },
            }
        if path == "/flows/flow-1/runs/run-1/evidence/":
            return {
                "run": {"id": "run-1", "status": "completed"},
                "step_results": [],
            }
        raise AssertionError((method, path, payload))

    uploaded_paths: list[Path] = []

    def upload_runtime_file(**kwargs: object) -> dict[str, object]:
        source_path = kwargs["source_path"]
        assert isinstance(source_path, Path)
        uploaded_paths.append(source_path)
        return {"id": f"uploaded-{len(uploaded_paths)}"}

    monkeypatch.setattr(harness, "_request_json", request_json)
    monkeypatch.setattr(harness, "_upload_runtime_file", upload_runtime_file)
    monkeypatch.setattr(
        harness,
        "_download_final_artifact",
        lambda **_: {
            "file_id": "artifact-1",
            "sha256": "d" * 64,
            "text": "Title: report",
        },
    )

    evidence = harness._execute_and_collect_runtime_evidence(
        config=config,
        flow_id="flow-1",
        runtime_file_paths=source_paths,
        timeout_seconds=1,
        artifact_output_dir=tmp_path,
        case_id="six-file-case",
    )

    assert uploaded_paths == list(source_paths)
    create_call = next(
        call for call in calls if call[:2] == ("POST", "/flows/flow-1/runs/")
    )
    assert create_call[2] == {
        "expected_flow_version": 4,
        "input_payload_json": None,
        "step_inputs": {
            "reader-step": {"file_ids": [f"uploaded-{index}" for index in range(1, 7)]}
        },
    }
    assert evidence["run"]["status"] == "completed"
    assert evidence["final_artifact"]["sha256"] == "d" * 64


def test_release_inventory_owns_required_dimensions_and_named_cases() -> None:
    harness = _battle_harness()
    cases_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_battle_cases.json"
    )
    cases = harness._read_cases_file(cases_path)
    acquisition_contract = harness._read_acquisition_contract(cases_path, cases=cases)
    by_id = {case.case_id: case for case in cases}

    assert acquisition_contract.artifact_schema_version == "ai-builder-live-release.v5"
    assert acquisition_contract.require_clean_source is True
    assert not hasattr(acquisition_contract, "thresholds")
    required_dimensions = {
        dimension
        for case_id in acquisition_contract.required_case_ids
        for dimension in by_id[case_id].release_dimensions
    }
    assert {
        "positive",
        "negative",
        "calibration",
        "file_role",
        "topology",
        "review_policy",
        "six_file_document_report",
        "first_pass_semantic",
    } <= required_dimensions
    assert all(
        by_id[case_id].required for case_id in acquisition_contract.required_case_ids
    )
    assert "complex_authoring_spec_first_pass" in acquisition_contract.required_case_ids

    review_case = by_id["ordinary_language_human_review_policy"]
    assert review_case.apply_plan is True
    assert review_case.execute_flow is False
    assert review_case.expected is not None
    assert review_case.expected["expected_review_policy"]["mode"] == "view"

    six_file_case = by_id["six_file_document_report_release_gate"]
    assert six_file_case.apply_plan is True
    assert six_file_case.execute_flow is True
    assert len(six_file_case.attachments) == 6
    assert len(six_file_case.runtime_files) == 6
    assert six_file_case.expected is not None
    assert six_file_case.expected["expected_persisted_named_results"] is True
    assert six_file_case.expected["expected_plan_invariant_vector"] is True
    assert six_file_case.expected["expected_runtime_evidence"] == {
        "source_file_count": 6,
        "source_record_count": 6,
        "required_final_field_label_groups": [
            ["titel", "title"],
            ["år", "year"],
            ["kategori", "category"],
            ["typ", "type"],
            ["författare", "author"],
            ["slutsatser", "conclusions"],
            ["sammanfattning", "summary"],
        ],
        "required_visible_degradation_markers": [
            ["pdf_text_likely_reversed"],
            ["framgår ej"],
        ],
        "source_display_count": 6,
        "model_call_count": 7,
        "max_total_tokens": 250000,
    }


def test_complex_authoring_case_enforces_first_pass_topology_independently() -> None:
    harness = _battle_harness()
    cases_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_battle_cases.json"
    )
    cases = harness._read_cases_file(cases_path)
    by_id = {case.case_id: case for case in cases}
    case = by_id["complex_authoring_spec_first_pass"]

    assert case.required is True
    assert case.apply_plan is True
    assert case.execute_flow is False
    assert case.expected is not None
    expected = case.expected["expected_first_pass_authoring"]

    def checks_for(plan: dict[str, object]) -> dict[str, dict[str, object]]:
        report = harness._quality_report(
            plan=plan,
            summary=harness._summarize_plan(plan),
            expected=case.expected,
            event_summary={},
            applied_flow=_applied_flow_from_plan(plan),
        )
        return {check["name"]: check for check in report["checks"]}

    baseline = checks_for(_complex_authoring_plan())
    first_pass_names = {name for name in baseline if name.startswith("first_pass_")}
    assert first_pass_names == {
        "first_pass_document_writer_count",
        "first_pass_pipeline",
        "first_pass_report_outline",
        "first_pass_task_headings_not_promoted",
        "first_pass_typed_analysis_contract",
        "first_pass_unique_step_names",
        "first_pass_proposed_review_policy_count",
        "first_pass_proposed_review_policy_targets",
        "first_pass_proposed_review_policy_producing_steps",
        "first_pass_applied_review_policy_count",
        "first_pass_applied_review_policy_targets",
        "first_pass_applied_review_policy_producing_steps",
    }
    assert all(baseline[name]["passed"] is True for name in first_pass_names)
    assert expected["proposal_call_count"] == 1
    assert expected["max_repair_attempts"] == 0

    proposed_only_report = harness._quality_report(
        plan=_complex_authoring_plan(),
        summary=harness._summarize_plan(_complex_authoring_plan()),
        expected=case.expected,
        event_summary={},
        applied_flow=None,
    )
    proposed_only_names = {
        check["name"]
        for check in proposed_only_report["checks"]
        if check["name"].startswith("first_pass_")
    }
    assert "first_pass_proposed_review_policy_count" in proposed_only_names
    assert not any(
        name.startswith("first_pass_applied_review_policy_")
        for name in proposed_only_names
    )

    wrong_outline = _complex_authoring_plan()
    _review_plan_steps(wrong_outline)[2]["assistant_spec"] = {
        "instructions": "Write one concise report."
    }
    assert checks_for(wrong_outline)["first_pass_report_outline"]["passed"] is False

    untyped_analysis = _complex_authoring_plan()
    _review_plan_steps(untyped_analysis)[1]["output_contract"] = None
    assert (
        checks_for(untyped_analysis)["first_pass_typed_analysis_contract"]["passed"]
        is False
    )

    promoted_task_heading = _complex_authoring_plan()
    _review_plan_steps(promoted_task_heading)[2]["name"] = "Processing rules"
    assert (
        checks_for(promoted_task_heading)["first_pass_task_headings_not_promoted"][
            "passed"
        ]
        is False
    )

    duplicate_name = _complex_authoring_plan()
    _review_plan_steps(duplicate_name)[2]["name"] = "Analyze transcript"
    assert checks_for(duplicate_name)["first_pass_unique_step_names"]["passed"] is False

    extra_writer = _complex_authoring_plan()
    _insert_review_plan_step(
        extra_writer,
        3,
        {
            "plan_step_ref": "write_appendix",
            "name": "Write appendix",
            "input_source": "previous_step",
            "input_type": "text",
            "output_type": "text",
            "output_mode": "pass_through",
            "assistant_spec": {"instructions": "Write a separate appendix."},
        },
    )
    extra_writer_checks = checks_for(extra_writer)
    assert extra_writer_checks["first_pass_document_writer_count"]["passed"] is False
    assert extra_writer_checks["first_pass_pipeline"]["passed"] is False

    missing_review = _complex_authoring_plan()
    _review_plan_steps(missing_review)[2]["review_policy"] = None
    assert (
        checks_for(missing_review)["first_pass_proposed_review_policy_count"]["passed"]
        is False
    )

    wrong_review_target = _complex_authoring_plan()
    wrong_review_steps = _review_plan_steps(wrong_review_target)
    wrong_review_steps[2]["review_policy"] = None
    wrong_review_steps[1]["review_policy"] = {"mode": "edit"}
    assert (
        checks_for(wrong_review_target)["first_pass_proposed_review_policy_targets"][
            "passed"
        ]
        is False
    )

    duplicate_review = _complex_authoring_plan()
    _review_plan_steps(duplicate_review)[1]["review_policy"] = {"mode": "edit"}
    duplicate_review_checks = checks_for(duplicate_review)
    assert (
        duplicate_review_checks["first_pass_proposed_review_policy_count"]["passed"]
        is False
    )
    assert (
        duplicate_review_checks["first_pass_applied_review_policy_count"]["passed"]
        is False
    )

    renderer_review = _complex_authoring_plan()
    renderer_review_steps = _review_plan_steps(renderer_review)
    renderer_review_steps[2]["review_policy"] = None
    renderer_review_steps[3]["review_policy"] = {"mode": "edit"}
    renderer_review_checks = checks_for(renderer_review)
    assert (
        renderer_review_checks["first_pass_proposed_review_policy_targets"]["passed"]
        is False
    )
    assert (
        renderer_review_checks["first_pass_proposed_review_policy_producing_steps"][
            "passed"
        ]
        is False
    )
    assert (
        renderer_review_checks["first_pass_applied_review_policy_targets"]["passed"]
        is False
    )
    assert (
        renderer_review_checks["first_pass_applied_review_policy_producing_steps"][
            "passed"
        ]
        is False
    )


def test_release_expectation_typos_fail_closed(tmp_path: Path) -> None:
    harness = _battle_harness()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": 8,
                "cases": [
                    {
                        "id": "typo",
                        "prompt": "Build a report.",
                        "expected": {
                            "expected_runtime_evidnce": {"source_file_count": 6}
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with raises(ValueError, match="unknown expectation keys"):
        harness._read_cases_file(cases_path)


def test_attachment_and_ambiguous_cases_gate_classifier_posture() -> None:
    harness = _battle_harness()
    cases = harness._read_cases_file(
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_battle_cases.json"
    )
    by_id = {case.case_id: case for case in cases}

    example = by_id["attachment_example_report_infers_disposition"].expected
    assert example is not None
    assert example["expected_classifier_slots"][0]["value"] == "both"
    assert example["expected_file_roles"][0]["role"] == "example_output"

    template = by_id["attachment_docx_template_placeholders_to_fields"].expected
    assert template is not None
    assert template["expected_classifier_slots"][0]["value"] == "docx_document"
    assert template["expected_file_roles"][0]["role"] == "template"

    ambiguous = by_id["ambiguous_report_without_attachment_asks_one_question"].expected
    assert ambiguous is not None
    assert ambiguous["expected_question_event_ids"] == ["report_disposition"]
    assert ambiguous["forbid_classifier_commit_grade_slots"] == ["report_disposition"]


def test_smoke_v3_is_locked_balanced_and_directly_selectable() -> None:
    harness = _battle_harness()
    cases_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_battle_cases.json"
    )

    cases = harness._cases_from_args(
        SimpleNamespace(
            cases_file=str(cases_path),
            run_suite=False,
            case_id=None,
            cohort=["smoke_v3"],
            max_cases=None,
        )
    )

    assert {case.case_id for case in cases} == {
        "advanced_explicit_e_service_submission",
        "advanced_explicit_open_eplatform_mapping",
        "ambiguous_report_without_attachment_asks_one_question",
        "attachment_docx_template_placeholders_to_fields",
        "attachment_example_report_infers_disposition",
        "complex_authoring_spec_first_pass",
        "hard_many_source_documents_exhaustive_pdf",
        "interview_input_procurement_requirements",
        "interview_open_meeting_audio",
        "ordinary_language_human_review_policy",
        "simple_document_metadata_json",
        "six_file_document_report_release_gate",
    }
    assert sum("json" in case.cohorts for case in cases) == 3
    assert sum("single_missing_dimension" in case.cohorts for case in cases) == 1
    assert sum("technical_contract" in case.cohorts for case in cases) == 2
    assert sum(bool(case.attachments) for case in cases) == 3
    assert [case.case_id for case in cases if case.execute_flow] == [
        "six_file_document_report_release_gate"
    ]


def test_municipal_journey_v1_balances_user_and_prompt_maturity() -> None:
    harness = _battle_harness()
    cases_path = (
        Path(__file__).resolve().parents[4]
        / "scripts"
        / "ai_builder_api_battle_cases.json"
    )
    cases = harness._cases_from_args(
        SimpleNamespace(
            cases_file=str(cases_path),
            run_suite=False,
            case_id=None,
            cohort=["municipal_journey_v1"],
            max_cases=None,
        )
    )

    assert {case.case_id for case in cases} == {
        "advanced_explicit_open_eplatform_mapping",
        "advanced_governed_procurement_report",
        "interview_input_citizen_feedback",
        "interview_open_citizen_feedback",
        "interview_open_lss_application",
        "interview_output_event_financing",
        "ordinary_json_lss_completeness",
        "ordinary_report_environmental_complaints",
    }
    expected_pairs = {
        ("persona_beginner", "prompt_vague"),
        ("persona_intermediate", "prompt_partial"),
        ("persona_domain_expert", "prompt_complete"),
        ("persona_technical", "prompt_contract"),
    }
    pair_counts = {pair: 0 for pair in expected_pairs}
    for case in cases:
        personas = [tag for tag in case.cohorts if tag.startswith("persona_")]
        prompt_maturity = [tag for tag in case.cohorts if tag.startswith("prompt_")]
        assert len(personas) == 1
        assert len(prompt_maturity) == 1
        pair = (personas[0], prompt_maturity[0])
        assert pair in pair_counts
        pair_counts[pair] += 1
    assert set(pair_counts.values()) == {2}
    for case_id in (
        "interview_open_citizen_feedback",
        "interview_open_lss_application",
    ):
        case = next(case for case in cases if case.case_id == case_id)
        assert case.expected is not None
        assert case.expected["terminal_output_type"] == "json"
        assert case.expected["max_steps"] == 4
        assert case.expected["max_reopened_question_count"] == 0

    with raises(ValueError, match="Omit --run-suite"):
        harness._cases_from_args(
            SimpleNamespace(
                cases_file=str(cases_path),
                run_suite=True,
                case_id=None,
                cohort=["municipal_journey_v1"],
                max_cases=None,
            )
        )

    with raises(ValueError, match="Omit --run-suite"):
        harness._cases_from_args(
            SimpleNamespace(
                cases_file=str(cases_path),
                run_suite=True,
                case_id=None,
                cohort=None,
                max_cases=None,
                file_ids=["global-file-override"],
            )
        )


def test_suite_reliability_counts_invalid_plan_errors() -> None:
    harness = _battle_harness()

    summary = harness._suite_reliability_summary(
        [
            {
                "case_id": "runtime_fields_explicit_case_metadata",
                "observation_status": "completed",
                "plan_id": None,
                "event_summary": {
                    "error_codes": ["self_correction_invalid_plan"],
                    "self_correction_quality_failure_count": 0,
                    "server_ask_question_text_only_count": 0,
                },
            },
            {
                "case_id": "runtime_fields_explicit_case_metadata",
                "observation_status": "completed",
                "plan_id": None,
                "event_summary": {
                    "error_codes": ["self_correction_invalid_plan"],
                    "self_correction_quality_failure_count": 0,
                    "server_ask_question_text_only_count": 0,
                },
            },
            {
                "case_id": "runtime_fields_explicit_case_metadata",
                "observation_status": "completed",
                "plan_id": "plan-1",
                "event_summary": {
                    "error_codes": [],
                    "self_correction_quality_failure_count": 0,
                    "server_ask_question_text_only_count": 0,
                },
            },
        ]
    )

    case_summary = summary["runtime_fields_explicit_case_metadata"]
    assert case_summary["run_count"] == 3
    assert case_summary["plan_created_count"] == 1
    assert case_summary["self_correction_invalid_plan_count"] == 2
    assert case_summary["error_code_counts"] == {"self_correction_invalid_plan": 2}


def test_suite_reliability_deduplicates_assumptions_across_repetitions() -> None:
    harness = _battle_harness()

    summary = harness._suite_reliability_summary(
        [
            {
                "case_id": "document_pdf_source_retention_balance",
                "observation_status": "completed",
                "plan_id": "plan-1",
                "assumptions": ["One section per source.", "Render as PDF."],
                "event_summary": {},
            },
            {
                "case_id": "document_pdf_source_retention_balance",
                "observation_status": "completed",
                "plan_id": "plan-2",
                "assumptions": ["Render as PDF.", "Keep source labels visible."],
                "event_summary": {},
            },
        ]
    )

    assert summary["document_pdf_source_retention_balance"]["assumptions"] == [
        "One section per source.",
        "Render as PDF.",
        "Keep source labels visible.",
    ]


def test_suite_plan_rate_excludes_execution_failures() -> None:
    harness = _battle_harness()

    summary = harness._suite_reliability_summary(
        [
            {
                "case_id": "municipal-flow",
                "observation_status": "completed",
                "plan_id": "plan-1",
                "event_summary": {},
            },
            {
                "case_id": "municipal-flow",
                "observation_status": "execution_failure",
                "plan_id": None,
                "event_summary": {},
            },
        ]
    )["municipal-flow"]

    assert summary["run_count"] == 1
    assert summary["plan_rate"] == 1.0
    assert summary["execution_failure_observation_count"] == 1


def test_suite_outcome_summary_counts_classes_by_cohort() -> None:
    harness = _battle_harness()

    summary = harness._suite_outcome_summary(
        [
            {
                "outcome_class": "clarification_stop_intended",
                "cohorts": ["municipal", "single_missing_dimension"],
            },
            {
                "outcome_class": "stalled_unanswered_question",
                "cohorts": ["municipal"],
            },
            {
                "outcome_class": "clarification_stop_intended",
                "cohorts": ["municipal"],
            },
        ]
    )

    assert summary["counts"] == {
        "clarification_stop_intended": 2,
        "stalled_unanswered_question": 1,
    }
    assert summary["by_cohort"] == {
        "municipal": {
            "clarification_stop_intended": 2,
            "stalled_unanswered_question": 1,
        },
        "single_missing_dimension": {"clarification_stop_intended": 1},
    }


def test_suite_conformance_summary_separates_mechanics_from_rubric() -> None:
    # A plan produced without repair is not a plan that satisfies the case.
    # Reading first-pass as a quality score overstated the product for a full
    # day, so the summary publishes both axes plus per-check unique cases.
    harness = _battle_harness()

    summary = harness._suite_conformance_summary(
        [
            {"outcome_class": "plan_first_pass", "expectation_verdict": "pass"},
            {
                "outcome_class": "plan_first_pass",
                "expectation_verdict": "fail",
                "failed_checks": [
                    {"name": "expected_leaf_output_fields"},
                    {"name": "expected_leaf_output_fields"},
                    {"name": "min_source_ref_steps"},
                ],
            },
            {
                "outcome_class": "plan_repaired",
                "expectation_verdict": "fail",
                "failed_checks": [{"name": "expected_leaf_output_fields"}],
            },
            {
                "outcome_class": "builder_error",
                "expectation_verdict": "not_evaluated",
            },
        ]
    )

    assert summary["expectation_verdict_counts"] == {
        "fail": 2,
        "not_evaluated": 1,
        "pass": 1,
    }
    # not_evaluated rows are excluded from the rate, not counted as failures.
    assert summary["conformance_rate"] == 0.3333
    assert summary["outcome_by_expectation"]["plan_first_pass"] == {
        "fail": 1,
        "pass": 1,
    }
    # A check repeated inside one case counts that case once.
    assert summary["failed_checks_by_unique_cases"] == {
        "expected_leaf_output_fields": 2,
        "min_source_ref_steps": 1,
    }


def test_suite_conformance_counts_repetitions_of_one_case_once() -> None:
    # "unique cases" must mean cases: with repetitions the previous counter
    # incremented once per observation, inflating every cluster by the
    # repetition factor.
    harness = _battle_harness()

    summary = harness._suite_conformance_summary(
        [
            {
                "case_id": "case-a",
                "repetition": index,
                "outcome_class": "plan_first_pass",
                "expectation_verdict": "fail",
                "failed_checks": [{"name": "expected_leaf_output_fields"}],
            }
            for index in range(1, 4)
        ]
    )

    assert summary["failed_checks_by_unique_cases"] == {
        "expected_leaf_output_fields": 1
    }


def test_event_summary_extracts_failure_detail() -> None:
    harness = _battle_harness()

    summary = harness._interaction_event_summary(
        [
            {
                "events": [
                    {
                        "event": "error",
                        "data": {
                            "code": "self_correction_quality_failure",
                            "message": "Quality retry failed.",
                            "details": {
                                "quality_failure_codes": "missing_leaf,wrong_mode",
                                "critic_issue_ids": ["json_input_rejects_all_previous"],
                                "feedback": "Use the structured output.",
                            },
                        },
                    }
                ]
            }
        ]
    )
    failure_summary = harness._failure_summary(summary)

    assert summary["error_codes"] == ["self_correction_quality_failure"]
    assert summary["failure_codes"] == ["missing_leaf", "wrong_mode"]
    assert summary["critic_issue_ids"] == ["json_input_rejects_all_previous"]
    assert summary["repair_feedback_texts"] == ["Use the structured output."]
    assert failure_summary["error_details"][0]["message"] == "Quality retry failed."


def test_event_summary_records_assumptions_for_posture_goldens(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    bundle_path = tmp_path / "bundle.json"
    harness._write_json_exclusive(bundle_path, {"case": "posture-golden"})

    summary = harness._interaction_event_summary(
        [
            {
                "events": [
                    {
                        "event": "requirements_summary",
                        "data": {"assumptions": ["One section per source.", ""]},
                    },
                    {
                        "event": "plan",
                        "data": {
                            "proposal": {
                                "assumptions": [
                                    "One section per source.",
                                    "Render as PDF.",
                                ]
                            }
                        },
                    },
                ]
            }
        ]
    )
    result = harness._suite_result(
        harness.seal_observation(
            {
                "case_identity": {
                    "id": "document_pdf_source_retention_balance",
                    "required": False,
                    "complexity": "custom",
                    "domain": "custom",
                    "cohorts": [],
                },
                "case": {"id": "document_pdf_source_retention_balance"},
                "session_id": "session-1",
                "plan_id": "plan-1",
                "repetition": 1,
                "plan_summary": {"step_count": 2},
                "event_summary": summary,
                "quality_report": {"checks": [], "warnings": [], "metrics": {}},
            }
        ),
        bundle_path,
    )
    reliability = harness._suite_reliability_summary([result])

    assert summary["assumptions"] == ["One section per source.", "Render as PDF."]
    assert result["assumptions"] == ["One section per source.", "Render as PDF."]
    assert reliability["document_pdf_source_retention_balance"]["assumptions"] == [
        "One section per source.",
        "Render as PDF.",
    ]


def test_benchmark_quality_failure_is_reported_without_failing_required_gate(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    harness = _battle_harness()
    _allow_clean_measurement_space(harness, monkeypatch)

    def fail_quality_check(*, case: Any, **_: Any) -> dict[str, Any]:
        bundle = _complete_live_case_bundle(
            harness,
            case,
            quality_checks=[
                {
                    "name": "terminal_document_output_mode",
                    "passed": False,
                    "actual": "pass_through",
                    "expected": "render_verbatim",
                }
            ],
        )
        bundle["created_at"] = "20260707T000000"
        bundle["plan_summary"] = {"step_count": 2}
        return bundle

    monkeypatch.setattr(harness, "_run_case", fail_quality_check)

    exit_code = harness._run_suite(
        cases=[
            harness.BattleCase(
                case_id="document_pdf_source_retention_balance", prompt="Build a PDF."
            )
        ],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=type(
            "Args",
            (),
            {
                "repetitions": 1,
                "space_id": "space-1",
            },
        )(),
        output_dir=tmp_path,
    )

    assert exit_code == 0
    summary_path = next(
        tmp_path.glob("ai-builder-api-battle-suite-*/suite-summary.json")
    )
    summary = json.loads(summary_path.read_text())
    assert summary["execution_failure_observation_count"] == 0
    assert summary["app_version"] == harness.LOCAL_APP_VERSION
    assert summary["expectation_failed_observation_count"] == 1
    assert summary["required_expectation_failed_observation_count"] == 0
    assert summary["sentinel_verdict"] is None
    assert summary["artifact_mode"] == "live_execution_exploratory_summary"
    assert summary["results"][0]["failed_expectation_check_count"] == 1
    assert all(check["passed"] for check in summary["sentinel_acquisition_checks"])


def test_reanalysis_can_use_current_case_expectations(tmp_path: Path) -> None:
    harness = _battle_harness()
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                **_complete_reanalysis_bundle(
                    harness,
                    case_id="document_pdf_source_retention_balance",
                    expected={"expected_leaf_output_field_groups": [["date_or_year"]]},
                ),
                "created_at": "20260707T000000",
                "plan": {
                    "proposal": {
                        "spec": {
                            "flow_name": "Document report",
                            "steps": [
                                {
                                    "plan_step_ref": "step_a",
                                    "name": "Read source",
                                    "input_source": "flow_input",
                                    "input_type": "document",
                                    "output_type": "json",
                                    "output_mode": "pass_through",
                                    "output_contract": {
                                        "type": "object",
                                        "properties": {
                                            "document_date": {"type": "string"}
                                        },
                                    },
                                }
                            ],
                        }
                    }
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    stale_output_dir = tmp_path / "stale"
    assert (
        harness._reanalyze_bundles(
            bundle_paths=[bundle_path],
            output_dir=stale_output_dir,
        )
        == 0
    )
    stale_bundle = json.loads(next(stale_output_dir.iterdir()).read_text())
    stale_checks = {
        check["name"]: check for check in stale_bundle["quality_report"]["checks"]
    }
    assert stale_checks["expected_leaf_output_fields"]["passed"] is False

    current_output_dir = tmp_path / "current"
    assert (
        harness._reanalyze_bundles(
            bundle_paths=[bundle_path],
            output_dir=current_output_dir,
            expected_overrides_by_case_id={
                "document_pdf_source_retention_balance": {
                    "expected_leaf_output_field_groups": [["document_date"]]
                }
            },
        )
        == 0
    )
    current_bundle = json.loads(next(current_output_dir.iterdir()).read_text())
    current_checks = {
        check["name"]: check for check in current_bundle["quality_report"]["checks"]
    }
    assert current_checks["expected_leaf_output_fields"]["passed"] is True


def test_reanalysis_preserves_expected_first_pass_provenance_checks(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    expected = {
        "expected_first_pass_authoring": {
            "require_classifier_request_composite_fingerprint": True,
            "require_progress_fingerprint": True,
            "proposal_call_count": 1,
            "max_repair_attempts": 0,
            "provider_failure_status": "none",
        }
    }
    bundle = _complete_reanalysis_bundle(
        harness,
        case_id="first-pass-reanalysis",
        expected=expected,
    )
    progress = bundle["live_execution_provenance"]["proposal_progress"]
    progress["call_count"] = 2
    progress["fingerprint"] = harness._canonical_sha256(
        {
            key: progress.get(key)
            for key in (
                "source",
                "call_count",
                "repair_attempts",
                "parse_repair_attempts",
                "attempts",
                "provider_failure_status",
                "public_error_code_count",
            )
        }
    )
    bundle_path = tmp_path / "first-pass.json"
    bundle_path.write_text(json.dumps(bundle), encoding="utf-8")

    output_dir = tmp_path / "reanalyzed"
    assert (
        harness._reanalyze_bundles(
            bundle_paths=[bundle_path],
            output_dir=output_dir,
        )
        == 0
    )
    reanalyzed = json.loads(next(output_dir.iterdir()).read_text())
    checks = {check["name"]: check for check in reanalyzed["quality_report"]["checks"]}
    assert checks["first_pass_proposal_call_count"]["passed"] is False


def test_case_loader_merges_synthetic_user_profile_with_case_overrides(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": 8,
                "synthetic_user_profiles": {
                    "document_report_owner": {
                        "description": "Owner building a report from documents.",
                        "question_answers": {
                            "primary_runtime_input": {
                                "selected_option_id": "documents"
                            },
                            "post_processing_goal": {
                                "selected_option_id": "extract_key_information"
                            },
                            "terminal_output": {"selected_option_id": "pdf_document"},
                        },
                    }
                },
                "cases": [
                    {
                        "id": "profiled-case",
                        "prompt": "Help me design the flow.",
                        "synthetic_user_profile": "document_report_owner",
                        "question_answer_overrides": {
                            "terminal_output": {"selected_option_id": "structured_json"}
                        },
                        "cohorts": ["vague", "document", "json"],
                        "expected": {
                            "preferred_question_event_ids": ["post_processing_goal"],
                            "allowed_question_event_ids": [
                                "primary_runtime_input",
                                "terminal_output",
                            ],
                            "forbidden_question_event_ids": ["docx_output_mode"],
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    case = harness._read_cases_file(cases_path)[0]

    assert case.synthetic_user_profile == "document_report_owner"
    assert case.cohorts == ("vague", "document", "json")
    assert case.configured_question_answers == {
        "primary_runtime_input": {"selected_option_id": "documents"},
        "post_processing_goal": {"selected_option_id": "extract_key_information"},
        "terminal_output": {"selected_option_id": "structured_json"},
    }
    assert case.question_answer_sources == {
        "primary_runtime_input": "profile",
        "post_processing_goal": "profile",
        "terminal_output": "case_override",
    }

    malformed = json.loads(cases_path.read_text(encoding="utf-8"))
    malformed["cases"][0]["expected"]["preferred_question_event_ids"] = (
        "post_processing_goal"
    )
    cases_path.write_text(json.dumps(malformed), encoding="utf-8")
    with raises(ValueError, match="must be a list of unique, non-empty strings"):
        harness._read_cases_file(cases_path)


def test_case_loader_requires_answers_for_plan_required_question_paths(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    cases_path = tmp_path / "cases.json"
    payload = {
        "version": 8,
        "synthetic_user_profiles": {
            "document_owner": {
                "description": "Owner who uploads source documents.",
                "question_answers": {
                    "primary_runtime_input": {"selected_option_id": "documents"}
                },
            }
        },
        "cases": [
            {
                "id": "plan-required",
                "prompt": "Help me build the flow.",
                "synthetic_user_profile": "document_owner",
                "expected": {
                    "preferred_question_event_ids": ["primary_runtime_input"],
                    "allowed_question_event_ids": ["terminal_output"],
                },
            }
        ],
    }
    cases_path.write_text(json.dumps(payload), encoding="utf-8")

    with raises(ValueError, match="terminal_output"):
        harness._read_cases_file(cases_path)

    payload["cases"][0]["expected"]["allow_question_instead_of_plan"] = True
    cases_path.write_text(json.dumps(payload), encoding="utf-8")

    case = harness._read_cases_file(cases_path)[0]
    assert case.case_id == "plan-required"


def test_case_loader_accepts_typed_runtime_input_field_answers(tmp_path: Path) -> None:
    harness = _battle_harness()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": harness.SUPPORTED_CASES_FILE_VERSION,
                "cases": [
                    {
                        "id": "runtime-fields",
                        "prompt": (
                            "At run time, the user enters a case id that should "
                            "shape the result."
                        ),
                        "question_answer_overrides": {
                            "runtime_metadata_field_details": {
                                "input_fields": [
                                    {
                                        "value": {
                                            "name": "case_id",
                                            "label": "Case id",
                                            "type": "text",
                                            "required": True,
                                            "options": [],
                                        },
                                        "purpose": "shape_result",
                                    }
                                ]
                            }
                        },
                        "expected": {
                            "preferred_question_event_ids": [
                                "runtime_metadata_field_details"
                            ]
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    case = harness._read_cases_file(cases_path)[0]

    assert case.configured_question_answers == {
        "runtime_metadata_field_details": {
            "input_fields": [
                {
                    "value": {
                        "name": "case_id",
                        "label": "Case id",
                        "type": "text",
                        "required": True,
                        "options": [],
                    },
                    "purpose": "shape_result",
                }
            ]
        }
    }


def test_case_loader_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    harness = _battle_harness()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        """{
          "version": 8,
          "cases": [{
            "id": "duplicate-answer",
            "prompt": "Build a flow with one runtime field.",
            "question_answer_overrides": {
              "runtime_metadata_fields": {"selected_option_id": "no_extra_metadata"},
              "runtime_metadata_fields": {"selected_option_id": "basic_runtime_metadata"}
            }
          }]
        }""",
        encoding="utf-8",
    )

    with raises(ValueError, match="Duplicate JSON key: runtime_metadata_fields"):
        harness._read_cases_file(cases_path)


@mark.parametrize(
    ("question_id", "input_fields", "error"),
    [
        (
            "runtime_metadata_field_details",
            [
                {
                    "value": {"name": "case_id", "label": "Case id"},
                    "purpose": "interpret_input",
                },
                {
                    "value": {"name": "CASE_ID", "label": "Case identifier"},
                    "purpose": "shape_result",
                },
            ],
            "unique field names",
        ),
        (
            "runtime_metadata_field_details",
            [{"value": {"name": "case_id", "label": "Case id"}}],
            "purpose",
        ),
        (
            "primary_runtime_input",
            [
                {
                    "value": {"name": "case_id", "label": "Case id"},
                    "purpose": "interpret_input",
                }
            ],
            "only valid for runtime metadata field details",
        ),
    ],
)
def test_case_loader_rejects_invalid_runtime_input_field_answers(
    tmp_path: Path,
    question_id: str,
    input_fields: list[dict[str, object]],
    error: str,
) -> None:
    harness = _battle_harness()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": harness.SUPPORTED_CASES_FILE_VERSION,
                "cases": [
                    {
                        "id": "invalid-runtime-fields",
                        "prompt": "Build a flow with run-time fields.",
                        "question_answer_overrides": {
                            question_id: {"input_fields": input_fields}
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with raises(ValueError, match=error):
        harness._read_cases_file(cases_path)


def test_configured_answer_uses_exact_option_id_and_never_falls_back() -> None:
    harness = _battle_harness()
    question = {
        "question_id": "primary_runtime_input",
        "allow_custom": False,
        "options": [
            {"id": "audio", "value": "audio", "label": "Audio"},
            {"id": "documents", "value": "documents", "label": "Documents"},
        ],
    }

    answer = harness._configured_question_answer(
        question=question,
        configured_answers={
            "primary_runtime_input": {"selected_option_id": "documents"}
        },
        answer_sources={"primary_runtime_input": "profile"},
    )

    assert answer["answer_source"] == "profile"
    assert answer["question_answer"]["selected_option_ids"] == ["documents"]
    assert answer["question_answer"]["selected_values"] == ["documents"]
    assert (
        harness._configured_question_answer(
            question=question,
            configured_answers={},
            answer_sources={},
        )
        is None
    )
    with raises(ValueError, match="does not allow a custom answer"):
        harness._configured_question_answer(
            question=question,
            configured_answers={
                "primary_runtime_input": {"custom_value": "Something else"}
            },
            answer_sources={"primary_runtime_input": "case_override"},
        )


def test_configured_runtime_input_fields_require_collection_question() -> None:
    harness = _battle_harness()
    answer_config = {
        "runtime_metadata_field_details": {
            "input_fields": [
                {
                    "value": {
                        "name": "case_id",
                        "label": "Case id",
                        "type": "text",
                        "required": True,
                        "options": [],
                    },
                    "purpose": "shape_result",
                }
            ]
        }
    }
    question = {
        "question_id": "runtime_metadata_field_details",
        "allow_custom": False,
        "input_field_collection": True,
        "options": [],
    }

    answer = harness._configured_question_answer(
        question=question,
        configured_answers=answer_config,
        answer_sources={"runtime_metadata_field_details": "case_override"},
    )

    assert answer == {
        "message": "Case id (case_id)",
        "answer_source": "case_override",
        "question_answer": {
            "kind": "structured_question_answer",
            "question_id": "runtime_metadata_field_details",
            "input_fields": [
                {
                    "value": {
                        "name": "case_id",
                        "label": "Case id",
                        "type": "text",
                        "required": True,
                        "options": [],
                    },
                    "purpose": "shape_result",
                }
            ],
        },
    }
    with raises(ValueError, match="input-field collection"):
        harness._configured_question_answer(
            question={**question, "input_field_collection": False},
            configured_answers=answer_config,
            answer_sources={"runtime_metadata_field_details": "case_override"},
        )


def test_plan_required_form_field_cases_have_complete_synthetic_answers() -> None:
    harness = _battle_harness()

    cases = harness._read_cases_file(harness.DEFAULT_CASES_FILE)
    field_cases = [
        case
        for case in cases
        if case.expected and case.expected.get("expected_form_field_groups")
    ]

    assert field_cases
    for case in field_cases:
        configured_answers = case.configured_question_answers or {}
        assert configured_answers.get("runtime_metadata_fields") == {
            "selected_option_id": "basic_runtime_metadata"
        }, case.case_id
        answer_config = configured_answers.get("runtime_metadata_field_details")
        assert isinstance(answer_config, dict), case.case_id
        answer = harness.StructuredQuestionAnswerMetadata.model_validate(
            {
                "question_id": "runtime_metadata_field_details",
                "input_fields": answer_config.get("input_fields"),
            }
        )
        assert answer.input_fields, case.case_id
        allowed_ids = set(case.expected.get("allowed_question_event_ids") or [])
        assert "runtime_metadata_field_details" in allowed_ids, case.case_id


def test_journey_outcome_distinguishes_intended_clarification_from_stall() -> None:
    harness = _battle_harness()
    interactions = [
        {
            "events": [
                {
                    "event": "question",
                    "data": {
                        "question_id": "primary_runtime_input",
                        "question": "What is the input?",
                        "allow_custom": False,
                        "selection_mode": "single",
                        "options": [{"id": "documents"}],
                    },
                }
            ]
        }
    ]
    expected = {"preferred_question_event_ids": ["primary_runtime_input"]}

    intended = harness._journey_summary(
        interactions,
        expected={**expected, "allow_question_instead_of_plan": True},
        interaction_limit=6,
    )
    stalled = harness._journey_summary(
        interactions,
        expected=expected,
        interaction_limit=6,
    )

    assert intended["outcome_class"] == "clarification_stop_intended"
    assert stalled["outcome_class"] == "stalled_unanswered_question"


def test_question_relevance_separates_unassessed_from_unknown_under_rubric() -> None:
    harness = _battle_harness()
    interactions = [
        {
            "events": [
                {
                    "event": "question",
                    "data": {
                        "question_id": "unexpected_dimension",
                        "question": "Vilket alternativ vill du använda?",
                        "options": [{"id": "one"}],
                    },
                }
            ]
        }
    ]

    unassessed = harness._journey_summary(
        interactions,
        expected={},
        interaction_limit=6,
    )
    unknown_under_rubric = harness._journey_summary(
        interactions,
        expected={"preferred_question_event_ids": ["primary_runtime_input"]},
        interaction_limit=6,
    )
    unknown_under_explicitly_empty_rubric = harness._journey_summary(
        interactions,
        expected={"preferred_question_event_ids": []},
        interaction_limit=6,
    )

    assert unassessed["questions"][0]["relevance"] == "unassessed"
    assert unassessed["question_relevance_counts"] == {
        "preferred": 0,
        "allowed": 0,
        "forbidden": 0,
        "unclassified": 0,
        "unassessed": 1,
    }
    assert unknown_under_rubric["questions"][0]["relevance"] == "unclassified"
    assert (
        unknown_under_explicitly_empty_rubric["questions"][0]["relevance"]
        == "unclassified"
    )


def test_journey_summary_preserves_order_and_marks_reopened_questions() -> None:
    harness = _battle_harness()
    interactions = [
        {
            "events": [
                {
                    "event": "question",
                    "data": {
                        "question_id": "primary_runtime_input",
                        "question": "What is the input?",
                        "allow_custom": False,
                        "selection_mode": "single",
                        "options": [{"id": "documents"}],
                    },
                }
            ]
        },
        {
            "question_answer": {
                "question_id": "primary_runtime_input",
                "selected_option_ids": ["documents"],
            },
            "configured_answer_source": "profile",
            "events": [
                {
                    "event": "question",
                    "data": {
                        "question_id": "terminal_output",
                        "question": "What is the output?",
                        "allow_custom": False,
                        "selection_mode": "single",
                        "options": [{"id": "pdf_document"}],
                    },
                }
            ],
        },
        {
            "question_answer": {
                "question_id": "terminal_output",
                "selected_option_ids": ["pdf_document"],
            },
            "configured_answer_source": "case_override",
            "events": [
                {
                    "event": "question",
                    "data": {
                        "question_id": "primary_runtime_input",
                        "question": "What is the input?",
                        "allow_custom": False,
                        "selection_mode": "single",
                        "options": [{"id": "documents"}],
                    },
                }
            ],
        },
        {
            "question_answer": {
                "question_id": "primary_runtime_input",
                "selected_option_ids": ["documents"],
            },
            "configured_answer_source": "profile",
            "plan_id": "plan-1",
            "events": [{"event": "plan", "data": {"plan_id": "plan-1"}}],
            "latest_session": {
                "telemetry": {
                    "repair_attempts_total": 0,
                    "parse_repair_attempts_total": 0,
                }
            },
        },
    ]

    journey = harness._journey_summary(
        interactions,
        expected={
            "preferred_question_event_ids": ["primary_runtime_input"],
            "allowed_question_event_ids": ["terminal_output"],
            "forbidden_question_event_ids": [],
        },
        interaction_limit=6,
    )

    assert journey["termination"] == "plan_created"
    assert journey["question_event_ids"] == [
        "primary_runtime_input",
        "terminal_output",
        "primary_runtime_input",
    ]
    assert journey["unique_question_event_ids"] == [
        "primary_runtime_input",
        "terminal_output",
    ]
    assert journey["reopened_question_ids"] == ["primary_runtime_input"]
    assert journey["questions"][0]["resolution"] == "reopened"
    assert journey["questions"][1]["resolution"] == "resolved"
    assert journey["questions"][2]["resolution"] == "resolved"
    assert journey["questions"][0]["answer_source"] == "profile"
    assert journey["questions"][0]["next_outcome"] == "next_question"
    assert journey["questions"][0]["next_question_id"] == "terminal_output"
    assert journey["questions"][1]["relevance"] == "allowed"
    assert journey["plan_outcome"]["kind"] == "first_pass_success"

    final_turn_error = harness._journey_summary(
        [{"events": []}] * 5
        + [{"events": [{"event": "error", "data": {"code": "provider_error"}}]}],
        expected={},
        interaction_limit=6,
    )
    assert final_turn_error["termination"] == "turn_error"

    plan_with_error = harness._journey_summary(
        [
            {"events": [{"event": "error", "data": {"code": "provider_error"}}]},
            {"plan_id": "plan-2", "events": [{"event": "plan", "data": {}}]},
        ],
        expected={},
        interaction_limit=6,
    )
    assert plan_with_error["outcome_class"] == "plan_with_error"


def _verdict(
    question_id: str,
    *,
    preferred: set[str] | None = None,
    allowed: set[str] | None = None,
    forbidden: set[str] | None = None,
    commit_grade: set[str] | None = None,
) -> tuple[bool, str]:
    harness = _battle_harness()
    return harness._first_question_relevance_verdict(
        question_id,
        preferred_ids=preferred or set(),
        allowed_ids=allowed or set(),
        forbidden_ids=forbidden or set(),
        first_run_commit_grade_slots=commit_grade or set(),
    )


def test_first_question_asking_a_commit_grade_slot_is_stale() -> None:
    passed, reason = _verdict(
        "post_processing_goal",
        preferred={"post_processing_goal"},
        commit_grade={"post_processing_goal"},
    )
    assert passed is False
    assert reason == "stale_commit_grade"


def test_first_question_prefers_remaining_unresolved_preferred() -> None:
    passed, reason = _verdict(
        "terminal_output",
        preferred={"post_processing_goal", "terminal_output"},
        commit_grade={"post_processing_goal"},
    )
    assert passed is True
    assert reason == "preferred"

    passed, reason = _verdict(
        "report_disposition",
        preferred={"terminal_output"},
        allowed={"report_disposition"},
    )
    assert passed is False
    assert reason == "preferred_unresolved_remaining"


def test_first_question_primary_input_exception_applies() -> None:
    # The documented product exception: primary input may precede purpose
    # when purpose was the fixture-preferred slot.
    passed, reason = _verdict(
        "primary_runtime_input",
        preferred={"post_processing_goal"},
        allowed={"primary_runtime_input"},
    )
    assert passed is True
    assert reason == "primary_input_exception"


def test_first_question_allowed_passes_when_no_preferred_remain() -> None:
    passed, reason = _verdict(
        "report_disposition",
        preferred={"post_processing_goal"},
        allowed={"report_disposition"},
        commit_grade={"post_processing_goal"},
    )
    assert passed is True
    assert reason == "allowed"


def test_first_question_forbidden_and_unclassified_always_fail() -> None:
    passed, reason = _verdict(
        "terminal_output",
        preferred={"post_processing_goal"},
        forbidden={"terminal_output"},
    )
    assert passed is False
    assert reason == "forbidden"

    passed, reason = _verdict(
        "mystery_question",
        preferred={"post_processing_goal"},
    )
    assert passed is False
    assert reason == "unclassified"


def test_evaluator_identity_carries_measurement_semantics_versions() -> None:
    harness = _battle_harness()
    assert harness.QUESTION_RELEVANCE_SEMANTICS_VERSION == 2
    assert harness.OUTCOME_CLASSIFICATION_SEMANTICS_VERSION == 4
    assert harness.OBSERVATION_INPUT_IDENTITY_SEMANTICS_VERSION == 3
    assert harness.SUPPORTED_CASES_FILE_VERSION == 8
    identity = harness._suite_evaluator_identity(
        release_identity={},
        run_context={},
        expected_observations=[],
    )
    assert identity["question_relevance_semantics_version"] == 2
    assert identity["outcome_classification_semantics_version"] == 4
    assert identity["observation_input_identity_semantics_version"] == 3


def test_planner_evidence_skips_planner_less_interactions() -> None:
    # Auto-resolved turns (limit/DOCX/purpose defaults) legitimately make
    # zero planner calls: no usage event means identity-neutral, not
    # identity-missing. Ambiguous usage stays a failure, and a bundle with
    # no observed planner at all still fails closed downstream.
    harness = _battle_harness()
    interactions = [
        {"events": [{"event": "usage", "data": {"last_model": "openai/gpt"}}]},
        {"events": [{"event": "question", "data": {"question_id": "x"}}]},
        {
            "events": [
                {"event": "usage", "data": {"last_model": "openai/gpt"}},
                {"event": "usage", "data": {"last_model": "openai/other"}},
            ]
        },
    ]

    observed, observations, missing, terminal_errors, count = (
        harness._planner_model_evidence_from_interactions(interactions)
    )

    assert observed == ["openai/gpt"]
    assert [o["interaction_index"] for o in observations] == [1]
    assert missing == [3]
    assert terminal_errors == []
    assert count == 3
