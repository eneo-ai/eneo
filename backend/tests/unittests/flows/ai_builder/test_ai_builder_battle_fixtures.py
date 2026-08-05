from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

from pytest import CaptureFixture, MonkeyPatch, raises

BACKEND_ROOT = Path(__file__).resolve().parents[4]
CASES_PATH = BACKEND_ROOT / "scripts" / "ai_builder_api_battle_cases.json"
GENERATOR_PATH = BACKEND_ROOT / "scripts" / "generate_battle_fixtures.py"
FIXTURE_DIR = BACKEND_ROOT / "scripts" / "fixtures" / "ai_builder_battle"
PROTOCOL_NAME = "01_protokoll_bun_2026_02_25.pdf"
TJNSTESKRIVELSE_CASE_IDS = {
    "interview_open_tjansteskrivelse",
    "advanced_sundsvall_tjansteskrivelse_runtime_sources_docx",
}


def _load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _fixture_hashes(fixture_dir: Path) -> dict[str, str]:
    return {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(fixture_dir.iterdir())
        if path.is_file()
    }


def test_generator_is_deterministic_and_portable_with_pinned_protocol(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    generator = _load_module("generate_battle_fixtures_portable", GENERATOR_PATH)
    fixture_dir = tmp_path / "fixtures"
    env_path = fixture_dir / "battle_fixtures.env"
    source_path = tmp_path / "protocol-source.pdf"
    shutil.copyfile(FIXTURE_DIR / PROTOCOL_NAME, source_path)
    monkeypatch.setattr(generator, "FIXTURE_DIR", fixture_dir)
    monkeypatch.setattr(generator, "ENV_PATH", env_path)

    expected_protocol_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert generator.AUTHENTIC_PROTOCOL_SHA256 == expected_protocol_sha256

    first_content_hashes = generator._write_fixtures(source_path=source_path)
    generator._write_env_file(first_content_hashes, captured_evidence=None)
    first_hashes = _fixture_hashes(fixture_dir)

    second_content_hashes = generator._write_fixtures()
    generator._write_env_file(second_content_hashes, captured_evidence=None)
    second_hashes = _fixture_hashes(fixture_dir)

    assert second_hashes == first_hashes
    assert "/Users/" not in env_path.read_text(encoding="utf-8")


def test_capture_mode_rejects_fixture_manifest_drift_without_regenerating(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    generator = _load_module("generate_battle_fixtures_capture", GENERATOR_PATH)
    fixture_dir = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_DIR, fixture_dir)
    drifted_path = fixture_dir / "02_tjansteskrivelse_underlag.docx"
    drifted_path.write_bytes(drifted_path.read_bytes() + b"drift")
    drifted_bytes = drifted_path.read_bytes()
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "classifier_diagnostics": {
                    "classifier_runs": [
                        {
                            "source_inventory": [
                                {
                                    "kind": "uploaded_file",
                                    "file_id": "fixture-upload-1",
                                    "source_sha256": "a" * 64,
                                }
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(generator, "FIXTURE_DIR", fixture_dir)
    monkeypatch.setattr(generator, "ENV_PATH", fixture_dir / "battle_fixtures.env")
    monkeypatch.setenv(
        "ENEO_AI_BUILDER_DECISION_LETTER_TEMPLATE_FILE_ID",
        "fixture-upload-1",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(GENERATOR_PATH),
            "--capture-evidence-from",
            str(bundle_path),
        ],
    )

    with raises(ValueError, match="fixture manifest drift.*02_tjansteskrivelse"):
        generator.main()

    assert drifted_path.read_bytes() == drifted_bytes


def test_capture_mode_reports_only_populated_fixture_bindings(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    generator = _load_module("generate_battle_fixtures_capture_count", GENERATOR_PATH)
    fixture_dir = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_DIR, fixture_dir)
    for binding in generator.ATTACHMENT_BINDINGS:
        monkeypatch.delenv(binding.file_id_env, raising=False)
    monkeypatch.setenv(
        "ENEO_AI_BUILDER_DECISION_LETTER_TEMPLATE_FILE_ID",
        "fixture-upload-1",
    )
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "classifier_diagnostics": {
                    "classifier_runs": [
                        {
                            "source_inventory": [
                                {
                                    "kind": "uploaded_file",
                                    "file_id": "fixture-upload-1",
                                    "source_sha256": "a" * 64,
                                },
                                {
                                    "kind": "uploaded_file",
                                    "file_id": "unrelated-upload",
                                    "source_sha256": "b" * 64,
                                },
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(generator, "FIXTURE_DIR", fixture_dir)
    monkeypatch.setattr(generator, "ENV_PATH", fixture_dir / "battle_fixtures.env")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(GENERATOR_PATH),
            "--capture-evidence-from",
            str(bundle_path),
        ],
    )

    assert generator.main() == 0

    assert "captured_attachment_count=1" in capsys.readouterr().out


def test_case_loader_rejects_runtime_bindings_without_execution(
    tmp_path: Path,
) -> None:
    harness = _load_module(
        "ai_builder_api_battle_test_fixtures",
        GENERATOR_PATH.with_name("ai_builder_api_battle_test.py"),
    )
    invalid_path = tmp_path / "invalid-runtime-binding.json"
    invalid_path.write_text(
        json.dumps(
            {
                "version": 4,
                "cases": [
                    {
                        "id": "plan-only-with-runtime-files",
                        "prompt": "Build a plan-only flow.",
                        "runtime_file_path_envs": ["RUNTIME_PATH"],
                        "runtime_file_sha256_envs": ["RUNTIME_SHA256"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with raises(
        ValueError,
        match="cannot declare runtime file bindings without execute_flow=true",
    ):
        harness._read_cases_file(invalid_path)


def _question_observation(
    harness: ModuleType,
    *,
    expected: dict[str, Any],
    question_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    interactions = [
        {
            "events": [
                {
                    "event": "question",
                    "data": {
                        "question_id": question_id,
                        "question": "Vilken inriktning ska flödet ha?",
                        "options": [{"id": "configured"}],
                    },
                },
                {"event": "plan", "data": {"plan_id": "plan-1"}},
            ],
            "plan_id": "plan-1",
        }
    ]
    return (
        harness._interaction_event_summary(interactions),
        harness._journey_summary(interactions, expected=expected, interaction_limit=6),
    )


def _minimal_plan() -> dict[str, object]:
    return {
        "proposal": {
            "spec": {
                "flow_name": "Tjänsteskrivelse",
                "steps": [
                    {
                        "plan_step_ref": "draft",
                        "input_source": "flow_input",
                        "input_type": "text",
                        "output_type": "json",
                        "output_mode": "pass_through",
                    }
                ],
            }
        }
    }


def test_interview_case_evaluator_rejects_pdf_metadata_first_question() -> None:
    harness = _load_module(
        "ai_builder_api_battle_test_interview_evaluator",
        GENERATOR_PATH.with_name("ai_builder_api_battle_test.py"),
    )
    cases = harness._read_cases_file(CASES_PATH)
    assert len(cases) == 122
    family = {
        case.case_id: case for case in cases if "tjansteskrivelse_v1" in case.cohorts
    }
    assert set(family) == TJNSTESKRIVELSE_CASE_IDS
    expected = family["interview_open_tjansteskrivelse"].expected
    assert isinstance(expected, dict)
    plan = _minimal_plan()
    summary = harness._summarize_plan(plan)

    bad_event_summary, bad_journey = _question_observation(
        harness,
        expected=expected,
        question_id="pdf_generation_mode",
    )
    bad_report = harness._quality_report(
        plan=plan,
        summary=summary,
        expected=expected,
        event_summary=bad_event_summary,
        journey=bad_journey,
    )
    bad_checks = {check["name"]: check for check in bad_report["checks"]}
    assert bad_checks["forbidden_question_event_ids"]["passed"] is False
    assert bad_checks["first_question_relevance"]["passed"] is False

    event_summary, journey = _question_observation(
        harness,
        expected=expected,
        question_id="post_processing_goal",
    )
    report = harness._quality_report(
        plan=plan,
        summary=summary,
        expected=expected,
        event_summary=event_summary,
        journey=journey,
    )
    assert all(check["passed"] for check in report["checks"])


def _flagship_plan(output_contract: dict[str, Any]) -> dict[str, object]:
    return {
        "proposal": {
            "spec": {
                "flow_name": "Sundsvalls tjänsteskrivelse",
                "form_fields": [
                    {"name": "diarienummer"},
                    {"name": "handlaggare"},
                    {"name": "forvaltning"},
                    {"name": "namnd"},
                    {"name": "beslutsdatum"},
                ],
                "steps": [
                    {
                        "plan_step_ref": "extract_sources",
                        "input_source": "flow_input",
                        "input_type": "document",
                        "output_type": "json",
                        "output_mode": "pass_through",
                        "output_contract": {
                            "type": "object",
                            "properties": {"sources": {"type": "array"}},
                        },
                    },
                    {
                        "plan_step_ref": "draft_sections",
                        "input_source": "specific_steps",
                        "input_type": "json",
                        "input_bindings": {
                            "source_refs": [
                                {
                                    "step_ref": "extract_sources",
                                    "output": "result",
                                    "field_path": "sources",
                                }
                            ]
                        },
                        "output_type": "json",
                        "output_mode": "pass_through",
                        "output_contract": output_contract,
                        "review_policy": {"mode": "edit"},
                    },
                    {
                        "plan_step_ref": "fill_template",
                        "input_source": "specific_steps",
                        "input_type": "json",
                        "input_bindings": {
                            "source_refs": [
                                {
                                    "step_ref": "draft_sections",
                                    "output": "result",
                                    "field_path": "sections",
                                }
                            ]
                        },
                        "output_type": "docx",
                        "output_mode": "template_fill",
                    },
                ],
            }
        }
    }


def _flagship_classifier_diagnostics() -> dict[str, object]:
    return {
        "classifier_runs": [
            {
                "source_inventory": [
                    {
                        "source_id": "user_message:user-1",
                        "kind": "user_message",
                        "source_sha256": "a" * 64,
                    },
                    {
                        "source_id": "uploaded_file:template-1",
                        "kind": "uploaded_file",
                        "source_sha256": "b" * 64,
                        "file_id": "template-1",
                        "coverage": "fully_seen",
                    },
                ],
                "slots": [
                    {
                        "slot_name": "terminal_output",
                        "value": "docx_document",
                        "confidence": "high",
                        "evidence_level": "explicit",
                        "evidence": [
                            {
                                "source_id": "user_message:user-1",
                                "quote": "fylla den bifogade DOCX-mallen",
                            }
                        ],
                    }
                ],
                "file_roles": [
                    {
                        "file_id": "template-1",
                        "role": "template",
                        "confidence": "high",
                        "evidence_level": "explicit",
                        "evidence": [
                            {
                                "source_id": "user_message:user-1",
                                "quote": "bifogade DOCX-filen är den enda mallen",
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _flagship_applied_flow(
    output_contract: dict[str, Any],
    *,
    primary_input_type: str,
) -> dict[str, object]:
    return {
        "steps": [
            {
                "step_order": 1,
                "plan_step_ref": "extract_sources",
                "input_source": "flow_input",
                "input_type": primary_input_type,
                "output_type": "json",
                "output_mode": "pass_through",
                "output_contract": {
                    "type": "object",
                    "properties": {"sources": {"type": "array"}},
                },
            },
            {
                "step_order": 2,
                "plan_step_ref": "draft_sections",
                "input_source": "specific_steps",
                "input_type": "json",
                "output_type": "json",
                "output_mode": "pass_through",
                "output_contract": output_contract,
                "review_policy": {"mode": "edit"},
            },
            {
                "step_order": 3,
                "plan_step_ref": "fill_template",
                "input_source": "specific_steps",
                "input_type": "json",
                "output_type": "docx",
                "output_mode": "template_fill",
            },
        ]
    }


def test_flagship_case_evaluator_rejects_text_primary_input() -> None:
    harness = _load_module(
        "ai_builder_api_battle_test_flagship_evaluator",
        GENERATOR_PATH.with_name("ai_builder_api_battle_test.py"),
    )
    cases = harness._read_cases_file(CASES_PATH)
    family = {
        case.case_id: case for case in cases if "tjansteskrivelse_v1" in case.cohorts
    }
    case = family["advanced_sundsvall_tjansteskrivelse_runtime_sources_docx"]
    assert case.apply_plan is True
    expected = case.expected
    assert isinstance(expected, dict)
    output_contract = expected["expected_output_contract_schema"]
    assert isinstance(output_contract, dict)
    plan = _flagship_plan(output_contract)

    def report(
        candidate: dict[str, object],
        applied_flow: dict[str, object],
    ) -> dict[str, object]:
        return harness._quality_report(
            plan=candidate,
            summary=harness._summarize_plan(candidate),
            expected=expected,
            classifier_diagnostics=_flagship_classifier_diagnostics(),
            attached_file_ids=("template-1",),
            applied_flow=applied_flow,
        )

    applied_flow = _flagship_applied_flow(
        output_contract,
        primary_input_type="document",
    )
    passing_report = report(plan, applied_flow)
    assert all(check["passed"] for check in passing_report["checks"])

    wrong_plan = deepcopy(plan)
    first_step = wrong_plan["proposal"]["spec"]["steps"][0]
    assert isinstance(first_step, dict)
    first_step["input_type"] = "text"
    wrong_checks = {
        check["name"]: check for check in report(wrong_plan, applied_flow)["checks"]
    }
    assert wrong_checks["expected_primary_input_type"]["passed"] is False

    wrong_applied_flow = _flagship_applied_flow(
        output_contract,
        primary_input_type="text",
    )
    wrong_applied_checks = {
        check["name"]: check for check in report(plan, wrong_applied_flow)["checks"]
    }
    assert (
        wrong_applied_checks["applied_expected_primary_input_type"]["passed"] is False
    )
