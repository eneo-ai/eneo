from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from intric.flows.enums import FlowStepAttemptStatus, FlowStepResultStatus
from intric.flows.flow import (
    FlowRun,
    FlowRunStatus,
    FlowStepAttempt,
    FlowStepResult,
    FlowVersion,
)
from intric.flows.flow_run_evidence import (
    build_debug_export,
    normalize_debug_step,
    parse_step_order,
)
from intric.flows.flow_run_evidence_bundle import (
    build_evidence_bundle,
    redact_evidence_bundle,
)
from intric.flows.flow_run_export_json import render_evidence_json_export
from intric.flows.flow_run_provenance import (
    normalize_attempt_provenance,
    normalize_rag_payload,
)


def test_parse_step_order_handles_strings_and_bools():
    assert parse_step_order(" 7 ") == 7
    assert parse_step_order(True, default=9) == 9
    assert parse_step_order("bad", default=5) == 5
    assert parse_step_order(None, default=3) == 3
    assert parse_step_order(7.2, default=4) == 4


def test_normalize_debug_step_uses_snapshot_mcp_fields_and_rag_metadata():
    step = normalize_debug_step(
        {
            "step_id": "step-1",
            "step_order": 1,
            "assistant_id": "assistant-1",
            "input_source": "flow_input",
            "input_type": "text",
            "output_mode": "pass_through",
            "output_type": "json",
            "mcp_policy": "inherit",
            "mcp_servers": [{"id": "server-1", "name": "Weather"}],
            "mcp_tools_enabled": [
                {"tool_id": "tool-1", "server_id": "server-1", "name": "forecast_tool"}
            ],
        },
        rag_metadata={"status": "success"},
    )

    assert step["mcp"]["servers"] == [{"id": "server-1", "name": "Weather"}]
    assert step["mcp"]["tools_enabled"] == [
        {"tool_id": "tool-1", "server_id": "server-1", "name": "forecast_tool"}
    ]
    assert step["rag"]["status"] == "success"
    assert step["rag"]["tracking"]["retrieval_tracked"] is True


def test_build_debug_export_reads_rag_metadata_from_typed_step_results():
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=2,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=2,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "step_order": 1,
                    "assistant_id": "assistant-1",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                }
            ]
        },
        created_at=now,
        updated_at=now,
    )
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={"rag": {"status": "success", "chunks_retrieved": 3}},
        effective_prompt=None,
        output_payload_json=None,
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )

    export = build_debug_export(run=run, version=version, step_results=[result])

    assert export["definition"]["steps_count"] == 1
    assert export["steps"][0]["rag"]["status"] == "success"
    assert export["steps"][0]["rag"]["chunks_retrieved"] == 3
    assert export["steps"][0]["rag"]["tracking"]["retrieval_tracked"] is True


def test_build_debug_export_handles_empty_steps():
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={"steps": []},
        created_at=now,
        updated_at=now,
    )

    export = build_debug_export(run=run, version=version, step_results=[])

    assert export["steps"] == []
    assert export["definition"]["steps_count"] == 0


def test_normalize_attempt_provenance_truncates_large_text_and_json_payloads():
    normalized = normalize_attempt_provenance(
        {
            "llm": {
                "effective_prompt": "x" * 20000,
                "tool_calls": {
                    "result": "y" * 20000,
                },
            }
        }
    )

    assert normalized is not None
    assert normalized.llm is not None
    assert normalized.llm.effective_prompt is not None
    assert normalized.llm.effective_prompt.truncated is True
    assert normalized.llm.effective_prompt.byte_size > 16000
    assert normalized.llm.effective_prompt.sha256 is not None
    assert normalized.llm.tool_calls is not None
    assert normalized.llm.tool_calls.truncated is True
    assert normalized.llm.tool_calls.sha256 is not None


def test_build_debug_export_adds_rag_source_names_and_run_summary() -> None:
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=2,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json=None,
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=2,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "step_order": 1,
                    "assistant_id": "assistant-1",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_mode": "pass_through",
                    "output_type": "json",
                    "mcp_policy": "inherit",
                }
            ]
        },
        created_at=now,
        updated_at=now,
    )
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={
            "rag": {
                "attempted": True,
                "status": "success",
                "source_ids": ["source-1", "source-2"],
                "source_ids_short": ["source-1", "source-2"],
                "references": [
                    {
                        "id": "source-1",
                        "id_short": "source-1",
                        "title": "Knowledge A",
                        "matched_chunk_count": 1,
                        "best_score": 0.8,
                        "chunks": [],
                    },
                    {
                        "id": "source-2",
                        "id_short": "source-2",
                        "title": None,
                        "matched_chunk_count": 1,
                        "best_score": 0.7,
                        "chunks": [],
                    },
                ],
            }
        },
        effective_prompt=None,
        output_payload_json=None,
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )

    export = build_debug_export(run=run, version=version, step_results=[result])

    assert export["run"]["summary"]["steps_count"] == 1
    assert export["run"]["summary"]["completed_steps"] == 1
    assert export["steps"][0]["rag"]["source_names"] == ["Knowledge A"]
    assert export["steps"][0]["rag"]["has_named_sources"] is True


def test_normalize_rag_payload_adds_prompt_context_display_names_and_usage_state() -> (
    None
):
    normalized = normalize_rag_payload(
        {
            "tracking": {
                "retrieval_tracked": True,
                "prompt_context_inclusion_tracked": True,
                "citation_tracked": False,
                "material_influence_tracked": False,
            },
            "prompt_context": {
                "tracked": True,
                "included_source_ids": ["source-1"],
                "included_groups": [
                    {
                        "source_id": "source-1",
                        "source_title": "https://kunskap.example.se/beslut/underlag",
                        "chunk_count": 2,
                    }
                ],
            },
            "references": [
                {
                    "id": "source-1",
                    "title": "https://kunskap.example.se/beslut/underlag",
                }
            ],
        }
    )

    assert normalized is not None
    assert normalized["references"][0]["usage_state"] == "inserted_into_prompt"
    assert normalized["prompt_context"]["included_source_titles"] == [
        "https://kunskap.example.se/beslut/underlag"
    ]
    assert normalized["prompt_context"]["included_source_display_names"] == [
        "kunskap.example.se/beslut/underlag"
    ]


def test_normalize_rag_payload_derives_reference_match_count_from_display_chunks() -> (
    None
):
    normalized = normalize_rag_payload(
        {
            "references": [
                {
                    "id": "source-1",
                    "id_short": "source-1",
                    "chunks": [
                        {"chunk_no": 1, "score": 0.9, "snippet": "First snippet"},
                        {"chunk_no": 2, "score": 0.7, "snippet": ""},
                        {"chunk_no": 3, "score": 0.6, "snippet": "Third snippet"},
                    ],
                }
            ]
        }
    )

    assert normalized is not None
    reference = normalized["references"][0]
    assert reference["matched_chunk_count"] == 2


def test_render_evidence_json_export_adds_manifest_and_summary() -> None:
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json={"authorization": "Bearer secret-token"},
        output_payload_json={"text": "done"},
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={"steps": []},
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[],
            step_attempts=[],
        )
    )
    export = render_evidence_json_export(bundle=bundle)

    assert export["manifest"]["run_id"] == str(run.id)
    assert export["manifest"]["trace_id"] == str(run.trace_id)
    assert export["manifest"]["redaction_applied"] is True
    assert export["summary"]["status"] == "completed"
    assert export["summary"]["steps_count"] == 0
    assert export["summary"]["artifacts_count"] == 0
    assert export["redaction"]["applied"] is True
    assert export["redaction"]["policy_version"] == "flow-evidence-redaction.v3"
    assert export["redaction"]["masked_fields_count"] >= 1
    assert (
        "bundle.run.input_payload_json.authorization"
        in export["redaction"]["masked_paths"]
    )
    assert export["redaction"]["masked_fields"][0]["reason"] in {
        "sensitive_key",
        "bearer_token",
    }

    serialized_bundle = json.dumps(
        bundle.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert export["content_hash"] == hashlib.sha256(serialized_bundle).hexdigest()


def test_render_evidence_json_export_adds_human_readable_rag_and_artifact_summaries() -> (
    None
):
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={
            "artifacts": [
                {
                    "file_id": str(uuid4()),
                    "file_name": "beslut-underlag.pdf",
                }
            ]
        },
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "metadata_json": {
                "ai_builder": {
                    "origin": {
                        "builder_session_id": "builder-session-123",
                    }
                }
            },
            "steps": [],
        },
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[],
            step_attempts=[],
        )
    )
    bundle = replace(
        bundle,
        step_attempts=(
            {
                "provenance_json": {
                    "rag": {
                        "references": [
                            {
                                "id": "source-1",
                                "title": "https://psykologi.se/psykologilexikon/affekt/",
                                "id_short": "source-1",
                                "chunks": [],
                                "matched_chunk_count": 1,
                                "best_score": 0.9,
                            }
                        ],
                        "source_names": [
                            "https://psykologi.se/psykologilexikon/affekt/"
                        ],
                    }
                }
            },
        ),
    )

    export = render_evidence_json_export(bundle=bundle)

    assert export["summary"]["artifact_names"] == ["beslut-underlag.pdf"]
    assert export["summary"]["rag_source_names"] == [
        "https://psykologi.se/psykologilexikon/affekt/"
    ]
    assert export["summary"]["rag_source_display_names"] == [
        "psykologi.se/psykologilexikon/affekt"
    ]
    assert (
        export["manifest"]["redaction_policy_version"] == "flow-evidence-redaction.v3"
    )
    assert (
        export["bundle"]["definition_snapshot"]["metadata_json"]["ai_builder"][
            "origin"
        ]["builder_session_id"]
        == "builder-session-123"
    )
    assert (
        "bundle.definition_snapshot.metadata_json.ai_builder.origin.builder_session_id"
        not in export["redaction"]["masked_paths"]
    )


def test_render_evidence_json_export_adds_rag_source_details_and_step_overview() -> (
    None
):
    started_at = datetime.now(timezone.utc)
    finished_at = started_at
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=3,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={
            "text": "Beslut till underlag klart.",
            "artifacts": [
                {
                    "file_id": str(uuid4()),
                    "file_name": "beslut-underlag.pdf",
                }
            ],
        },
        error_message=None,
        job_id=None,
        created_at=started_at,
        updated_at=finished_at,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=3,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "assistant_id": "assistant-1",
                    "step_order": 1,
                    "user_description": "Sammanfatta underlaget",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                }
            ]
        },
        created_at=started_at,
        updated_at=finished_at,
    )
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={
            "input_source": "flow_input",
            "used_question_binding": False,
            "legacy_prompt_binding_used": False,
            "runtime_input": {
                "file_ids": [str(uuid4())],
                "files_count": 1,
                "files": [
                    {
                        "id": "input-file-1",
                        "name": "underlag.pdf",
                        "checksum": "input-checksum",
                        "size": 2048,
                        "mimetype": "application/pdf",
                        "file_type": "document",
                        "text_length": 1024,
                        "has_text": True,
                        "has_transcription": False,
                    }
                ],
                "total_file_size": 2048,
                "extracted_text_length": 1024,
                "input_format": "document",
                "capture_mode": "flow_input_files",
            },
        },
        effective_prompt=None,
        output_payload_json={
            "text": "Beslut till underlag klart.",
            "artifacts": [
                {
                    "file_id": str(uuid4()),
                    "file_name": "beslut-underlag.pdf",
                    "checksum": "artifact-checksum",
                    "file_type": "document",
                    "mimetype": "application/pdf",
                    "size": 4096,
                }
            ],
        },
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=started_at,
        updated_at=finished_at,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=result.step_id,
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        error_message=None,
        requested_model="gpt-4.1-mini",
        response_model="gpt-4.1-mini",
        provider="openai",
        finish_reason="stop",
        provider_response_id="resp_123",
        num_tokens_input=12,
        num_tokens_output=8,
        provenance_json={
            "rag": {
                "status": "success",
                "tracking": {
                    "retrieval_tracked": True,
                    "prompt_context_inclusion_tracked": True,
                    "citation_tracked": False,
                    "material_influence_tracked": False,
                    "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                },
                "prompt_context": {
                    "tracked": True,
                    "version": 2,
                    "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                    "raw_source_count": 1,
                    "raw_chunk_count": 1,
                    "included_source_count": 1,
                    "not_included_source_count": 0,
                    "included_chunk_count": 1,
                    "knowledge_tokens": 144,
                    "truncated_by_token_budget": False,
                    "included_source_ids": ["source-1"],
                    "not_included_source_ids": [],
                    "included_source_titles": ["Beslut till underlag"],
                    "included_groups": [
                        {
                            "source_id": "source-1",
                            "source_id_short": "source-1",
                            "source_title": "Beslut till underlag",
                            "start_chunk": 1,
                            "end_chunk": 1,
                            "chunk_count": 1,
                            "relevance_score": 0.82,
                        }
                    ],
                },
                "references": [
                    {
                        "id": "source-1",
                        "id_short": "source-1",
                        "title": "Beslut till underlag",
                        "source_title": "Beslut till underlag",
                        "source_url": "https://kunskap.example.se/beslut/underlag",
                        "source_kind": "website",
                        "source_container_kind": "website",
                        "source_container_name": "Kunskapsbanken",
                        "source_container_id": "website-1",
                        "usage_state": "inserted_into_prompt",
                        "matched_chunk_count": 1,
                        "best_score": 0.82,
                        "chunks": [],
                    }
                ],
                "unique_sources": 1,
                "source_names": ["Beslut till underlag"],
                "source_display_names": ["Beslut till underlag"],
                "reference_metadata_status": "success",
                "references_truncated": False,
            }
        },
        started_at=started_at,
        finished_at=finished_at,
        created_at=started_at,
        updated_at=finished_at,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[attempt],
        )
    )

    export = render_evidence_json_export(bundle=bundle)

    assert export["summary"]["final_output"]["kind"] == "mixed"
    assert export["summary"]["final_output"]["artifact_names"] == [
        "beslut-underlag.pdf"
    ]
    assert (
        export["summary"]["final_output"]["artifact_details"][0]["checksum"]
        == "artifact-checksum"
    )
    assert (
        export["summary"]["final_output"]["text_preview"]["preview"]
        == "Beslut till underlag klart."
    )
    assert export["summary"]["rag_sources"][0]["source_kind"] == "website"
    assert (
        export["summary"]["rag_sources"][0]["source_container_name"] == "Kunskapsbanken"
    )
    assert (
        export["summary"]["rag_sources"][0]["source_container_display_name"]
        == "Kunskapsbanken"
    )
    assert export["summary"]["rag_sources"][0]["usage_state"] == "inserted_into_prompt"
    assert export["summary"]["rag_usage_tracking"]["retrieval_tracked"] is True
    assert (
        export["summary"]["rag_usage_tracking"]["prompt_context_inclusion_tracked"]
        is True
    )
    assert export["summary"]["rag_usage_tracking"]["citation_tracked"] is False
    assert (
        export["summary"]["step_overview"][0]["user_description"]
        == "Sammanfatta underlaget"
    )
    assert export["summary"]["step_overview"][0]["knowledge_sources_count"] == 1
    assert (
        export["summary"]["step_overview"][0]["knowledge_retrieval"]["status"]
        == "success"
    )
    assert (
        export["summary"]["step_overview"][0]["knowledge_retrieval"]["unique_sources"]
        == 1
    )
    assert export["summary"]["step_overview"][0]["knowledge_retrieval"][
        "prompt_context"
    ]["included_source_display_names"] == ["Beslut till underlag"]
    assert export["summary"]["step_overview"][0]["artifact_names"] == [
        "beslut-underlag.pdf"
    ]
    assert (
        export["summary"]["step_overview"][0]["artifact_details"][0]["checksum"]
        == "artifact-checksum"
    )
    assert export["summary"]["step_overview"][0]["input_lineage"][
        "runtime_file_names"
    ] == ["underlag.pdf"]
    assert export["summary"]["step_overview"][0]["input_lineage"][
        "runtime_file_checksums"
    ] == ["input-checksum"]
    assert (
        export["summary"]["step_overview"][0]["output_summary"]["preview"]
        == "Beslut till underlag klart."
    )


def test_render_evidence_json_export_adds_step_input_lineage_for_upstream_bindings() -> (
    None
):
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=2,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "klart"},
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=2,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "assistant_id": "assistant-1",
                    "step_order": 1,
                    "user_description": "Extrahera text",
                    "input_source": "flow_input",
                    "input_type": "document",
                    "output_type": "text",
                },
                {
                    "step_id": "step-2",
                    "assistant_id": "assistant-2",
                    "step_order": 2,
                    "user_description": "Analysera dokumentet",
                    "input_source": "previous_step",
                    "input_type": "text",
                    "output_type": "json",
                    "input_bindings": {
                        "question": "Analysera {{ step_1.output.text }} med fokus på {{ step_input.text }}"
                    },
                },
            ]
        },
        created_at=now,
        updated_at=now,
    )
    step_one = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={
            "input_source": "flow_input",
            "used_question_binding": False,
            "legacy_prompt_binding_used": False,
            "runtime_input": {
                "file_ids": ["input-file-1"],
                "files_count": 1,
                "files": [
                    {
                        "id": "input-file-1",
                        "name": "underlag.pdf",
                        "checksum": "input-checksum",
                        "size": 100,
                        "mimetype": "application/pdf",
                        "file_type": "document",
                        "text_length": 50,
                        "has_text": True,
                        "has_transcription": False,
                    }
                ],
                "total_file_size": 100,
                "extracted_text_length": 50,
                "input_format": "document",
                "capture_mode": "flow_input_files",
            },
        },
        effective_prompt=None,
        output_payload_json={"text": "Extraherad text"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )
    step_two = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=2,
        assistant_id=uuid4(),
        input_payload_json={
            "input_source": "previous_step",
            "used_question_binding": True,
            "legacy_prompt_binding_used": False,
            "runtime_input": {
                "file_ids": ["input-file-2"],
                "files_count": 1,
                "files": [
                    {
                        "id": "input-file-2",
                        "name": "frågor.txt",
                        "checksum": "question-checksum",
                        "size": 80,
                        "mimetype": "text/plain",
                        "file_type": "text",
                        "text_length": 30,
                        "has_text": True,
                        "has_transcription": False,
                    }
                ],
                "total_file_size": 80,
                "extracted_text_length": 30,
                "input_format": "document",
                "capture_mode": "runtime_input",
            },
        },
        effective_prompt=None,
        output_payload_json={"structured": {"ok": True}},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[step_one, step_two],
            step_attempts=[],
        )
    )

    export = render_evidence_json_export(bundle=bundle)

    lineage = export["summary"]["step_overview"][1]["input_lineage"]
    assert lineage["input_source"] == "previous_step"
    assert lineage["uses_runtime_input"] is True
    assert lineage["runtime_file_names"] == ["frågor.txt"]
    assert lineage["runtime_file_checksums"] == ["question-checksum"]
    assert lineage["upstream_step_orders"] == [1]
    assert lineage["upstream_step_labels"] == ["Extrahera text"]
    assert lineage["question_binding_references_runtime_input"] is True
    assert lineage["question_binding_expressions"] == [
        "step_1.output.text",
        "step_input.text",
    ]


def test_render_evidence_json_export_adds_fallback_container_display_name_and_model_default_semantics() -> (
    None
):
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "klart"},
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={"steps": []},
        created_at=now,
        updated_at=now,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        error_message=None,
        requested_model="gpt-5.4-nano",
        response_model="gpt-5.4-nano",
        provider="openai",
        finish_reason="stop",
        provider_response_id=None,
        num_tokens_input=1,
        num_tokens_output=1,
        provenance_json={
            "llm": {
                "model_parameters": {
                    "model_id": str(uuid4()),
                    "provider": "openai",
                    "model_name": "gpt-5.4-nano",
                    "temperature": None,
                    "reasoning_effort": None,
                    "verbosity": None,
                    "parameter_semantics": {
                        "temperature": {"mode": "model_default"},
                        "reasoning_effort": {"mode": "model_default"},
                        "verbosity": {"mode": "model_default"},
                    },
                }
            },
            "rag": {
                "status": "success",
                "references": [
                    {
                        "id": "source-1",
                        "title": "https://psykologi.se/terapi/psykoanalys/",
                        "source_url": "https://psykologi.se/terapi/psykoanalys/",
                        "source_kind": "website",
                        "source_container_kind": "website",
                        "source_container_id": "website-1",
                        "usage_state": "retrieved_candidate",
                        "chunks": [],
                        "matched_chunk_count": 1,
                        "best_score": 0.8,
                    }
                ],
            },
        },
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )
    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[],
            step_attempts=[attempt],
        )
    )

    export = render_evidence_json_export(bundle=bundle)

    assert export["summary"]["rag_sources"][0]["source_container_name"] is None
    assert (
        export["summary"]["rag_sources"][0]["source_container_display_name"]
        == "psykologi.se"
    )
    llm = export["bundle"]["step_attempts"][0]["provenance_json"]["llm"][
        "model_parameters"
    ]
    assert llm["temperature"] is None
    assert llm["reasoning_effort"] is None
    assert llm["verbosity"] is None
    assert llm["parameter_semantics"]["temperature"]["mode"] == "model_default"


def test_render_evidence_json_export_adds_citation_sidecars_and_prompt_context_summary() -> (
    None
):
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={
            "text": 'Slutsats med kallor <inref id="11111111"/><inref id="aaaaaaaa"/>',
            "structured": {"summary": 'Detta styrks av kalla <inref id="22222222"/>'},
        },
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "assistant_id": "assistant-1",
                    "step_order": 1,
                    "user_description": "Analysera underlaget",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "json",
                }
            ]
        },
        created_at=now,
        updated_at=now,
    )
    source_one = "11111111-1111-1111-1111-111111111111"
    source_two = "22222222-2222-2222-2222-222222222222"
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt=None,
        output_payload_json={
            "text": 'Stegsvar <inref id="11111111"/>',
            "structured": {"note": 'Komplettering <inref id="aaaaaaaa"/>'},
        },
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=result.step_id,
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        error_message=None,
        requested_model="gpt-5.4-nano",
        response_model="gpt-5.4-nano",
        provider="openai",
        finish_reason="stop",
        provider_response_id="resp_123",
        num_tokens_input=10,
        num_tokens_output=12,
        provenance_json={
            "rag": {
                "status": "success",
                "tracking": {
                    "retrieval_tracked": True,
                    "prompt_context_inclusion_tracked": True,
                    "citation_tracked": False,
                    "material_influence_tracked": False,
                    "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                },
                "prompt_context": {
                    "tracked": True,
                    "included_source_count": 2,
                    "not_included_source_count": 0,
                    "included_chunk_count": 3,
                    "knowledge_tokens": 180,
                    "truncated_by_token_budget": False,
                    "included_source_ids": [source_one, source_two],
                    "included_source_titles": ["Kalla ett", "Kalla tva"],
                    "included_groups": [
                        {
                            "source_id": source_one,
                            "source_id_short": "11111111",
                            "source_title": "Kalla ett",
                            "start_chunk": 1,
                            "end_chunk": 2,
                            "chunk_count": 2,
                            "relevance_score": 1.0,
                        },
                        {
                            "source_id": source_two,
                            "source_id_short": "22222222",
                            "source_title": "Kalla tva",
                            "start_chunk": 1,
                            "end_chunk": 1,
                            "chunk_count": 1,
                            "relevance_score": 0.6,
                        },
                    ],
                },
                "references": [
                    {
                        "id": source_one,
                        "id_short": "11111111",
                        "title": "Kalla ett",
                        "usage_state": "inserted_into_prompt",
                        "matched_chunk_count": 2,
                        "best_score": 0.9,
                        "chunks": [],
                    },
                    {
                        "id": source_two,
                        "id_short": "22222222",
                        "title": "Kalla tva",
                        "usage_state": "inserted_into_prompt",
                        "matched_chunk_count": 1,
                        "best_score": 0.7,
                        "chunks": [],
                    },
                ],
            }
        },
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[attempt],
        )
    )
    export = render_evidence_json_export(bundle=bundle)

    prompt_context_summary = export["summary"]["step_overview"][0][
        "knowledge_retrieval"
    ]["prompt_context"]["summary"]
    assert prompt_context_summary["total_sources"] == 2
    assert prompt_context_summary["total_chunks"] == 3
    assert prompt_context_summary["truncated_by_token_budget"] is False
    assert prompt_context_summary["top_ranked_sources"][0]["source_id"] == source_one
    assert export["summary"]["citations"]["tracking_mode"] == "passive_inline_scan"
    assert export["summary"]["citations"]["citation_mode_requested"] is False
    assert export["summary"]["citations"]["citation_applicable"] is True
    assert export["summary"]["citations"]["citation_context_kind"] == "direct"
    assert export["summary"]["citations"]["citation_expected"] is False
    assert export["summary"]["citations"]["citation_observed"] is True
    assert (
        export["summary"]["citations"]["citation_compliance"]
        == "unknown_citation_ids_present"
    )
    assert export["summary"]["citations"]["cited_source_ids"] == [
        source_one,
        source_two,
    ]
    assert export["summary"]["citations"]["unknown_citation_ids"] == ["aaaaaaaa"]
    assert export["summary"]["citations"]["uncited_inserted_source_ids"] == []
    assert export["summary"]["step_overview"][0]["citations"]["cited_source_ids"] == [
        source_one
    ]
    assert export["summary"]["step_overview"][0]["citations"][
        "unknown_citation_ids"
    ] == ["aaaaaaaa"]
    assert (
        export["summary"]["step_overview"][0]["citations"]["citation_compliance"]
        == "unknown_citation_ids_present"
    )


def test_render_evidence_json_export_uses_provenance_citation_compliance_and_run_level_counts() -> (
    None
):
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "Ren sluttext utan taggar"},
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-1",
                    "assistant_id": "assistant-1",
                    "step_order": 1,
                    "user_description": "Analysera underlaget",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                    "output_config": {"citation_mode": "inline_inref_sidecar"},
                }
            ]
        },
        created_at=now,
        updated_at=now,
    )
    source_one = "11111111-1111-1111-1111-111111111111"
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=1,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt=None,
        output_payload_json={"text": "Ren sluttext utan taggar"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=result.step_id,
        step_order=1,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        error_message=None,
        requested_model="gpt-5.4-nano",
        response_model="gpt-5.4-nano",
        provider="openai",
        finish_reason="stop",
        provider_response_id="resp_123",
        num_tokens_input=10,
        num_tokens_output=12,
        provenance_json={
            "rag": {
                "status": "success",
                "tracking": {
                    "retrieval_tracked": True,
                    "prompt_context_inclusion_tracked": True,
                    "citation_tracked": False,
                    "material_influence_tracked": False,
                    "selection_basis": "semantic_search_ranked_chunks_grouped_by_source",
                },
                "prompt_context": {
                    "tracked": True,
                    "included_source_count": 1,
                    "not_included_source_count": 0,
                    "included_chunk_count": 1,
                    "knowledge_tokens": 80,
                    "truncated_by_token_budget": False,
                    "included_source_ids": [source_one],
                    "included_source_titles": ["Kalla ett"],
                    "included_groups": [],
                },
                "references": [
                    {
                        "id": source_one,
                        "id_short": "11111111",
                        "title": "Kalla ett",
                        "usage_state": "inserted_into_prompt",
                        "chunks": [],
                    }
                ],
            },
            "citations": {
                "tracking_mode": "inline_inref_required",
                "citation_tracked": True,
                "citation_mode_requested": True,
                "citation_applicable": True,
                "citation_context_kind": "direct",
                "citation_expected": True,
                "citation_observed": False,
                "citation_compliance": "missing_required_citations",
                "cited_source_ids": [],
                "cited_source_count": 0,
                "unknown_citation_ids": [],
                "uncited_inserted_source_ids": [source_one],
                "direct_available_source_ids": [source_one],
                "inherited_available_source_ids": [],
                "direct_cited_source_ids": [],
                "inherited_cited_source_ids": [],
                "upstream_grounded_step_orders": [],
            },
            "llm": {
                "raw_completion_text": "Ren sluttext utan taggar",
            },
        },
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[attempt],
        )
    )
    export = render_evidence_json_export(bundle=bundle)

    assert export["summary"]["citations"]["tracking_mode"] == "inline_inref_required"
    assert export["summary"]["citations"]["citation_mode_requested"] is True
    assert export["summary"]["citations"]["citation_applicable"] is True
    assert export["summary"]["citations"]["citation_context_kind"] == "direct"
    assert export["summary"]["citations"]["citation_expected"] is True
    assert export["summary"]["citations"]["citation_observed"] is False
    assert (
        export["summary"]["citations"]["citation_compliance"]
        == "missing_required_citations"
    )
    assert export["summary"]["citations"]["steps_with_citation_mode_requested"] == 1
    assert export["summary"]["citations"]["steps_with_citations_applicable"] == 1
    assert export["summary"]["citations"]["steps_with_direct_citation_context"] == 1
    assert export["summary"]["citations"]["steps_with_inherited_citation_context"] == 0
    assert export["summary"]["citations"]["steps_with_citations_expected"] == 1
    assert export["summary"]["citations"]["steps_with_citations_observed"] == 0
    assert export["summary"]["citations"]["steps_missing_required_citations"] == 1
    assert export["summary"]["citations"]["steps_with_unknown_citation_ids"] == 0
    assert (
        export["summary"]["step_overview"][0]["citations"]["citation_expected"] is True
    )
    assert (
        export["summary"]["step_overview"][0]["citations"]["citation_compliance"]
        == "missing_required_citations"
    )


def test_render_evidence_json_export_surfaces_inherited_citation_context() -> None:
    now = datetime.now(timezone.utc)
    run = FlowRun(
        id=uuid4(),
        flow_id=uuid4(),
        flow_version=1,
        user_id=uuid4(),
        tenant_id=uuid4(),
        trace_id=uuid4(),
        status=FlowRunStatus.COMPLETED,
        cancelled_at=None,
        input_payload_json=None,
        output_payload_json={"text": "Slutrapport"},
        error_message=None,
        job_id=None,
        created_at=now,
        updated_at=now,
    )
    version = FlowVersion(
        flow_id=run.flow_id,
        version=1,
        tenant_id=run.tenant_id,
        definition_checksum="checksum",
        definition_json={
            "steps": [
                {
                    "step_id": "step-2",
                    "assistant_id": "assistant-2",
                    "step_order": 2,
                    "user_description": "Grounded summary",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                },
                {
                    "step_id": "step-3",
                    "assistant_id": "assistant-3",
                    "step_order": 3,
                    "user_description": "Final report",
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "text",
                    "output_config": {"citation_mode": "inline_inref_sidecar"},
                },
            ]
        },
        created_at=now,
        updated_at=now,
    )
    source_one = "11111111-1111-1111-1111-111111111111"
    result = FlowStepResult(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=uuid4(),
        step_order=3,
        assistant_id=uuid4(),
        input_payload_json={},
        effective_prompt=None,
        output_payload_json={"text": "Slutrapport"},
        model_parameters_json=None,
        num_tokens_input=None,
        num_tokens_output=None,
        status=FlowStepResultStatus.COMPLETED,
        error_message=None,
        flow_step_execution_hash=None,
        tool_calls_metadata=None,
        created_at=now,
        updated_at=now,
    )
    attempt = FlowStepAttempt(
        id=uuid4(),
        flow_run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_id=result.step_id,
        step_order=3,
        attempt_no=1,
        celery_task_id=None,
        status=FlowStepAttemptStatus.COMPLETED,
        error_code=None,
        error_message=None,
        requested_model="gpt-5.4-nano",
        response_model="gpt-5.4-nano",
        provider="openai",
        finish_reason="stop",
        provider_response_id="resp_123",
        num_tokens_input=10,
        num_tokens_output=12,
        provenance_json={
            "citations": {
                "tracking_mode": "inline_inref_required",
                "citation_tracked": True,
                "citation_mode_requested": True,
                "citation_applicable": True,
                "citation_context_kind": "inherited",
                "citation_expected": True,
                "citation_observed": True,
                "citation_compliance": "observed",
                "cited_source_ids": [source_one],
                "cited_source_count": 1,
                "unknown_citation_ids": [],
                "uncited_inserted_source_ids": [],
                "direct_available_source_ids": [],
                "inherited_available_source_ids": [source_one],
                "direct_cited_source_ids": [],
                "inherited_cited_source_ids": [source_one],
                "upstream_grounded_step_orders": [2],
                "upstream_grounded_step_labels": ["Grounded summary"],
            },
            "llm": {
                "raw_completion_text": 'Slutrapport<inref id="11111111"/>',
            },
        },
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )

    bundle = redact_evidence_bundle(
        build_evidence_bundle(
            run=run,
            version=version,
            step_results=[result],
            step_attempts=[attempt],
        )
    )
    export = render_evidence_json_export(bundle=bundle)

    assert export["summary"]["citations"]["citation_context_kind"] == "inherited"
    assert export["summary"]["citations"]["inherited_cited_source_ids"] == [source_one]
    assert export["summary"]["citations"]["upstream_grounded_step_orders"] == [2]
    assert export["summary"]["citations"]["steps_with_inherited_citation_context"] == 1
    assert (
        export["summary"]["step_overview"][1]["citations"]["citation_context_kind"]
        == "inherited"
    )
