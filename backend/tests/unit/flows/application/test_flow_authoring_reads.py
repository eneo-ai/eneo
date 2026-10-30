"""The chat's view of what each step reads and who reads it."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from eneo.flows.application.flow_authoring_reads import (
    output_fields,
    read_reference,
    run_form_fields,
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
