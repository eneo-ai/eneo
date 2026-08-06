from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID

from pytest import CaptureFixture, MonkeyPatch, raises


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
                "schema_version": 19,
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
        "runtime_source_sha256s": [],
    }
    return {
        **payload,
        "declared_attachment_evidence_sha256s": [],
        "declared_runtime_sha256s": [],
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
            "file_id_envs": [],
            "attachment_evidence_sha256_envs": [],
            "runtime_file_path_envs": [],
            "runtime_file_sha256_envs": [],
            "synthetic_user_profile": None,
            "cohorts": [],
            "configured_question_answers": {},
            "question_answer_sources": {},
        },
        "case_identity": harness._case_identity(case),
        "case_contract": case_contract,
        "case_contract_sha256": harness._canonical_sha256(case_contract),
        "repetition": 1,
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
            "session_id": "00000000-0000-0000-0000-000000000001",
            "classifier_runs": [
                {
                    "message_id": "assistant-1",
                    "schema_version": 19,
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
                "file_id_envs": list(case.file_id_envs),
                "attachment_evidence_sha256_envs": list(
                    case.attachment_evidence_sha256_envs
                ),
                "runtime_file_path_envs": list(case.runtime_file_path_envs),
                "runtime_file_sha256_envs": list(case.runtime_file_sha256_envs),
                "synthetic_user_profile": case.synthetic_user_profile,
                "cohorts": list(case.cohorts),
                "configured_question_answers": (case.configured_question_answers or {}),
                "question_answer_sources": case.question_answer_sources or {},
            },
            "case_identity": harness._case_identity(case),
            "case_contract": case_contract,
            "case_contract_sha256": harness._canonical_sha256(case_contract),
            "session_id": "session-1",
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
                "version": 5,
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

    with raises(ValueError, match="version must be 5"):
        _battle_harness()._read_cases_file(cases_path)


def test_cases_file_rejects_duplicate_case_ids_and_prompts(tmp_path: Path) -> None:
    harness = _battle_harness()
    duplicate_cases = [
        {"id": "case-a", "prompt": "Build a report."},
        {"id": "case-b", "prompt": "Build a report."},
    ]
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps({"version": 5, "cases": duplicate_cases}), encoding="utf-8"
    )

    with raises(ValueError, match="duplicate prompt"):
        harness._read_cases_file(cases_path)

    duplicate_cases[1] = {"id": "case-a", "prompt": "Build another report."}
    cases_path.write_text(
        json.dumps({"version": 5, "cases": duplicate_cases}), encoding="utf-8"
    )

    with raises(ValueError, match="duplicate case id"):
        harness._read_cases_file(cases_path)


def test_cases_file_rejects_misspelled_evidence_posture_key(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": 5,
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
    assert summary["fixture_skipped_observation_count"] == 1
    assert summary["required_fixture_skipped_observation_count"] == 1
    assert summary["sentinel_verdict"] is None


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
        file_ids=("file-1",),
        attachment_evidence_sha256_envs=("FIXTURE_EVIDENCE_SHA256",),
    )
    bundle = _complete_live_case_bundle(harness, case)
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
        {**valid_bundle, "skipped": True},
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

    result = harness._suite_result(bundle, bundle_path)

    assert result["observation_status"] == "invalid_evidence"
    assert result["expectation_verdict"] == "not_evaluated"
    assert result["evidence_valid"] is False
    assert result["evidence_failed_check_count"] > 0


def test_release_thresholds_are_predeclared_and_compared(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    gate = harness.ReleaseGate(
        required_case_ids=("required-positive",),
        thresholds=harness.ReleaseThresholds(
            max_required_case_errors=0,
            max_required_quality_failures=0,
            max_required_skips=0,
        ),
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
        bundle = _complete_live_case_bundle(
            harness,
            selected_case,
        )
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
        release_gate=gate,
    )

    assert exit_code == 0
    suite_dir = next(tmp_path.glob("ai-builder-api-battle-suite-*"))
    assert suite_dir.stat().st_mode & 0o777 == 0o700
    manifest = json.loads((suite_dir / "release-manifest.json").read_text())
    assert manifest["thresholds"] == {
        "max_required_case_errors": 0,
        "max_required_quality_failures": 0,
        "max_required_skips": 0,
    }
    summary = json.loads((suite_dir / "suite-summary.json").read_text())
    assert all(check["passed"] for check in summary["sentinel_threshold_checks"])
    assert summary["sentinel_verdict"] == "pass"
    assert "release_verdict" not in summary
    assert summary["expectation_failed_observation_count"] == 0
    assert summary["required_expectation_failed_observation_count"] == 0
    assert summary["invalid_evidence_observation_count"] == 1
    assert summary["required_invalid_evidence_observation_count"] == 0
    benchmark_result = next(
        result
        for result in summary["results"]
        if result["case_id"] == "benchmark-negative"
    )
    assert benchmark_result["observation_status"] == "invalid_evidence"
    assert benchmark_result["expectation_verdict"] == "not_evaluated"
    assert summary["sentinel_gate_scope"] == {
        "case_count": 1,
        "selected_case_count": 2,
        "observation_count": 1,
        "selected_observation_count": 2,
        "case_ids": ["required-positive"],
    }
    assert summary["artifact_mode"] == "live_execution_summary"


def test_release_gate_requires_explicit_model_before_execution(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    case = harness.BattleCase(
        case_id="required-model",
        prompt="Build it.",
        required=True,
    )
    gate = harness.ReleaseGate(
        required_case_ids=(case.case_id,),
        thresholds=harness.ReleaseThresholds(
            max_required_case_errors=0,
            max_required_quality_failures=0,
            max_required_skips=0,
        ),
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
            release_gate=gate,
        )

    assert executed is False
    assert list(tmp_path.iterdir()) == []

    failed_checks = harness._evaluate_release_thresholds(
        gate.thresholds,
        required_case_error_count=0,
        required_quality_failure_run_count=1,
        required_skipped_run_count=0,
    )
    assert (
        next(
            check
            for check in failed_checks
            if check["name"] == "max_required_quality_failures"
        )["passed"]
        is False
    )


def test_release_receipt_version_defaults_to_v3_and_rejects_other_versions(
    tmp_path: Path,
) -> None:
    harness = _battle_harness()
    thresholds = harness.ReleaseThresholds(
        max_required_case_errors=0,
        max_required_quality_failures=0,
        max_required_skips=0,
    )

    gate = harness.ReleaseGate(
        required_case_ids=("required-case",),
        thresholds=thresholds,
    )

    assert gate.artifact_schema_version == "ai-builder-live-release.v3"
    assert gate.artifact_schema_version == harness.SUPPORTED_RECEIPT_ARTIFACT_VERSION

    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            {
                "version": 5,
                "release_gate": {
                    "artifact_schema_version": "ai-builder-live-release.unsupported",
                    "require_clean_source": False,
                    "thresholds": {
                        "max_required_case_errors": 0,
                        "max_required_quality_failures": 0,
                        "max_required_skips": 0,
                    },
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
        harness._read_release_gate(cases_path, cases=cases)


def test_suite_receipts_preserve_canonical_case_identity_for_every_outcome(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
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
            case_id="skipped-case",
            prompt="Build the skipped case.",
            complexity="easy",
            domain="municipality_documents",
            cohorts=("attachments",),
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
    monkeypatch.setattr(
        harness,
        "_missing_file_id_envs",
        lambda case, _args: ("MISSING_FILE_ID",)
        if case.case_id == "skipped-case"
        else (),
    )

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
    assert results_by_case_id["skipped-case"]["skipped"] is True
    assert results_by_case_id["skipped-case"]["observation_status"] == "fixture_skip"
    assert results_by_case_id["skipped-case"]["expectation_verdict"] == "not_evaluated"
    assert results_by_case_id["skipped-case"]["error"] is None
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
        assert (
            result["bundle_sha256"]
            == hashlib.sha256(bundle_path.read_bytes()).hexdigest()
        )
        assert "bundle_path" not in result
    assert summary["outcome_class_summary"]["counts"] == {
        "execution_failure": 1,
        "fixture_skip": 1,
        "unclassified": 1,
    }
    assert summary["receipt_integrity"]["status"] == "complete"
    assert summary["sentinel_verdict"] is None
    assert summary["artifact_mode"] == "live_execution_exploratory_summary"
    assert summary["observation_summary"] == {
        "status_counts": {
            "completed": 1,
            "execution_failure": 1,
            "fixture_skip": 1,
        },
        "verdict_counts": {"not_evaluated": 2, "pass": 1},
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
            "file_id_envs": ("ENEO_TEST_SOURCE_FILE_ID",),
            "attachment_evidence_sha256_envs": ("ENEO_TEST_EVIDENCE_SHA256",),
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
    assert contract_hash(file_id_envs=("ENEO_OTHER_FIXTURE_FILE_ID",)) != baseline
    assert (
        contract_hash(attachment_evidence_sha256_envs=("ENEO_OTHER_FIXTURE_SHA256",))
        != baseline
    )
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
    release_gate = harness.ReleaseGate(
        required_case_ids=(case.case_id,),
        thresholds=harness.ReleaseThresholds(
            max_required_case_errors=0,
            max_required_quality_failures=0,
            max_required_skips=0,
        ),
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
        release_gate=release_gate,
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
    gate = harness.ReleaseGate(
        required_case_ids=(case.case_id,),
        thresholds=harness.ReleaseThresholds(
            max_required_case_errors=0,
            max_required_quality_failures=0,
            max_required_skips=0,
        ),
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
        release_gate=gate,
    )

    assert exit_code == 1
    summary = json.loads(
        next(
            tmp_path.glob("ai-builder-api-battle-suite-*/suite-summary.json")
        ).read_text()
    )
    assert summary["sentinel_verdict"] == "fail"
    assert summary["suite_identity_failed_check_count"] == 5
    assert all(
        check["passed"] is False for check in summary["release_identity_recheck_checks"]
    )


def test_required_identity_drift_does_not_become_builder_expectation_failure(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    harness = _battle_harness()
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
    release_gate = harness.ReleaseGate(
        required_case_ids=(case.case_id,),
        thresholds=harness.ReleaseThresholds(
            max_required_case_errors=0,
            max_required_quality_failures=0,
            max_required_skips=0,
        ),
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
        release_gate=release_gate,
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


def test_release_gate_rejects_dirty_source_before_creating_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    gate = harness.ReleaseGate(
        required_case_ids=("required-positive",),
        thresholds=harness.ReleaseThresholds(
            max_required_case_errors=0,
            max_required_quality_failures=0,
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


def test_observation_input_identity_verifies_evidence_text_and_runtime_file_bytes(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    harness = _battle_harness()
    runtime_path = tmp_path / "source.pdf"
    runtime_path.write_bytes(b"municipal fixture bytes")
    runtime_sha256 = hashlib.sha256(runtime_path.read_bytes()).hexdigest()
    extracted_evidence_sha256 = "a" * 64
    monkeypatch.setenv("FIXTURE_EVIDENCE_SHA256", extracted_evidence_sha256)
    monkeypatch.setenv("FIXTURE_FILE_SHA256", runtime_sha256)
    case = harness.BattleCase(
        case_id="fixture-identity",
        prompt="Build it.",
        file_id_envs=("FIXTURE_FILE_ID",),
        attachment_evidence_sha256_envs=("FIXTURE_EVIDENCE_SHA256",),
        runtime_file_path_envs=("FIXTURE_PATH",),
        runtime_file_sha256_envs=("FIXTURE_FILE_SHA256",),
    )
    diagnostics = {
        "classifier_runs": [
            {
                "source_inventory": [
                    {
                        "kind": "uploaded_file",
                        "file_id": "file-1",
                        "source_sha256": extracted_evidence_sha256,
                    }
                ]
            }
        ]
    }
    runtime_evidence = {
        "run_contract": {
            "steps_requiring_input": [{"step_id": "reader-step"}],
        },
        "uploaded_files": [{"id": "runtime-file-1"}],
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
                                "checksum": runtime_sha256,
                                "byte_size": len(runtime_path.read_bytes()),
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
        attached_file_ids=("file-1",),
        classifier_diagnostics=diagnostics,
        runtime_evidence=runtime_evidence,
    )
    assert identity["verified"] is True
    assert len(identity["sha256"]) == 64

    runtime_path.write_bytes(b"changed after upload")
    stable_consumed_identity = harness._observation_input_identity(
        case=case,
        attached_file_ids=("file-1",),
        classifier_diagnostics=diagnostics,
        runtime_evidence=runtime_evidence,
    )
    assert stable_consumed_identity == identity

    diagnostics["classifier_runs"][0]["source_inventory"][0]["source_sha256"] = "0" * 64
    mismatch = harness._observation_input_identity(
        case=case,
        attached_file_ids=("file-1",),
        classifier_diagnostics=diagnostics,
        runtime_evidence=runtime_evidence,
    )
    assert mismatch["verified"] is False
    assert mismatch["mismatches"] == ["attachment_evidence_content"]

    diagnostics["classifier_runs"][0]["source_inventory"][0]["source_sha256"] = (
        extracted_evidence_sha256
    )
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
        attached_file_ids=("file-1",),
        classifier_diagnostics=diagnostics,
        runtime_evidence=runtime_evidence,
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
    release_gate = harness._read_release_gate(cases_path, cases=cases)
    by_id = {case.case_id: case for case in cases}

    assert release_gate.artifact_schema_version == "ai-builder-live-release.v3"
    assert release_gate.require_clean_source is True
    assert release_gate.thresholds == harness.ReleaseThresholds(
        max_required_case_errors=0,
        max_required_quality_failures=0,
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
        "first_pass_semantic",
    } <= required_dimensions
    assert all(by_id[case_id].required for case_id in release_gate.required_case_ids)
    assert "complex_authoring_spec_first_pass" in release_gate.required_case_ids

    review_case = by_id["ordinary_language_human_review_policy"]
    assert review_case.apply_plan is True
    assert review_case.execute_flow is False
    assert review_case.expected is not None
    assert review_case.expected["expected_review_policy"]["mode"] == "view"

    six_file_case = by_id["six_file_document_report_release_gate"]
    assert six_file_case.apply_plan is True
    assert six_file_case.execute_flow is True
    assert len(six_file_case.file_id_envs) == 6
    assert len(six_file_case.attachment_evidence_sha256_envs) == 6
    assert len(six_file_case.runtime_file_path_envs) == 6
    assert len(six_file_case.runtime_file_sha256_envs) == 6
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
                "version": 5,
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
    assert sum(bool(case.file_id_envs) for case in cases) == 3
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

    assert summary == {
        "counts": {
            "clarification_stop_intended": 2,
            "stalled_unanswered_question": 1,
        },
        "by_cohort": {
            "municipal": {
                "clarification_stop_intended": 2,
                "stalled_unanswered_question": 1,
            },
            "single_missing_dimension": {"clarification_stop_intended": 1},
        },
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
        },
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
    assert all(check["passed"] for check in summary["sentinel_threshold_checks"])


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
                "version": 5,
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
        "version": 5,
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


def test_evaluator_identity_carries_relevance_semantics_version() -> None:
    harness = _battle_harness()
    assert harness.QUESTION_RELEVANCE_SEMANTICS_VERSION == 2
    assert harness.SUPPORTED_CASES_FILE_VERSION == 5
    identity = harness._suite_evaluator_identity(
        release_identity={},
        run_context={},
        expected_observations=[],
    )
    assert identity["question_relevance_semantics_version"] == 2


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

    observed, observations, missing, count = (
        harness._planner_model_evidence_from_interactions(interactions)
    )

    assert observed == ["openai/gpt"]
    assert [o["interaction_index"] for o in observations] == [1]
    assert missing == [3]
    assert count == 3
