from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from pytest import MonkeyPatch


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


def test_attachment_case_file_ids_can_resolve_from_environment(
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    case = harness.BattleCase(
        case_id="attachment_docx_template_placeholders_to_fields",
        prompt="Build a DOCX flow.",
        file_id_envs=("ENEO_AI_BUILDER_DOCX_TEMPLATE_FILE_ID",),
    )
    args = type("Args", (), {"file_ids": None})()

    assert harness._missing_file_id_envs(case, args) == (
        "ENEO_AI_BUILDER_DOCX_TEMPLATE_FILE_ID",
    )
    skipped = harness._skipped_case_bundle(
        case=case,
        repetition=None,
        missing_envs=("ENEO_AI_BUILDER_DOCX_TEMPLATE_FILE_ID",),
    )
    assert skipped["skipped"] is True
    assert skipped["case"]["id"] == "attachment_docx_template_placeholders_to_fields"
    assert "ENEO_AI_BUILDER_DOCX_TEMPLATE_FILE_ID" in skipped["skip_reason"]

    monkeypatch.setenv(
        "ENEO_AI_BUILDER_DOCX_TEMPLATE_FILE_ID",
        "file-template-1",
    )

    assert harness._missing_file_id_envs(case, args) == ()
    assert harness._case_file_ids(case, args) == ("file-template-1",)

    cli_args = type("Args", (), {"file_ids": ["file-cli-1"]})()
    assert harness._missing_file_id_envs(case, cli_args) == ()
    assert harness._case_file_ids(case, cli_args) == ("file-cli-1",)


def test_suite_reliability_counts_invalid_plan_errors() -> None:
    harness = _battle_harness()

    summary = harness._suite_reliability_summary(
        [
            {
                "case_id": "runtime_fields_explicit_case_metadata",
                "plan_id": None,
                "event_summary": {
                    "error_codes": ["self_correction_invalid_plan"],
                    "self_correction_quality_failure_count": 0,
                    "server_ask_question_text_only_count": 0,
                },
            },
            {
                "case_id": "runtime_fields_explicit_case_metadata",
                "plan_id": None,
                "event_summary": {
                    "error_codes": ["self_correction_invalid_plan"],
                    "self_correction_quality_failure_count": 0,
                    "server_ask_question_text_only_count": 0,
                },
            },
            {
                "case_id": "runtime_fields_explicit_case_metadata",
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
                "plan_id": "plan-1",
                "assumptions": ["One section per source.", "Render as PDF."],
                "event_summary": {},
            },
            {
                "case_id": "document_pdf_source_retention_balance",
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
        {
            "case": {"id": "document_pdf_source_retention_balance"},
            "session_id": "session-1",
            "plan_id": "plan-1",
            "repetition": 1,
            "plan_summary": {"step_count": 2},
            "event_summary": summary,
            "quality_report": {"checks": [], "warnings": [], "metrics": {}},
        },
        tmp_path / "bundle.json",
    )
    reliability = harness._suite_reliability_summary([result])

    assert summary["assumptions"] == ["One section per source.", "Render as PDF."]
    assert result["assumptions"] == ["One section per source.", "Render as PDF."]
    assert reliability["document_pdf_source_retention_balance"]["assumptions"] == [
        "One section per source.",
        "Render as PDF.",
    ]


def test_suite_returns_failure_when_quality_checks_fail(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    harness = _battle_harness()

    def fail_quality_check(**_: Any) -> dict[str, Any]:
        return {
            "created_at": "20260707T000000",
            "app_version": harness.LOCAL_APP_VERSION,
            "case": {"id": "document_pdf_source_retention_balance"},
            "session_id": "session-1",
            "plan_id": "plan-1",
            "plan_summary": {"step_count": 2},
            "event_summary": {},
            "quality_report": {
                "checks": [
                    {
                        "name": "terminal_document_output_mode",
                        "passed": False,
                        "actual": "pass_through",
                        "expected": "render_verbatim",
                    }
                ],
                "warnings": [],
                "metrics": {},
            },
        }

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

    assert exit_code == 1
    summary_path = next(
        tmp_path.glob("ai-builder-api-battle-suite-*/suite-summary.json")
    )
    summary = json.loads(summary_path.read_text())
    assert summary["case_error_count"] == 0
    assert summary["app_version"] == harness.LOCAL_APP_VERSION
    assert summary["quality_failure_run_count"] == 1
    assert summary["failure_count"] == 1
    assert summary["results"][0]["failed_check_count"] == 1


def test_reanalysis_can_use_current_case_expectations(tmp_path: Path) -> None:
    harness = _battle_harness()
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "created_at": "20260707T000000",
                "case": {
                    "id": "document_pdf_source_retention_balance",
                    "expected": {
                        "expected_leaf_output_field_groups": [["date_or_year"]]
                    },
                },
                "interactions": [],
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
