from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from intric.flows.api.flow_models import (
    FlowRunContractPublic,
    FlowRunCreateRequest,
    FlowRunDebugAttempt,
    FlowRunEvidenceResponse,
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
from intric.flows.enums import FlowStepAttemptStatus


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
def test_flow_step_create_request_rejects_invalid_enum_values(field: str, value: str) -> None:
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
    contract = FlowRunContractPublic.model_validate(
        {
            "flow_id": str(uuid4()),
            "published_flow_version": 3,
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


def test_flow_run_evidence_response_parses_typed_nested_models() -> None:
    run_id = uuid4()
    flow_id = uuid4()
    tenant_id = uuid4()
    step_id = uuid4()
    attempt_id = uuid4()

    response = FlowRunEvidenceResponse.model_validate(
        {
            "run": {
                "id": str(run_id),
                "flow_id": str(flow_id),
                "flow_version": 2,
                "tenant_id": str(tenant_id),
                "trace_id": str(uuid4()),
                "status": "completed",
                "created_at": "2026-03-20T12:00:00Z",
                "updated_at": "2026-03-20T12:05:00Z",
            },
            "definition_snapshot": {"steps": []},
            "step_results": [
                {
                    "id": str(uuid4()),
                    "flow_run_id": str(run_id),
                    "flow_id": str(flow_id),
                    "tenant_id": str(tenant_id),
                    "step_id": str(step_id),
                    "step_order": 1,
                    "status": "completed",
                    "effective_prompt": "Summarize the report",
                    "model_parameters_json": {"temperature": 0.2},
                    "flow_step_execution_hash": "abc123",
                    "tool_calls_metadata": [{"name": "search"}],
                    "created_at": "2026-03-20T12:00:01Z",
                    "updated_at": "2026-03-20T12:00:05Z",
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
                        "mcp": {"policy": "inherit", "tool_allowlist": []},
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
                                "included_source_display_names": ["Beslut till underlag"],
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
    assert response.step_results[0].effective_prompt == "Summarize the report"
    assert response.step_results[0].model_parameters_json == {"temperature": 0.2}
    assert response.step_results[0].flow_step_execution_hash == "abc123"
    assert response.step_results[0].tool_calls_metadata == [{"name": "search"}]
    assert isinstance(response.debug_export.steps[0].attempts[0], FlowRunDebugAttempt)
    assert response.debug_export.steps[0].attempts[0].response_model == "gpt-4.1-mini"
    assert response.debug_export.steps[0].rag is not None
    assert response.debug_export.steps[0].rag.prompt_context is not None
    assert response.debug_export.steps[0].rag.prompt_context.included_source_ids == ["source-1"]
    assert (
        response.debug_export.steps[0].rag.prompt_context.included_source_display_names
        == ["Beslut till underlag"]
    )


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
