"""The chat's view of what each step reads and who reads it."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from eneo.flows.application.flow_authoring_reads import (
    output_fields,
    read_reference,
    run_form_fields,
    run_summary,
    step_connections,
    step_reads_summary,
)
from eneo.flows.infrastructure.flow_repo import StoredAssistantPrompt
from eneo.flows.step_lineage import StepRead


def _step(order: int, name: str, **config):
    return SimpleNamespace(
        id=uuid4(),
        assistant_id=uuid4(),
        step_order=order,
        user_description=name,
        input_source=config.pop("input_source", "previous_step"),
        input_type="text",
        input_bindings=None,
        input_config=config.pop("input_config", None),
        output_mode=config.pop("output_mode", "pass_through"),
        output_type=config.pop("output_type", "text"),
        output_contract=config.pop("output_contract", None),
        output_config=None,
        review_policy=None,
        output_classification_override=None,
    )


def _flow(*steps, metadata_json=None):
    return SimpleNamespace(steps=list(steps), metadata_json=metadata_json)


def test_read_reference_names_text_structured_and_a_path():
    assert read_reference(StepRead("prompt", 2, (), "x")) == "{{step_2.output.text}}"
    assert (
        read_reference(StepRead("prompt", 2, ("structured",), "x"))
        == "{{step_2.output.structured}}"
    )
    assert (
        read_reference(StepRead("prompt", 5, ("structured", "summary"), "x"))
        == "{{step_5.output.structured.summary}}"
    )


def test_each_step_lists_what_it_reads_and_who_reads_it():
    extract = _step(
        1,
        "Extract",
        input_source="flow_input",
        output_type="json",
        output_contract={"type": "object", "properties": {"summary": {}}},
    )
    reply = _step(2, "Reply")
    check = _step(3, "Check", input_source="all_previous_steps")
    prompts = {
        extract.assistant_id: StoredAssistantPrompt(
            "Extract from {{ flow_input.letter }}.", None
        ),
        reply.assistant_id: StoredAssistantPrompt(
            "Answer using {{ step_1.output.structured.summary }}.", None
        ),
        check.assistant_id: StoredAssistantPrompt("Check everything.", None),
    }
    form = {"form_schema": {"fields": [{"name": "letter", "type": "text"}]}}

    summary = step_reads_summary(
        _flow(extract, reply, check, metadata_json=form), prompts
    )

    # Step 1 reads nothing of an earlier step, only the form field: whole as
    # its input and again in its prompt.
    assert summary[1]["reads"] == []
    assert summary[1]["form_fields"] == [
        {"field": "letter", "where": "as its input (flow_input)"},
        {"field": "letter", "where": "in its prompt ({{ flow_input.letter }})"},
    ]
    # Step 2 reads step 1 as its input and a field of it in its prompt.
    assert summary[2]["reads"] == [
        {
            "step_order": 1,
            "name": "Extract",
            "value": "{{step_1.output.text}}",
            "where": "as its input (previous_step)",
        },
        {
            "step_order": 1,
            "name": "Extract",
            "value": "{{step_1.output.structured.summary}}",
            "where": "in its prompt ({{ step_1.output.structured.summary }})",
        },
    ]
    # Step 1's readers are step 2 (twice) and step 3 (through all steps).
    assert [(item["step_order"], item["value"]) for item in summary[1]["readers"]] == [
        (2, "{{step_1.output.text}}"),
        (2, "{{step_1.output.structured.summary}}"),
        (3, "{{step_1.output.text}}"),
    ]
    assert summary[3]["readers"] == []
    assert "unreadable" not in summary[2]


def test_a_step_whose_configuration_cannot_be_read_is_marked():
    first = _step(1, "First", input_source="flow_input")
    broken = _step(2, "Broken", input_source="not_a_source")

    summary = step_reads_summary(_flow(first, broken), {})

    assert summary[2]["unreadable"] is True
    assert summary[2]["reads"] == []


def test_run_form_fields_in_short_and_empty_when_unreadable():
    fields = run_form_fields(
        {
            "form_schema": {
                "fields": [
                    {
                        "name": "letter",
                        "type": "text",
                        "label": "Brev",
                        "required": True,
                    },
                    {"name": "kind", "type": "select", "options": ["a", "b"]},
                ]
            }
        }
    )
    assert fields == [
        {"name": "letter", "type": "text", "required": True, "label": "Brev"},
        {"name": "kind", "type": "select", "required": False, "options": ["a", "b"]},
    ]
    assert run_form_fields(None) == []
    assert run_form_fields({"form_schema": {"fields": "nonsense"}}) == []


def test_output_fields_names_the_contracts_top_level_fields():
    assert output_fields(None) is None
    assert output_fields({"type": "object"}) == []
    assert output_fields({"properties": {"a": {}, "b": {}}}) == ["a", "b"]


def _at(minute: int, second: int = 0) -> datetime:
    return datetime(2026, 10, 30, 12, minute, second, tzinfo=timezone.utc)


def test_a_run_summary_names_each_step_with_what_it_cost_and_how_it_ended():
    run_id = uuid4()
    detail = SimpleNamespace(
        id=run_id,
        status="failed",
        flow_version=3,
        purpose="production",
        started_at=_at(0),
        finished_at=_at(1, 30),
        token_usage=SimpleNamespace(
            num_tokens_input=100,
            num_tokens_output=40,
            num_tokens_total=140,
            input_completeness="complete",
            output_completeness="incomplete",
        ),
        error=SimpleNamespace(
            code="flow_step_timeout",
            message="Step timed out.",
            step_order=2,
            retryable=True,
            user_action="Start the run again.",
        ),
        result=None,
    )
    steps = [
        SimpleNamespace(
            step_order=2,
            status="failed",
            current_attempt_no=2,
            started_at=_at(0, 20),
            finished_at=_at(1, 30),
            num_tokens_input=60,
            num_tokens_output=0,
            effective_prompt_truncated=True,
            long_material=SimpleNamespace(coverage="partial"),
            diagnostics=[SimpleNamespace(code="material_left_out", severity="warning")],
            error_code="flow_step_timeout",
            error_message="Step timed out.",
        ),
        SimpleNamespace(
            step_order=1,
            status="completed",
            current_attempt_no=1,
            started_at=_at(0),
            finished_at=_at(0, 20),
            num_tokens_input=40,
            num_tokens_output=40,
            effective_prompt_truncated=False,
            long_material=None,
            diagnostics=[],
            error_code=None,
            error_message=None,
        ),
    ]
    checkpoints = [
        SimpleNamespace(step_order=1, attempt_no=1, state="rejected"),
        SimpleNamespace(step_order=1, attempt_no=2, state="approved"),
    ]

    summary = run_summary(
        detail, steps, {1: "Läs brevet", 2: "Skriv svaret"}, checkpoints
    )

    assert summary["run_id"] == str(run_id)
    assert summary["status"] == "failed"
    assert summary["duration_seconds"] == 90.0
    assert summary["tokens"] == {
        "input": 100,
        "output": 40,
        "total": 140,
        "complete": False,
    }
    assert summary["error"] == {
        "code": "flow_step_timeout",
        "message": "Step timed out.",
        "step_order": 2,
        "retryable": True,
        "user_action": "Start the run again.",
    }
    assert summary["result"] is None
    # Steps in order, the latest review per step, and the facts that tell a
    # setting from a transient failure.
    assert [s["step_order"] for s in summary["steps"]] == [1, 2]
    assert summary["steps"][0] == {
        "step_order": 1,
        "name": "Läs brevet",
        "status": "completed",
        "attempts": 1,
        "duration_seconds": 20.0,
        "tokens": {"input": 40, "output": 40},
        "prompt_truncated": False,
        "coverage": None,
        "diagnostics": [],
        "error": None,
        "review": {"state": "approved", "attempt": 2},
    }
    assert summary["steps"][1] == {
        "step_order": 2,
        "name": "Skriv svaret",
        "status": "failed",
        "attempts": 2,
        "duration_seconds": 70.0,
        "tokens": {"input": 60, "output": 0},
        "prompt_truncated": True,
        "coverage": "partial",
        "diagnostics": [{"code": "material_left_out", "severity": "warning"}],
        "error": {"code": "flow_step_timeout", "message": "Step timed out."},
        "review": None,
    }


def test_a_run_summary_shows_the_start_of_a_text_result_and_names_a_missing_step():
    detail = SimpleNamespace(
        id=uuid4(),
        status="completed",
        flow_version=1,
        purpose="test",
        started_at=None,
        finished_at=None,
        token_usage=None,
        error=None,
        result=SimpleNamespace(kind="inline_text", text="x" * 500),
    )
    step = SimpleNamespace(
        step_order=1,
        status="completed",
        current_attempt_no=1,
        started_at=None,
        finished_at=None,
        num_tokens_input=None,
        num_tokens_output=None,
        effective_prompt_truncated=False,
        long_material=None,
        diagnostics=[],
        error_code=None,
        error_message=None,
    )

    summary = run_summary(detail, [step], {}, [])

    assert summary["result"] == {
        "kind": "inline_text",
        "preview": "x" * 400,
        "preview_truncated": True,
    }
    assert summary["duration_seconds"] is None
    assert summary["tokens"] is None
    assert summary["steps"][0]["name"] == "Steg 1"


STORED = {"$secret": "stored"}


def test_a_steps_connections_name_the_service_and_whether_its_secret_is_stored():
    step = {
        "input_source": "http_get",
        "input_config": {
            "url": "https://api.example.se/cases?key=hidden",
            "auth": {"mode": "api_key", "header_name": "X-Key", "key": STORED},
            "custom_headers": [
                {"name": "X-Trace", "value": "abc", "secret": False},
                {"name": "X-Signature", "value": STORED, "secret": True},
            ],
        },
        "output_mode": "http_post",
        "output_config": {
            "url": "https://hooks.example.se/in",
            "auth": {"mode": "bearer_token", "token": ""},
        },
    }

    source, delivery = step_connections(step)

    assert source == {
        "kind": "http",
        "direction": "input",
        "field": "input_config.http",
        "url": "https://api.example.se/cases",
        "auth_mode": "api_key",
        "credential": "stored",
        "secret_headers": 1,
        "configured": True,
    }
    assert delivery == {
        "kind": "http",
        "direction": "output",
        "field": "output_config.http",
        "url": "https://hooks.example.se/in",
        "auth_mode": "bearer_token",
        "credential": "missing",
        "secret_headers": 0,
        "configured": False,
    }
    # The secret itself never appears, only that it is stored.
    assert "hidden" not in str([source, delivery])


def test_a_tool_step_names_its_server_and_an_open_delivery_needs_no_credential():
    tool = {
        "input_source": "tool",
        "input_config": {"tool": {"mcp_server_id": "srv-1", "tool_id": "t-1"}},
        "output_mode": "pass_through",
    }
    assert step_connections(tool) == [
        {
            "kind": "mcp",
            "direction": "input",
            "field": "input_config.tool",
            "mcp_server_id": "srv-1",
            "tool_id": "t-1",
        }
    ]
    open_delivery = {
        "input_source": "previous_step",
        "output_mode": "http_post",
        "output_config": {
            "url": "https://hooks.example.se/in",
            "auth": {"mode": "none"},
        },
    }
    (item,) = step_connections(open_delivery)
    assert item["credential"] == "none" and item["configured"] is True
    assert (
        step_connections(
            {"input_source": "previous_step", "output_mode": "pass_through"}
        )
        == []
    )


def test_an_http_configuration_the_core_refuses_is_marked_unreadable():
    broken = {
        "input_source": "http_get",
        "input_config": {"url": "https://x", "auth": {"mode": "magic"}},
        "output_mode": "pass_through",
    }
    assert step_connections(broken) == [
        {
            "kind": "http",
            "direction": "input",
            "field": "input_config.http",
            "unreadable": True,
        }
    ]
