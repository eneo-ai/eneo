from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.authentication.principal_types import PrincipalType
from intric.flows.api.flow_assembler import FlowAssembler
from intric.flows.api.flow_models import (
    FlowOutputDelivery,
    FlowRunContractPublic,
    FlowRunCreateRequest,
    FlowRunDebugAttempt,
    FlowRunEvidenceResponse,
    FlowRunRerunInvalidatedStepPublic,
    FlowRunRerunOperationPublic,
    FlowStepAttemptPublic,
    FlowStepCreateRequest,
    FormFieldPublic,
    GraphEdge,
    GraphNode,
    GraphResponse,
    HttpTestRequest,
    HttpTestResponse,
    StepRunInput,
)
from intric.flows.domain.flow import FlowRunReviewCheckpoint
from intric.flows.enums import (
    FlowOutputMode,
    FlowOutputType,
    FlowRunRerunOperationStatus,
    FlowRunReviewCheckpointState,
    FlowStepAttemptStatus,
)
from intric.flows.flow_review_policy import FlowStepReviewMode
from intric.main.exceptions import BadRequestException


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "assistant_id": str(uuid4()),
        "step_order": 1,
        "input_source": "flow_input",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "json",
        "mcp_policy": "inherit",
    }
    payload.update(overrides)
    return payload


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_source", "banana"),
        ("input_type", "banana"),
        ("output_mode", "banana"),
        ("output_type", "banana"),
        ("mcp_policy", "banana"),
    ],
)
def test_flow_step_create_request_rejects_invalid_enum_values(
    field: str, value: str
) -> None:
    with pytest.raises(ValidationError):
        FlowStepCreateRequest.model_validate(_payload(**{field: value}))


def test_flow_step_create_request_accepts_template_fill_output_mode() -> None:
    request = FlowStepCreateRequest.model_validate(
        _payload(
            output_mode="template_fill",
            output_type="docx",
            output_config={
                "template_file_id": str(uuid4()),
                "bindings": {"title": "{{flow_input.title}}"},
            },
        )
    )

    assert request.output_mode.value == "template_fill"


def test_flow_run_create_request_parses_typed_step_inputs() -> None:
    step_id = uuid4()
    file_id = uuid4()

    request = FlowRunCreateRequest.model_validate(
        {
            "step_inputs": {
                str(step_id): {
                    "file_ids": [str(file_id)],
                }
            }
        }
    )

    assert request.step_inputs is not None
    assert isinstance(request.step_inputs[step_id], StepRunInput)
    assert request.step_inputs[step_id].file_ids == [file_id]


def test_flow_run_create_request_rejects_removed_top_level_file_ids() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        FlowRunCreateRequest.model_validate({"file_ids": [str(uuid4())]})

    assert exc_info.value.code == "flow_run_top_level_file_ids_not_supported"
    assert "run contract endpoint" in str(exc_info.value)
    assert exc_info.value.context == {
        "invalid_field": "file_ids",
        "expected_field": "step_inputs[step_id].file_ids",
        "contract_endpoint": "/api/v1/flows/{id}/run-contract/",
    }


def test_graph_response_parses_typed_nodes_and_edges() -> None:
    response = GraphResponse.model_validate(
        {
            "nodes": [
                {"id": "input", "label": "Input", "type": "input"},
                {
                    "id": "step-1",
                    "label": "Step 1",
                    "type": "llm",
                    "step_order": 1,
                    "input_source": "flow_input",
                    "input_type": "text",
                    "output_type": "json",
                    "output_mode": "pass_through",
                    "mcp_policy": "inherit",
                    "run_status": "completed",
                },
            ],
            "edges": [
                {
                    "source": "input",
                    "target": "step-1",
                    "kind": "flow_input",
                    "source_step_order": 0,
                    "target_step_order": 1,
                }
            ],
        }
    )

    assert isinstance(response.nodes[0], GraphNode)
    assert isinstance(response.edges[0], GraphEdge)
    assert response.nodes[1].run_status == "completed"


def test_flow_run_contract_public_parses_typed_form_fields() -> None:
    final_step_id = uuid4()
    contract = FlowRunContractPublic.model_validate(
        {
            "flow_id": str(uuid4()),
            "published_flow_version": 3,
            "final_output": {
                "step_id": str(final_step_id),
                "step_order": 3,
                "label": "Create Word report",
                "output_type": "docx",
                "output_mode": "pass_through",
                "delivery": "artifact",
                "output_contract": None,
            },
            "form_fields": [
                {
                    "name": "employee_name",
                    "type": "text",
                    "label": "Employee name",
                    "required": True,
                }
            ],
        }
    )

    assert isinstance(contract.form_fields[0], FormFieldPublic)
    assert contract.form_fields[0].name == "employee_name"
    assert contract.final_output is not None
    assert contract.final_output.step_id == final_step_id
    assert contract.final_output.output_type == FlowOutputType.DOCX
    assert contract.final_output.output_mode == FlowOutputMode.PASS_THROUGH
    assert contract.final_output.delivery == FlowOutputDelivery.ARTIFACT


def test_review_checkpoint_public_exposes_render_contract() -> None:
    now = datetime(2026, 3, 17, 10, 5, tzinfo=timezone.utc)
    checkpoint = FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=uuid4(),
        flow_id=uuid4(),
        flow_run_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
        revision=1,
        schema_version=1,
        original_payload_json={"transcription": "draft"},
        current_payload_json={"transcription": "draft"},
        step_label="Review transcription",
        review_mode=FlowStepReviewMode.EDIT,
        output_type=FlowOutputType.JSON,
        output_contract_json={
            "type": "object",
            "properties": {"transcription": {"type": "string"}},
        },
        requester_principal_type=PrincipalType.USER,
        requester_user_id=uuid4(),
        next_step_ids_json=[uuid4()],
        created_at=now,
        updated_at=now,
    )

    public = FlowAssembler().to_review_checkpoint_public(checkpoint)

    assert public.step_label == "Review transcription"
    assert public.review_mode == FlowStepReviewMode.EDIT
    assert public.output_type == FlowOutputType.JSON
    assert public.step_snapshot_available is True
    assert public.output_contract == {
        "type": "object",
        "properties": {"transcription": {"type": "string"}},
    }
    assert not hasattr(public, "output_contract_json")


def test_legacy_review_checkpoint_public_marks_missing_step_snapshot() -> None:
    now = datetime(2026, 3, 17, 10, 5, tzinfo=timezone.utc)
    checkpoint = FlowRunReviewCheckpoint(
        id=uuid4(),
        tenant_id=uuid4(),
        flow_id=uuid4(),
        flow_run_id=uuid4(),
        step_id=uuid4(),
        step_order=1,
        attempt_no=1,
        state=FlowRunReviewCheckpointState.AWAITING_REVIEW,
        revision=1,
        schema_version=1,
        original_payload_json={"text": "draft"},
        current_payload_json={"text": "draft"},
        requester_principal_type=PrincipalType.USER,
        requester_user_id=uuid4(),
        next_step_ids_json=[],
        created_at=now,
        updated_at=now,
    )

    public = FlowAssembler().to_review_checkpoint_public(checkpoint)

    assert public.step_snapshot_available is False
    assert public.step_label is None
    assert public.review_mode is None
    assert public.output_type is None
    assert public.output_contract is None


def test_flow_run_evidence_response_parses_typed_nested_models() -> None:
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    step_id = uuid4()
    step_result_id = uuid4()
    file_id = uuid4()
    attempt_id = uuid4()
    rerun_operation_id = uuid4()
    rerun_invalidated_step_id = uuid4()
    replacement_attempt_id = uuid4()
    review_checkpoint_id = uuid4()
    review_checkpoint_contract = {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
    }

    response = FlowRunEvidenceResponse.model_validate(
        {
            "run": {
                "id": str(run_id),
                "flow_id": str(flow_id),
                "flow_version": 2,
                "tenant_id": str(tenant_id),
                "trace_id": str(uuid4()),
                "status": "completed",
                "revision": 1,
                "created_at": "2026-03-20T12:00:00Z",
                "updated_at": "2026-03-20T12:05:00Z",
            },
            "definition_snapshot": {"steps": []},
            "step_results": [
                {
                    "id": str(step_result_id),
                    "flow_run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "tenant_id": str(tenant_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "status": "completed",
                    "effective_prompt": "Summarize the report",
                    "model_parameters_json": {"temperature": 0.2},
                    "flow_step_execution_hash": "abc123",
                    "created_at": "2026-03-20T12:00:01Z",
                    "updated_at": "2026-03-20T12:00:05Z",
                }
            ],
            "result_files": [
                {
                    "flow_run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "tenant_id": str(tenant_id),
                    "step_result_id": str(step_result_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "attempt_no": 1,
                    "file_id": str(file_id),
                    "ordinal": 0,
                    "source": "declared_artifact",
                    "name": "artifact.pdf",
                    "checksum": "artifact-checksum",
                    "size": 4096,
                    "mimetype": "application/pdf",
                    "file_type": "document",
                    "availability": "available",
                }
            ],
            "step_attempts": [
                {
                    "id": str(attempt_id),
                    "flow_run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "tenant_id": str(tenant_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "attempt_no": 1,
                    "status": "completed",
                    "started_at": "2026-03-20T12:00:00Z",
                    "finished_at": "2026-03-20T12:00:05Z",
                    "created_at": "2026-03-20T12:00:00Z",
                    "updated_at": "2026-03-20T12:00:05Z",
                }
            ],
            "rerun_operations": [
                {
                    "id": str(rerun_operation_id),
                    "tenant_id": str(tenant_id),
                    "flow_id": str(flow_id),
                    "flow_run_id": str(run_id),
                    "rerun_step_id": str(step_id),
                    "rerun_step_order": 1,
                    "root_attempt_no": 2,
                    "root_attempt_id": str(replacement_attempt_id),
                    "status": "completed",
                    "request_fingerprint": "rerun-fingerprint",
                    "expected_run_revision": 1,
                    "accepted_run_revision": 2,
                    "reason": "Reviewer corrected the step output.",
                    "input_payload_json": {"question": "Updated input"},
                    "step_inputs_json": {str(step_id): {"file_ids": []}},
                    "requested_by_principal_type": "user",
                    "requested_by_user_id": str(uuid4()),
                    "failure_code": None,
                    "failure_message": None,
                    "started_at": "2026-03-20T12:01:00Z",
                    "finished_at": "2026-03-20T12:01:05Z",
                    "created_at": "2026-03-20T12:01:00Z",
                    "updated_at": "2026-03-20T12:01:05Z",
                }
            ],
            "rerun_invalidated_steps": [
                {
                    "id": str(rerun_invalidated_step_id),
                    "operation_id": str(rerun_operation_id),
                    "tenant_id": str(tenant_id),
                    "flow_id": str(flow_id),
                    "flow_run_id": str(run_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "invalidation_order": 1,
                    "role": "root",
                    "dependency_sources_json": ["input_bindings.question"],
                    "prior_step_result_id": str(step_result_id),
                    "prior_attempt_id": str(attempt_id),
                    "new_attempt_no": 2,
                    "new_attempt_id": str(replacement_attempt_id),
                    "created_at": "2026-03-20T12:01:00Z",
                    "updated_at": "2026-03-20T12:01:05Z",
                }
            ],
            "review_checkpoints": [
                {
                    "id": str(review_checkpoint_id),
                    "tenant_id": str(tenant_id),
                    "flow_id": str(flow_id),
                    "flow_run_id": str(run_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "attempt_no": 1,
                    "state": "awaiting_review",
                    "revision": 1,
                    "schema_version": 1,
                    "original_payload_json": {"summary": "draft"},
                    "current_payload_json": {"summary": "reviewed"},
                    "step_label": "Review summary",
                    "review_mode": "edit",
                    "output_type": "json",
                    "step_snapshot_available": True,
                    "output_contract": review_checkpoint_contract,
                    "decision": None,
                    "next_step_ids": [],
                    "resume_key_present": False,
                    "requester_user_id": str(uuid4()),
                    "requester_principal_type": "user",
                    "decided_by_user_id": None,
                    "decided_by_principal_type": None,
                    "created_at": "2026-03-20T12:00:05Z",
                    "updated_at": "2026-03-20T12:00:05Z",
                }
            ],
            "debug_export": {
                "schema_version": "eneo.flow.debug-export.v2",
                "generated_at": "2026-03-20T12:05:00Z",
                "run": {
                    "run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "flow_version": 2,
                    "trace_id": str(uuid4()),
                    "status": "completed",
                },
                "definition": {
                    "flow_id": str(flow_id),
                    "version": 2,
                    "checksum": "abc",
                    "steps_count": 1,
                },
                "definition_snapshot": {"steps": []},
                "steps": [
                    {
                        "step_id": str(step_id),
                        "step_order": 1,
                        "assistant_id": str(uuid4()),
                        "io_types": {"input": "text", "output": "json"},
                        "input": {
                            "source": "flow_input",
                            "type": "text",
                            "contract": None,
                            "bindings": None,
                            "config": None,
                        },
                        "output": {
                            "mode": "pass_through",
                            "type": "json",
                            "contract": None,
                            "classification": None,
                            "config": None,
                        },
                        "mcp": {
                            "policy": "inherit",
                            "servers": [{"id": "server-1", "name": "Weather"}],
                            "tools_enabled": [
                                {
                                    "tool_id": "tool-1",
                                    "server_id": "server-1",
                                    "name": "forecast_tool",
                                }
                            ],
                        },
                        "rag": {
                            "attempted": True,
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
                                "included_source_ids": ["source-1"],
                                "included_source_titles": ["Beslut till underlag"],
                                "included_source_display_names": [
                                    "Beslut till underlag"
                                ],
                                "summary": {
                                    "total_sources": 1,
                                    "total_chunks": 2,
                                    "truncated_by_token_budget": False,
                                    "top_ranked_sources": [
                                        {
                                            "source_id": "source-1",
                                            "display_name": "Beslut till underlag",
                                            "source_kind": "website",
                                            "included_group_count": 1,
                                            "included_chunk_count": 2,
                                            "best_score": 1.0,
                                            "rank": 1,
                                        }
                                    ],
                                },
                                "included_groups": [
                                    {
                                        "source_id": "source-1",
                                        "source_title": "Beslut till underlag",
                                        "start_chunk": 1,
                                        "end_chunk": 2,
                                        "chunk_count": 2,
                                        "relevance_score": 1.0,
                                    }
                                ],
                            },
                        },
                        "attempts": [
                            {
                                "attempt_no": 1,
                                "status": "completed",
                                "duration_ms": 5000,
                                "error_code": None,
                                "requested_model": "gpt-4.1",
                                "response_model": "gpt-4.1-mini",
                                "provider": "openai",
                                "finish_reason": "stop",
                                "provider_response_id": "resp-123",
                                "num_tokens_input": 12,
                                "num_tokens_output": 18,
                            }
                        ],
                    }
                ],
                "security": {
                    "redaction_applied": True,
                    "classification_field": "output_classification_override",
                    "mcp_policy_field": "mcp_policy",
                },
            },
        }
    )

    assert isinstance(response.step_attempts[0], FlowStepAttemptPublic)
    assert response.step_attempts[0].status == FlowStepAttemptStatus.COMPLETED
    assert isinstance(response.rerun_operations[0], FlowRunRerunOperationPublic)
    assert response.rerun_operations[0].status == FlowRunRerunOperationStatus.COMPLETED
    assert response.rerun_operations[0].root_attempt_id == replacement_attempt_id
    assert isinstance(
        response.rerun_invalidated_steps[0], FlowRunRerunInvalidatedStepPublic
    )
    assert response.rerun_invalidated_steps[0].operation_id == rerun_operation_id
    assert response.rerun_invalidated_steps[0].dependency_sources_json == [
        "input_bindings.question"
    ]
    assert response.step_results[0].effective_prompt == "Summarize the report"
    assert response.step_results[0].model_parameters_json == {"temperature": 0.2}
    assert response.step_results[0].flow_step_execution_hash == "abc123"
    assert response.result_files[0].file_id == file_id
    assert response.result_files[0].availability == "available"
    assert response.review_checkpoints[0].id == review_checkpoint_id
    assert response.review_checkpoints[0].step_label == "Review summary"
    assert response.review_checkpoints[0].review_mode == FlowStepReviewMode.EDIT
    assert response.review_checkpoints[0].output_type == FlowOutputType.JSON
    assert response.review_checkpoints[0].step_snapshot_available is True
    assert response.review_checkpoints[0].output_contract == review_checkpoint_contract
    assert isinstance(response.debug_export.steps[0].attempts[0], FlowRunDebugAttempt)
    assert response.debug_export.steps[0].attempts[0].response_model == "gpt-4.1-mini"
    assert response.debug_export.steps[0].rag is not None
    assert response.debug_export.steps[0].rag.prompt_context is not None
    assert response.debug_export.steps[0].rag.prompt_context.included_source_ids == [
        "source-1"
    ]
    assert response.debug_export.steps[0].rag.prompt_context.summary is not None
    assert (
        response.debug_export.steps[0].rag.prompt_context.summary["total_sources"] == 1
    )
    assert response.debug_export.steps[
        0
    ].rag.prompt_context.included_source_display_names == ["Beslut till underlag"]


def test_http_test_request_accepts_current_payload_shape() -> None:
    request = HttpTestRequest.model_validate(
        {
            "config": {
                "url": "https://example.org/api",
                "auth": {"mode": "none"},
                "body": {"mode": "auto"},
                "custom_headers": [],
                "timeout_seconds": 30,
            },
            "direction": "output",
            "method": "POST",
            "test_variables": {"name": "Alex"},
        }
    )

    assert request.direction == "output"
    assert request.method == "POST"
    assert request.test_variables == {"name": "Alex"}


def test_http_test_response_parses_current_payload_shape() -> None:
    response = HttpTestResponse.model_validate(
        {
            "success": False,
            "status_code": None,
            "duration_ms": 12.5,
            "response_preview": None,
            "request_preview": {"method": "POST"},
            "error_code": "INVALID_CONFIG",
            "error_message": "bad config",
        }
    )

    assert response.success is False
    assert response.error_code == "INVALID_CONFIG"
