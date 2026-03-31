from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from intric.flows.enums import FlowStepResultStatus
from intric.flows.flow import FlowRun, FlowRunStatus, FlowStepResult, FlowVersion
from intric.flows.flow_run_evidence import build_debug_export, normalize_debug_step, parse_step_order
from intric.flows.flow_run_provenance import normalize_attempt_provenance


def test_parse_step_order_handles_strings_and_bools():
    assert parse_step_order(" 7 ") == 7
    assert parse_step_order(True, default=9) == 9
    assert parse_step_order("bad", default=5) == 5
    assert parse_step_order(None, default=3) == 3
    assert parse_step_order(7.2, default=4) == 4


def test_normalize_debug_step_uses_list_allowlist_and_rag_metadata():
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
            "mcp_tool_allowlist": "not-a-list",
        },
        rag_metadata={"status": "success"},
    )

    assert step["mcp"]["tool_allowlist"] == []
    assert step["rag"] == {"status": "success"}


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
    assert export["steps"][0]["rag"] == {"status": "success", "chunks_retrieved": 3}


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
