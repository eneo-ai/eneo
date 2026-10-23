"""Every patch a suggestion offers publishes: applied to the draft in memory
the way the editor update applies it, it passes publish's step rules, and a
patch that would not is taken back."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest

from eneo.flows.api.flow_models import FlowEditorUpdateRequest
from eneo.flows.application.flow_suggestion_service import (
    flow_suggestions,
    patched_draft,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.flow_run_retention_policy import (
    FlowRunRetentionContributors,
    FlowRunRetentionOff,
)
from eneo.flows.domain.flow_suggestions import FlowSuggestion, FlowSuggestionCode
from eneo.flows.flow_metadata import normalize_persisted_flow_metadata
from eneo.flows.flow_validators import publish_step_refusals
from eneo.flows.infrastructure.flow_repo import StoredAssistantPrompt

_CONTRACT = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    "required": ["title", "body"],
    "additionalProperties": False,
}
_FORM = {
    "form_schema": {
        "fields": [
            {"name": "kommun", "type": "text", "required": True},
            {"name": "arende", "type": "text"},
        ]
    }
}


def _step(order: int, **columns: Any) -> FlowStep:
    values: dict[str, Any] = {
        "id": uuid4(),
        "assistant_id": uuid4(),
        "step_order": order,
        "user_description": f"Steg {order}",
        "input_source": "flow_input" if order == 1 else "previous_step",
        "input_type": "text",
        "output_mode": "pass_through",
        "output_type": "text",
    }
    return FlowStep.model_validate({**values, **columns})


def _flow(steps: list[FlowStep], **fields: Any) -> Flow:
    now = datetime.now(timezone.utc)
    return Flow.model_validate(
        {
            "id": uuid4(),
            "tenant_id": uuid4(),
            "space_id": uuid4(),
            "space_name": "Space",
            "name": "Flow",
            "created_by_user_id": uuid4(),
            "owner_user_id": uuid4(),
            "run_history_retention": FlowRunRetentionOff(
                contributors=FlowRunRetentionContributors(
                    organization=None, space=None, flow=None
                )
            ),
            "draft_revision": 3,
            "created_at": now,
            "updated_at": now,
            "steps": steps,
            **fields,
        }
    )


def _prompts(flow: Flow, texts: dict[int, str]) -> dict[UUID, StoredAssistantPrompt]:
    """Each assistant's prompt, by the order of the first step that uses it."""
    prompts: dict[UUID, StoredAssistantPrompt] = {}
    for step in sorted(flow.steps, key=lambda item: item.step_order):
        prompts.setdefault(
            step.assistant_id,
            StoredAssistantPrompt(
                text=texts.get(step.step_order, "Gör så här."), description=None
            ),
        )
    return prompts


def _duplicate_prompt_line() -> tuple[Flow, dict[int, str]]:
    return _flow([_step(1), _step(2)]), {2: "Sammanfatta.\n{{ step_1.output.text }}"}


def _duplicate_source_ref() -> tuple[Flow, dict[int, str]]:
    bindings = {
        "question": "{{ step_1.output.text }}",
        "source_refs": [{"step_ref": "step_1", "output": "text"}],
    }
    return _flow([_step(1), _step(2, input_bindings=bindings)]), {}


def _shared_assistant_duplicate() -> tuple[Flow, dict[int, str]]:
    # Steps 2 and 3 share an assistant: the patch copies it for step 2.
    second = _step(2)
    third = _step(3, assistant_id=second.assistant_id)
    return _flow([_step(1), second, third]), {
        2: "{{ föregående_steg }}\n\nSvara.",
    }


def _unread_contract_field() -> tuple[Flow, dict[int, str]]:
    return (
        _flow(
            [
                _step(1, output_type="json", output_contract=_CONTRACT),
                _step(
                    2,
                    input_bindings={"question": "{{ step_1.output.structured.title }}"},
                ),
            ]
        ),
        {},
    )


def _relay() -> tuple[Flow, dict[int, str]]:
    return (
        _flow(
            [
                _step(1),
                _step(2, output_mode="compose_text"),
                _step(3),
                _step(4),
            ]
        ),
        {3: "Svara.\n{{ step_2.output.text }}", 4: "{{ step_3.output.text }}"},
    )


def _unused_form_field() -> tuple[Flow, dict[int, str]]:
    return (
        _flow(
            [_step(1, input_bindings={"question": "{{ flow_input.kommun }}"})],
            metadata_json=_FORM,
        ),
        {},
    )


def _unread_result() -> tuple[Flow, dict[int, str]]:
    # Step 3's underlag reads step 1, so nothing reads step 2.
    return (
        _flow(
            [
                _step(1),
                _step(2),
                _step(3, input_bindings={"question": "{{ step_1.output.text }}"}),
            ]
        ),
        {},
    )


def _offered_patch(suggestion: FlowSuggestion) -> dict[str, Any] | None:
    if suggestion.fix.patch is not None:
        return suggestion.fix.patch
    return suggestion.params.get("remove_patch")


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        pytest.param(_duplicate_prompt_line, "duplicate_read", id="prompt-line"),
        pytest.param(_duplicate_source_ref, "duplicate_read", id="source-ref"),
        pytest.param(_shared_assistant_duplicate, "duplicate_read", id="shared"),
        pytest.param(_unread_contract_field, "unread_contract_fields", id="contract"),
        pytest.param(_relay, "relay_step", id="relay"),
        pytest.param(_unused_form_field, "unused_form_field", id="form-field"),
        pytest.param(_unread_result, "unread_result", id="remove-step"),
    ],
)
def test_every_offered_patch_publishes(fixture, code: str) -> None:
    flow, texts = fixture()
    prompts = _prompts(flow, texts)
    saved_texts = {aid: prompt.text for aid, prompt in prompts.items()}
    assert (
        publish_step_refusals(
            flow.steps,
            metadata_json=normalize_persisted_flow_metadata(flow.metadata_json),
            prompt_templates={
                step.step_order: saved_texts[step.assistant_id] for step in flow.steps
            },
        )
        == []
    )

    # The first of its code: on a shared assistant, each step that shares it
    # has its own.
    suggestion = next(
        s for s in flow_suggestions(flow, prompts=prompts) if s.code.value == code
    )
    patch = _offered_patch(suggestion)
    assert patch is not None, suggestion
    update = FlowEditorUpdateRequest.model_validate(
        {**patch, "expected_revision": flow.draft_revision}
    )
    steps, metadata, prompt_templates = patched_draft(flow, update, prompts=saved_texts)

    assert (
        publish_step_refusals(
            steps, metadata_json=metadata, prompt_templates=prompt_templates
        )
        == []
    )


def test_the_relay_patch_leaves_every_reader_reading_the_source() -> None:
    flow, texts = _relay()
    prompts = _prompts(flow, texts)
    (suggestion,) = [
        s
        for s in flow_suggestions(flow, prompts=prompts)
        if s.code is FlowSuggestionCode.RELAY_STEP
    ]
    assert suggestion.fix.patch is not None
    update = FlowEditorUpdateRequest.model_validate(
        {**suggestion.fix.patch, "expected_revision": 3}
    )

    steps, _, prompt_templates = patched_draft(
        flow,
        update,
        prompts={aid: prompt.text for aid, prompt in prompts.items()},
    )

    assert [step.id for step in steps] == [
        flow.steps[0].id,
        flow.steps[2].id,
        flow.steps[3].id,
    ]
    # The reader of the relay reads step 1; the reader of step 3 follows it
    # to its new place.
    assert prompt_templates == {
        1: "Gör så här.",
        2: "Svara.\n{{ step_1.output.text }}",
        3: "{{ step_2.output.text }}",
    }


def test_a_patch_that_would_not_publish_is_downgraded_to_assisted() -> None:
    # Rewriting the relay's reader gives it two source refs of step 1, which
    # publish refuses; the saved draft publishes.
    flow = _flow(
        [
            _step(1),
            _step(2, output_mode="compose_text"),
            _step(
                3,
                input_bindings={
                    "source_refs": [
                        {"step_ref": "step_2", "output": "text"},
                        {"step_ref": "step_1", "output": "text"},
                    ]
                },
            ),
        ]
    )
    prompts = _prompts(flow, {})

    (suggestion,) = [
        s
        for s in flow_suggestions(flow, prompts=prompts)
        if s.code is FlowSuggestionCode.RELAY_STEP
    ]

    assert suggestion.fix.kind == "assisted"
    assert suggestion.fix.patch is None


def test_a_draft_that_already_fails_keeps_patches_that_add_no_failure() -> None:
    # Step 3's name collides with step 1's: publish refuses the draft either
    # way, and the duplicate's patch adds nothing to that.
    flow = _flow([_step(1), _step(2), _step(3, user_description="Steg 1")])
    prompts = _prompts(flow, {2: "Sammanfatta.\n{{ step_1.output.text }}"})

    duplicates = [
        s
        for s in flow_suggestions(flow, prompts=prompts)
        if s.code is FlowSuggestionCode.DUPLICATE_READ
    ]

    assert [s.fix.kind for s in duplicates] == ["patch"]


def test_a_remove_patch_that_would_lose_a_read_is_dropped() -> None:
    # Step 4 runs without a model, so its prompt is no read of step 2; the
    # editor update still refuses to remove a step a kept prompt names.
    flow = _flow(
        [
            _step(1),
            _step(2),
            _step(3, input_bindings={"question": "{{ step_1.output.text }}"}),
            _step(4, output_mode="compose_text"),
        ]
    )
    prompts = _prompts(flow, {4: "{{ step_2.output.text }}"})

    (unread,) = [
        s
        for s in flow_suggestions(flow, prompts=prompts)
        if s.code is FlowSuggestionCode.UNREAD_RESULT
    ]

    assert unread.steps == (flow.steps[1].id,)
    assert unread.fix.kind == "advice"
    assert "remove_patch" not in unread.params
