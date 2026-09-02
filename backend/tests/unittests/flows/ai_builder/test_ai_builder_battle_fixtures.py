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

from pytest import MonkeyPatch, raises

BACKEND_ROOT = Path(__file__).resolve().parents[4]
CASES_PATH = BACKEND_ROOT / "scripts" / "ai_builder_api_battle_cases.json"
GENERATOR_PATH = BACKEND_ROOT / "scripts" / "generate_battle_fixtures.py"
FIXTURE_DIR = BACKEND_ROOT / "scripts" / "fixtures" / "ai_builder_battle"
MANIFEST_PATH = FIXTURE_DIR / "manifest.json"
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
    manifest_path = fixture_dir / "manifest.json"
    source_path = tmp_path / "protocol-source.pdf"
    shutil.copyfile(FIXTURE_DIR / PROTOCOL_NAME, source_path)
    monkeypatch.setattr(generator, "FIXTURE_DIR", fixture_dir)
    monkeypatch.setattr(generator, "MANIFEST_PATH", manifest_path)

    expected_protocol_sha256 = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert generator.AUTHENTIC_PROTOCOL_SHA256 == expected_protocol_sha256

    first_content_hashes = generator._write_fixtures(source_path=source_path)
    generator._write_manifest(first_content_hashes)
    first_hashes = _fixture_hashes(fixture_dir)

    second_content_hashes = generator._write_fixtures()
    generator._write_manifest(second_content_hashes)

    assert second_content_hashes == first_content_hashes
    assert _fixture_hashes(fixture_dir) == first_hashes
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["version"] == generator.MANIFEST_VERSION
    assert manifest["fixtures"] == first_content_hashes
    # The manifest ships with the repository, so it may carry content hashes
    # only: a path or file id from the generating machine is what stops a fresh
    # checkout from running the corpus.
    assert "/Users/" not in manifest_path.read_text(encoding="utf-8")

    tampered_source = tmp_path / "tampered-protocol-source.pdf"
    tampered_source.write_bytes(source_path.read_bytes() + b"tampered")
    with raises(ValueError, match="Authentic protocol SHA-256 mismatch"):
        generator._write_fixtures(source_path=tampered_source)
    assert _fixture_hashes(fixture_dir) == first_hashes


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
                "version": harness.SUPPORTED_CASES_FILE_VERSION,
                "cases": [
                    {
                        "id": "plan-only-with-runtime-files",
                        "prompt": "Build a plan-only flow.",
                        "runtime_files": [PROTOCOL_NAME],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    with raises(
        ValueError,
        match="cannot declare runtime_files without execute_flow=true",
    ):
        harness._read_cases_file(invalid_path)


def test_battle_cases_and_fixture_manifest_cannot_drift_apart() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    pinned = manifest["fixtures"]
    assert isinstance(pinned, dict)
    assert pinned

    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    referenced = {
        name
        for case in payload["cases"]
        for key in ("attachments", "runtime_files")
        for name in case.get(key, ())
    }
    assert referenced
    assert referenced <= set(pinned)

    # A fixture name only means something if the bytes behind it are still the
    # pinned ones; otherwise a case measures a different document than the
    # receipt claims it did.
    on_disk = _fixture_hashes(FIXTURE_DIR)
    assert {name: on_disk.get(name) for name in pinned} == pinned


def test_long_context_cohort_covers_large_municipal_format_journeys() -> None:
    harness = _load_module(
        "ai_builder_api_battle_test_long_context",
        GENERATOR_PATH.with_name("ai_builder_api_battle_test.py"),
    )
    cases = harness._read_cases_file(CASES_PATH)
    long_context_cases = [case for case in cases if "long_context" in case.cohorts]

    assert len(long_context_cases) == 10
    assert all(5_000 <= len(case.prompt) <= 10_000 for case in long_context_cases)
    assert {
        case.case_id: hashlib.sha256(case.prompt.encode("utf-8")).hexdigest()
        for case in long_context_cases
    } == {
        "long_context_livsmedelsverksamhet_json_to_pdf": "ae7c9df9b8708fe9ee60e3b4db06ee082877f6d600d37924345dfd314e69f529",
        "long_context_bygglov_pdf_to_docx": "2bcd291a87dd606ca827259315a74e016b3426ec9436ebab02106f8494941d39",
        "long_context_grannehornande_text_to_docx": "b131e8ac9e64d63db3ff38c10b29162db4e7bdcfb3c4a5efc00c8a91c18a10b2",
        "long_context_foreningsbidrag_documents_to_docx": "5c79177edea2561672862deb59c521f534f269b16465795ce022cdcc32eb3dce",
        "long_context_varmepumpsanmalan_json_pdf_to_pdf": "cd507c50f75cd3dd78bf6c55085fd510040ebabbcabcb41532f257306bbadc78",
        "long_context_miljofarlig_verksamhet_documents_to_json": "854d955eb73a7c39fe9dcd9a132445e61e882828660e0c23b0c94e2e299a7f76",
        "long_context_serveringstillstand_json_pdf_to_docx": "0fed3247a4a6c0f4b992a9a4b9f35793ab73d30598df1344ccbca65fc62aef5f",
        "long_context_synpunkt_text_to_json": "e2eceb8a445ca69d57848886f7c443d7cc99b48b24d3e3cad9f84843194ea669",
        "long_context_allman_handling_text_to_json": "26e362fea31af1e2ee82d78bc693915243f566fb1883515ed2c4bdfac418e49d",
        "long_context_inackorderingstillagg_pdf_to_pdf": "ab21302b04d630b904079ad98107e694934e97469552dea296253c1478eaffe7",
    }
    assert {
        (
            case.expected.get("expected_primary_input_type"),
            case.expected.get("terminal_output_type"),
        )
        for case in long_context_cases
        if case.expected is not None
    } == {
        ("document", "docx"),
        ("document", "pdf"),
        ("json", "pdf"),
        ("document", "json"),
        ("file", "docx"),
        ("file", "json"),
        ("file", "pdf"),
        ("text", "docx"),
        ("text", "json"),
    }


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
    assert len(cases) >= 122
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
                "slot_outcomes": {
                    "terminal_output": {
                        "outcome": "resolved",
                        "value": "docx_document",
                        "confidence": "high",
                        "reason": "The user asks to fill the attached DOCX template.",
                        "evidence_level": "explicit",
                        "evidence": [
                            {
                                "source_id": "user_message:user-1",
                                "quote": "fylla den bifogade DOCX-mallen",
                            }
                        ],
                    }
                },
                "diagnostics": [],
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
