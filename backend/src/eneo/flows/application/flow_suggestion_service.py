"""Suggestions for a draft flow, computed from the saved draft and the prompts
of its step assistants; writes nothing.

Every patch is checked before it is offered: it is applied to the draft in
memory, the way an editor update applies it (its placement, the reads that
follow a removed step, the settings of modes a step does not use dropped),
and the result goes through publish's own step rules. A patch whose draft
would fail a rule that the draft as saved passes is not offered: the
suggestion becomes ``assisted``. A draft that already fails a rule for other
reasons keeps the patches that add no failure.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any, cast
from uuid import UUID

from pydantic import ValidationError

from eneo.flows.api.flow_models import FlowEditorStepPatch, FlowEditorUpdateRequest
from eneo.flows.application.flow_authoring_operations import sparse_placement
from eneo.flows.application.flow_service import draft_write_metadata, steps_as_written
from eneo.flows.application.flow_step_structure import (
    form_field_change,
    restructure_steps,
)
from eneo.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from eneo.flows.domain.flow_suggestions import (
    FlowSuggestion,
    FlowSuggestionFix,
    SuggestionFlow,
    SuggestionStep,
    analyze_flow,
)
from eneo.flows.enums import flow_output_mode_uses_completion_model
from eneo.flows.flow_metadata import normalize_persisted_flow_metadata
from eneo.flows.flow_validators import publish_step_refusals
from eneo.flows.infrastructure.flow_repo import StoredAssistantPrompt
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.main.models import NOT_PROVIDED, NotProvided

# A patch the in-memory draft cannot take: the editor update refuses it, the
# reads it leaves lose their step, or its metadata cannot be written.
_UNAPPLICABLE = (BadRequestException, NotFoundException, ValidationError, ValueError)

RefusalKey = tuple[str, UUID | None]


def suggestion_step(
    step: FlowStep, *, prompt: StoredAssistantPrompt | None
) -> SuggestionStep:
    """The analyzer's view of a saved step. The prompt counts as a read only
    when a completion model reads it, as the classification rule counts it."""
    assert step.id is not None, "a saved step has an id"
    reads_prompt = flow_output_mode_uses_completion_model(step.output_mode)
    return SuggestionStep(
        id=step.id,
        step_order=step.step_order,
        user_description=step.user_description,
        input_source=step.input_source,
        input_type=step.input_type,
        input_bindings=step.input_bindings,
        input_config=step.input_config,
        output_mode=step.output_mode,
        output_type=step.output_type,
        output_contract=step.output_contract,
        output_config=step.output_config,
        prompt_text=(
            (prompt.text if prompt is not None else "") if reads_prompt else None
        ),
        assistant_id=step.assistant_id,
        prompt_description=prompt.description if prompt is not None else None,
        has_review_policy=step.review_policy is not None,
        output_classification_override=step.output_classification_override,
    )


def suggestion_flow(
    flow: Flow, *, prompts: Mapping[UUID, StoredAssistantPrompt]
) -> SuggestionFlow:
    """The analyzer's view of a saved draft: its steps with their assistants'
    prompts, and its metadata as saved."""
    return SuggestionFlow(
        steps=[
            suggestion_step(step, prompt=prompts.get(step.assistant_id))
            for step in flow.steps
            if step.id is not None
        ],
        metadata_json=flow.metadata_json,
    )


def flow_suggestions(
    flow: Flow, *, prompts: Mapping[UUID, StoredAssistantPrompt]
) -> tuple[FlowSuggestion, ...]:
    """Every suggestion the draft proves, given the saved prompt of each step
    assistant (an assistant without one reads as an empty prompt), each
    patch checked against the publish rules."""
    return checked_suggestions(
        flow, analyze_flow(suggestion_flow(flow, prompts=prompts)), prompts=prompts
    )


async def list_flow_suggestions(
    *, container: Container, flow: Flow
) -> tuple[FlowSuggestion, ...]:
    """The suggestions of ``flow``'s draft. The prompts are read once for all
    of its assistants, tenant-scoped, as the step-kinds answer reads them.
    The caller has decided that the user may edit the flow."""
    stored = await container.flow_service().get_flow_assistant_prompts(flow)
    return flow_suggestions(flow, prompts=stored)


# At most this many introduced suggestions are reported after one change.
MAX_REPORTED_INTRODUCED = 10


def introduced_suggestions(
    before: Sequence[FlowSuggestion], after: Sequence[FlowSuggestion]
) -> tuple[FlowSuggestion, ...]:
    """The suggestions of ``after`` that ``before`` did not have: what a
    change introduced, in the order ``after`` lists them."""
    known = {suggestion.fingerprint for suggestion in before}
    return tuple(
        suggestion for suggestion in after if suggestion.fingerprint not in known
    )


def suggestion_summary(
    suggestion: FlowSuggestion, steps: Sequence[FlowStep]
) -> dict[str, Any]:
    """A suggestion in short, for a tool result: no patch body, its steps by
    order and name."""
    by_id = {step.id: step for step in steps if step.id is not None}
    return {
        "fingerprint": suggestion.fingerprint,
        "code": suggestion.code.value,
        "message": suggestion.message,
        "fix_kind": suggestion.fix.kind,
        "steps": [
            {"step_order": step.step_order, "name": step.user_description}
            for step_id in suggestion.steps
            if (step := by_id.get(step_id)) is not None
        ],
    }


def checked_suggestions(
    flow: Flow,
    suggestions: Sequence[FlowSuggestion],
    *,
    prompts: Mapping[UUID, StoredAssistantPrompt],
) -> tuple[FlowSuggestion, ...]:
    """``suggestions`` with every patch that would add a publish refusal
    taken back: a ``patch`` fix becomes ``assisted``, and an offered
    ``params["remove_patch"]`` is dropped."""

    texts = {assistant_id: prompt.text for assistant_id, prompt in prompts.items()}
    saved = _ordered(flow.steps)
    baseline = Counter(
        _refusal_keys(
            saved,
            publish_step_refusals(
                saved,
                metadata_json=normalize_persisted_flow_metadata(flow.metadata_json),
                prompt_templates={
                    step.step_order: texts.get(step.assistant_id, "") for step in saved
                },
            ),
        )
    )
    checked: list[FlowSuggestion] = []
    for suggestion in suggestions:
        patch = suggestion.fix.patch
        if patch is not None and not _publishes(flow, patch, texts, baseline):
            suggestion = suggestion.model_copy(
                update={"fix": FlowSuggestionFix(kind="assisted")}
            )
        remove_patch = suggestion.params.get("remove_patch")
        if isinstance(remove_patch, dict) and not _publishes(
            flow, cast(dict[str, Any], remove_patch), texts, baseline
        ):
            suggestion = suggestion.model_copy(
                update={
                    "params": {
                        key: value
                        for key, value in suggestion.params.items()
                        if key != "remove_patch"
                    }
                }
            )
        checked.append(suggestion)
    return tuple(checked)


def _publishes(
    flow: Flow,
    patch: Mapping[str, Any],
    prompts: Mapping[UUID, str],
    baseline: Counter[RefusalKey],
) -> bool:
    """Whether ``patch``, applied to the draft in memory, leaves it with no
    publish refusal the draft as saved does not have."""
    try:
        update = FlowEditorUpdateRequest.model_validate(
            {**patch, "expected_revision": flow.draft_revision}
        )
        steps, metadata, prompt_templates = patched_draft(flow, update, prompts=prompts)
    except _UNAPPLICABLE:
        return False
    refusals = publish_step_refusals(
        steps, metadata_json=metadata, prompt_templates=prompt_templates
    )
    return not Counter(_refusal_keys(steps, refusals)) - baseline


def patched_draft(
    flow: Flow,
    update: FlowEditorUpdateRequest,
    *,
    prompts: Mapping[UUID, str],
) -> tuple[list[FlowStep], FlowPersistedJsonObject | None, dict[int, str]]:
    """The draft ``update`` would save, in memory: its steps, its metadata as
    publish normalizes it, and the prompt each step's assistant would have,
    by step order. ``prompts`` are the saved prompts by assistant.

    The pieces are the editor update's (``apply_editor_update``): its
    placement, its read following and the save's cleaning of the settings of
    modes a step does not use. An assistant change with ``step_id`` gives
    that step the prompt (a copy, when the assistant is shared); one without
    gives it to every step of the assistant. New steps are not judged here
    (no suggestion adds one) and raise ``ValueError``. Raises what the
    update would refuse with when the steps cannot take it."""

    if update.new_steps:
        raise ValueError("A suggestion's patch adds no step.")
    saved_steps = _ordered(flow.steps)
    saved_by_id = {step.id: step for step in saved_steps if step.id is not None}
    changed: dict[UUID, FlowEditorStepPatch] = {
        change.step_id: change.changes for change in update.step_edits
    }
    placed_ids = {
        slot.step_id for slot in update.step_order or [] if slot.step_id is not None
    }
    if (changed.keys() | placed_ids) - saved_by_id.keys():
        raise NotFoundException("Step not found.")
    step_prompts: dict[UUID, str] = {}
    assistant_prompts: dict[UUID, str] = {}
    for change in update.assistants:
        if change.step_id is not None:
            step = saved_by_id.get(change.step_id)
            if step is None or step.assistant_id != change.assistant_id:
                raise NotFoundException("Step not found.")
        prompt = change.changes.prompt
        if prompt is None:
            continue
        if change.step_id is not None:
            step_prompts[change.step_id] = prompt.text
        else:
            assistant_prompts[change.assistant_id] = prompt.text
    placed = [
        replace(item, prompt_written=True)
        if item.saved is not None and item.saved.id in step_prompts
        else item
        for item in sparse_placement(
            update=update, changed=changed, saved_steps=saved_steps, new_steps=[]
        )
    ]
    definition = update.definition
    writes_metadata = "metadata_json" in definition.model_fields_set and not (
        isinstance(definition.metadata_json, NotProvided)
    )
    metadata = cast(
        FlowPersistedJsonObject | None,
        definition.metadata_json if writes_metadata else flow.metadata_json,
    )
    structure = restructure_steps(
        placed,
        prompts=prompts,
        rewritten_prompts=frozenset(assistant_prompts),
        saved_steps=saved_steps,
        form_fields=(
            form_field_change(
                saved_metadata=flow.metadata_json,
                metadata=metadata,
                renames=definition.form_field_renames,
            )
            if writes_metadata or definition.form_field_renames
            else None
        ),
    )
    written = steps_as_written(
        structure.steps,
        unchanged_step_ids=frozenset(
            step_id for step_id in saved_by_id if step_id not in changed
        ),
    )

    def prompt_of(step: FlowStep) -> str:
        if step.id is not None and step.id in step_prompts:
            return step_prompts[step.id]
        if step.assistant_id in assistant_prompts:
            return assistant_prompts[step.assistant_id]
        if step.assistant_id in structure.changed_prompts:
            return structure.changed_prompts[step.assistant_id]
        return prompts.get(step.assistant_id, "")

    return (
        written,
        normalize_persisted_flow_metadata(
            draft_write_metadata(
                flow.metadata_json, metadata if writes_metadata else NOT_PROVIDED
            )
        ),
        {step.step_order: prompt_of(step) for step in written},
    )


def _refusal_keys(
    steps: Sequence[FlowStep], refusals: Sequence[BadRequestException]
) -> list[RefusalKey]:
    """Each refusal as what it is and the step it is about, so a refusal of
    a step that moved is the same refusal."""
    ids_by_order = {step.step_order: step.id for step in steps}
    keys: list[RefusalKey] = []
    for refusal in refusals:
        context = refusal.context or {}
        order = getattr(refusal, "step_order", None) or context.get("step_order")
        what = str(context.get("issue_code") or refusal.code or type(refusal).__name__)
        keys.append((what, ids_by_order.get(order) if isinstance(order, int) else None))
    return keys


def _ordered(steps: Sequence[FlowStep]) -> list[FlowStep]:
    return sorted(steps, key=lambda step: step.step_order)


__all__ = [
    "checked_suggestions",
    "flow_suggestions",
    "list_flow_suggestions",
    "patched_draft",
    "suggestion_flow",
    "suggestion_step",
]
