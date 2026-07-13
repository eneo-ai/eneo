from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

from pytest import MonkeyPatch, raises


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
                "schema_version": 13,
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
    build = {
        "app_version": harness.LOCAL_APP_VERSION,
        "source_revision": revision,
        "harness_sha256": harness_sha256,
        "cases_sha256": cases_sha256,
    }
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
        "build": {**build, "sha256": harness._canonical_sha256(build)},
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
    build = {
        "app_version": harness.LOCAL_APP_VERSION,
        "source_revision": revision,
        "harness_sha256": harness_sha256,
        "cases_sha256": cases_sha256,
    }
    return {
        "source": {
            "revision": revision,
            "revision_sha256": hashlib.sha256(revision.encode("utf-8")).hexdigest(),
            "tracked_clean": True,
        },
        "build": {**build, "sha256": harness._canonical_sha256(build)},
        "model": {"requested_id": requested_model_id},
        "prompt": {
            "case_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        },
    }


def test_cases_file_rejects_misspelled_classifier_expectation(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
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
                ]
            }
        ),
        encoding="utf-8",
    )

    with raises(ValueError, match="unknown keys: slot_nam"):
        _battle_harness()._read_cases_file(cases_path)


def test_cases_file_rejects_misspelled_evidence_posture_key(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
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
                ]
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
    assert baseline_checks["classifier_file_role:file-1"]["passed"] is True
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
        ("file_roles", "role", "reference_material", "classifier_file_role:file-1"),
        ("file_roles", "confidence", "medium", "classifier_file_role:file-1"),
        ("file_roles", "evidence_level", "inferred", "classifier_file_role:file-1"),
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
    assert checks_for(wrong_coverage)["classifier_file_role:file-1"]["passed"] is False

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


def test_required_case_skip_fails_suite(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    missing_env = "ENEO_AI_BUILDER_REQUIRED_TEST_FILE_ID"
    monkeypatch.delenv(missing_env, raising=False)

    exit_code = harness._run_suite(
        cases=[
            harness.BattleCase(
                case_id="required-file-role",
                prompt="Build from the attached source.",
                required=True,
                file_id_envs=(missing_env,),
            )
        ],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=type("Args", (), {"repetitions": 1, "space_id": "space-1"})(),
        output_dir=tmp_path,
    )

    assert exit_code == 1
    summary_path = next(
        tmp_path.glob("ai-builder-api-battle-suite-*/suite-summary.json")
    )
    summary = json.loads(summary_path.read_text())
    assert summary["skipped_run_count"] == 1
    assert summary["required_skipped_run_count"] == 1
    assert summary["failure_count"] == 1


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
    source_path.write_text(
        json.dumps(
            {
                "artifact_mode": "live_execution",
                "live_execution_provenance": {
                    "source_revision": "immutable-source-revision"
                },
                "case": {"id": "live-case", "expected": {}},
                "interactions": [],
                "plan": None,
            }
        ),
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
    assert reanalyzed["live_execution_provenance"] == {
        "source_revision": "immutable-source-revision"
    }
    assert reanalyzed["reanalysis_provenance"]["source_bundle_sha256"] == (
        hashlib.sha256(source_bytes).hexdigest()
    )


def test_release_thresholds_are_predeclared_and_compared(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    gate = harness.ReleaseGate(
        required_case_ids=("required-positive",),
        thresholds=harness.ReleaseThresholds(
            max_case_errors=0,
            max_quality_failures=0,
            max_required_skips=0,
        ),
    )
    case = harness.BattleCase(
        case_id="required-positive",
        prompt="Build the required positive case.",
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
        return {
            "created_at": "20260713T120001",
            "artifact_mode": "live_execution",
            "live_execution_provenance": _live_provenance_fixture(
                harness,
                prompt=case.prompt,
            ),
            "case": {"id": "required-positive", "required": True},
            "session_id": "session-1",
            "plan_id": "plan-1",
            "plan_summary": {"step_count": 1},
            "event_summary": {},
            "quality_report": {"checks": [], "warnings": [], "metrics": {}},
        }

    monkeypatch.setattr(harness, "_run_case", successful_case)
    exit_code = harness._run_suite(
        cases=[case],
        config=harness.ApiConfig(
            base_url="http://localhost:8123/api/v1",
            api_key="test-key",
            timeout_seconds=1,
        ),
        args=type("Args", (), {"repetitions": 1, "space_id": "space-1"})(),
        output_dir=tmp_path,
        release_gate=gate,
    )

    assert exit_code == 0
    suite_dir = next(tmp_path.glob("ai-builder-api-battle-suite-*"))
    assert suite_dir.stat().st_mode & 0o777 == 0o700
    manifest = json.loads((suite_dir / "release-manifest.json").read_text())
    assert manifest["thresholds"] == {
        "max_case_errors": 0,
        "max_quality_failures": 0,
        "max_required_skips": 0,
    }
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    assert all(check["passed"] for check in summary["release_threshold_checks"])

    failed_checks = harness._evaluate_release_thresholds(
        gate.thresholds,
        case_error_count=0,
        quality_failure_run_count=1,
        required_skipped_run_count=0,
    )
    assert (
        next(
            check for check in failed_checks if check["name"] == "max_quality_failures"
        )["passed"]
        is False
    )


def test_suite_identity_rechecks_a_to_b_before_green_summary(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
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
            "case": {"id": case.case_id, "required": True},
            "session_id": "session-1",
            "plan_id": "plan-1",
            "plan_summary": {"step_count": 1},
            "event_summary": {},
            "quality_report": {"checks": [], "warnings": [], "metrics": {}},
        }

    monkeypatch.setattr(harness, "_run_case", successful_case)

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
    )

    assert exit_code == 1
    suite_dir = next(tmp_path.glob("ai-builder-api-battle-suite-*"))
    case_bundle = json.loads(
        next(suite_dir.glob("ai-builder-api-battle-test-*.json")).read_text()
    )
    assert case_bundle["release_identity"] == identity_a
    identity_check_names = {
        check["name"]
        for check in case_bundle["quality_report"]["checks"]
        if check["name"].startswith("suite_")
    }
    assert identity_check_names == {
        "suite_source_revision_identity",
        "suite_build_input_identity",
        "suite_requested_model_identity",
        "suite_case_prompt_identity",
    }
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    final_checks = {
        check["name"]: check for check in summary["release_identity_recheck_checks"]
    }
    assert final_checks["suite_build_identity_unchanged"]["passed"] is False
    assert summary["suite_identity_failure_count"] == 1
    assert summary["failure_count"] == 1


def test_release_gate_rejects_dirty_source_before_creating_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    gate = harness.ReleaseGate(
        artifact_schema_version="ai-builder-live-release.v1",
        required_case_ids=("required-positive",),
        thresholds=harness.ReleaseThresholds(
            max_case_errors=0,
            max_quality_failures=0,
            max_required_skips=0,
        ),
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
            release_gate=gate,
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

    provenance = harness._live_execution_provenance(
        case=case,
        latest_session=latest_session,
        classifier_diagnostics=classifier_diagnostics,
        requested_model_id=None,
    )

    assert provenance["mode"] == "live_execution"
    assert provenance["source"]["revision"]
    assert len(provenance["source"]["revision_sha256"]) == 64
    assert provenance["build"]["app_version"] == harness.LOCAL_APP_VERSION
    assert len(provenance["build"]["sha256"]) == 64
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

    missing_model = {**provenance, "model": {"observed_ids": [], "sha256": "0" * 64}}
    assert (
        next(
            check
            for check in harness._live_provenance_checks(missing_model)
            if check["name"] == "live_model_provenance_complete"
        )["passed"]
        is False
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
            )
        }

    baseline = checks_for(_live_provenance_fixture(harness, prompt=case.prompt))
    assert all(check["passed"] is True for check in baseline.values())

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


def test_apply_and_fetch_flow_preserves_compiled_structure_scope(
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

    monkeypatch.setattr(harness, "_request_json", request_json)

    evidence = harness._apply_and_fetch_flow(
        config=config,
        plan_id="plan-1",
    )

    assert calls == [
        ("POST", "/flows/ai-builder/plans/plan-1/create"),
        ("GET", "/flows/flow-1/"),
    ]
    assert evidence["apply_result"]["flow_id"] == "flow-1"
    assert evidence["flow"]["steps"][0]["review_policy"] == {"mode": "view"}
    assert evidence["evidence_scope"] == (
        "compiled_proposal_and_applied_draft_only; "
        "does_not_prove_runtime_checkpoint_pause_or_resume"
    )


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

    extra_model_stage = _six_file_runtime_evidence()
    _insert_runtime_step_result(
        extra_model_stage,
        2,
        {
            "step_order": 3,
            "status": "completed",
            "num_tokens_input": 10,
            "num_tokens_output": 5,
        },
    )
    assert checks_for(extra_model_stage)["runtime_model_call_count"]["passed"] is False

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
    release_gate = harness._read_release_gate(cases_path, cases=cases)
    by_id = {case.case_id: case for case in cases}

    assert release_gate.artifact_schema_version == "ai-builder-live-release.v1"
    assert release_gate.require_clean_source is True
    assert release_gate.thresholds == harness.ReleaseThresholds(
        max_case_errors=0,
        max_quality_failures=0,
        max_required_skips=0,
    )
    required_dimensions = {
        dimension
        for case_id in release_gate.required_case_ids
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
    } <= required_dimensions
    assert all(by_id[case_id].required for case_id in release_gate.required_case_ids)

    review_case = by_id["ordinary_language_human_review_policy"]
    assert review_case.apply_plan is True
    assert review_case.execute_flow is False
    assert review_case.expected is not None
    assert review_case.expected["expected_review_policy"]["mode"] == "view"

    six_file_case = by_id["six_file_document_report_release_gate"]
    assert six_file_case.apply_plan is True
    assert six_file_case.execute_flow is True
    assert len(six_file_case.file_id_envs) == 6
    assert len(six_file_case.runtime_file_path_envs) == 6
    assert six_file_case.expected is not None
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


def test_release_expectation_typos_fail_closed(tmp_path: Path) -> None:
    harness = _battle_harness()
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "id": "typo",
                        "prompt": "Build a report.",
                        "expected": {
                            "expected_runtime_evidnce": {"source_file_count": 6}
                        },
                    }
                ]
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
