"""Which kinds of step may stand at each place of a draft, and why the others
may not, judged by the draft save's own rules.

For a place a step can be added (before a step or after the last) or a saved
step, each kind's change is built as an editor update makes it: the new step
with the kind's configuration at that place (step 1 also hands the run's input
over to it), or the saved step turned to the kind's configuration. The change
then goes through what the save does with it: the
editor update's placement, the reads that follow moved steps, the settings of
modes a step does not use dropped, and the step rules. A kind is allowed
exactly when those accept the change, and its refusals are theirs.

Not judged: the new step's name, which the author gives; the URL of an HTTP
kind and the tool of a tool kind, which the author enters (they are judged as
entered and valid); and the checks a save makes against the space and the
organisation (assistants, security classification, the transcription service),
which do not depend on the step's place.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from eneo.flows.api.flow_models import (
    FlowEditorStepPatch,
    FlowEditorUpdateRequest,
)
from eneo.flows.application.flow_authoring_operations import (
    new_flow_step,
    sparse_placement,
)
from eneo.flows.application.flow_service import (
    draft_write_metadata,
    published_draft_refusal,
    steps_as_written,
)
from eneo.flows.application.flow_step_structure import (
    form_field_change,
    restructure_steps,
)
from eneo.flows.domain.flow import Flow, FlowPersistedJsonObject, FlowStep
from eneo.flows.domain.flow_step_validation import FlowGraphIssueCode
from eneo.flows.domain.step_kinds import (
    FlowStepKind,
    StepKindValues,
    run_input_hand_over,
    step_kind_configuration,
)
from eneo.flows.enums import FlowOutputType
from eneo.flows.flow_authoring_transcription import requires_audio_transcription
from eneo.flows.flow_validators import (
    draft_step_refusals,
    retained_contracts,
    validate_step_count,
)
from eneo.flows.transcription_config import (
    FlowTranscriptionConfigError,
    parse_transcription_config,
)
from eneo.main.exceptions import BadRequestException
from eneo.main.models import NOT_PROVIDED, NotProvided

# Stand-ins for what the author enters: an HTTP kind is judged with a URL and
# a tool kind with a tool, as if entered and valid.
JUDGED_VALUES = StepKindValues(
    url="https://example.org/",
    tool={
        "mcp_server_id": "00000000-0000-0000-0000-000000000000",
        "tool_id": "00000000-0000-0000-0000-000000000000",
        "arguments": {},
    },
)
# The assistant a new step is judged with; the save creates its own.
_JUDGED_ASSISTANT_ID = UUID(int=0)


@dataclass(frozen=True, slots=True)
class StepKindRefusal:
    """A refusal of the change, as the save gives it: its error ``code``, the
    step rule that refuses it (``issue_code``, None for a refusal outside the
    step rules) and the step it is about, numbered as after the change (None
    for the flow as a whole). ``step_id`` is None for the new step."""

    code: str | None
    issue_code: FlowGraphIssueCode | None
    step_order: int | None
    step_id: UUID | None
    message: str


@dataclass(frozen=True, slots=True)
class StepKindChange:
    """What adding a kind, or turning a saved step to it, changes: the step's
    configuration, the saved steps it edits too (by id) and whether it turns
    the flow's transcription on."""

    configuration: dict[str, object]
    step_edits: tuple[tuple[UUID, dict[str, object]], ...] = ()
    turns_on_transcription: bool = False


@dataclass(frozen=True, slots=True)
class StepKindOption:
    kind: FlowStepKind
    change: StepKindChange
    refusals: tuple[StepKindRefusal, ...]

    @property
    def allowed(self) -> bool:
        return not self.refusals


@dataclass(frozen=True, slots=True)
class StepKindPlace:
    """A place in the draft: where a step is added (``step_id`` None;
    ``position`` the place it takes) or a saved step (its order)."""

    position: int
    step_id: UUID | None
    options: tuple[StepKindOption, ...]


@dataclass(frozen=True, slots=True)
class StepKindAnswer:
    insertions: tuple[StepKindPlace, ...]
    steps: tuple[StepKindPlace, ...]


def step_kind_answer(
    flow: Flow,
    *,
    prompts: Mapping[UUID, str],
    positions: Sequence[int],
    step_ids: Sequence[UUID],
) -> StepKindAnswer:
    """Every kind at the insertion ``positions`` and saved ``step_ids`` of
    ``flow``'s draft. Each place judges the whole draft once per kind, so a
    caller names the places it needs. ``prompts`` are the saved prompts of
    the steps' assistants, which follow moved steps too."""

    insertion_positions = sorted(set(positions))
    changed_steps = [
        step
        for step in _ordered(flow.steps)
        if step.id is not None and step.id in step_ids
    ]
    return StepKindAnswer(
        insertions=tuple(
            StepKindPlace(
                position=position,
                step_id=None,
                options=tuple(
                    _option(flow, kind, position=position, prompts=prompts)
                    for kind in FlowStepKind
                ),
            )
            for position in insertion_positions
        ),
        steps=tuple(
            StepKindPlace(
                position=step.step_order,
                step_id=step.id,
                options=tuple(
                    _option(flow, kind, step=step, prompts=prompts)
                    for kind in FlowStepKind
                ),
            )
            for step in changed_steps
        ),
    )


def insertion_change(
    flow: Flow,
    kind: FlowStepKind,
    *,
    position: int,
    values: StepKindValues = StepKindValues(),
) -> StepKindChange:
    """Adding a step of ``kind`` at ``position`` (1 is first). Before a first
    step that reads the run's input, the new step takes that input over."""

    steps = _ordered(flow.steps)
    previous = steps[position - 2] if position > 1 else None
    configuration = step_kind_configuration(
        kind,
        previous_output_type=_output_type(previous),
        values=values,
    )
    step_edits: tuple[tuple[UUID, dict[str, object]], ...] = ()
    first = steps[0] if position == 1 and steps else None
    if first is not None and first.id is not None:
        hand_over = run_input_hand_over(
            first,
            new_output_type=FlowOutputType(configuration["output_type"]),
        )
        if hand_over is not None:
            step_edits = ((first.id, hand_over),)
    return StepKindChange(
        configuration=configuration,
        step_edits=step_edits,
        turns_on_transcription=_turns_on_transcription(flow, configuration),
    )


def step_change(
    flow: Flow,
    kind: FlowStepKind,
    *,
    step: FlowStep,
    values: StepKindValues = StepKindValues(),
) -> StepKindChange:
    """Turning the saved ``step`` to ``kind`` where it stands: every
    configuration column becomes the kind's; its name and assistant stay."""

    steps = _ordered(flow.steps)
    index = next(i for i, saved in enumerate(steps) if saved.id == step.id)
    configuration = step_kind_configuration(
        kind,
        previous_output_type=_output_type(steps[index - 1] if index > 0 else None),
        values=values,
    )
    return StepKindChange(
        configuration=configuration,
        turns_on_transcription=_turns_on_transcription(flow, configuration),
    )


def editor_update(
    flow: Flow,
    change: StepKindChange,
    *,
    position: int | None = None,
    step_id: UUID | None = None,
    name: str = "New step",
) -> FlowEditorUpdateRequest:
    """The editor update that makes ``change``: adding a step named ``name``
    at ``position``, or turning the saved step ``step_id``."""

    step_edits = [
        {"step_id": str(edited), "changes": changes}
        for edited, changes in change.step_edits
    ]
    payload: dict[str, object] = {
        "expected_revision": flow.draft_revision,
        "definition": (
            {"metadata_json": _with_transcription_on(flow.metadata_json)}
            if change.turns_on_transcription
            else {}
        ),
    }
    if step_id is not None:
        payload["step_edits"] = [
            {"step_id": str(step_id), "changes": change.configuration},
            *step_edits,
        ]
    else:
        slots: list[dict[str, object]] = [
            {"step_id": str(step.id)} for step in _ordered(flow.steps)
        ]
        slots.insert(cast(int, position) - 1, {"new_step": 0})
        payload["new_steps"] = [
            {"name": name, "configuration": change.configuration, "assistant": {}}
        ]
        payload["step_order"] = slots
        payload["step_edits"] = step_edits
    return FlowEditorUpdateRequest.model_validate(payload)


def judge_editor_update(
    flow: Flow, update: FlowEditorUpdateRequest, *, prompts: Mapping[UUID, str]
) -> tuple[StepKindRefusal, ...]:
    """The refusals the draft save gives ``update``'s steps, by the save's own
    placement, read following and step rules. New steps are judged unnamed."""

    published = published_draft_refusal(flow)
    if published is not None:
        return (_refusal(published, ids_by_order={}),)
    saved_steps = _ordered(flow.steps)
    new_steps = [
        new_flow_step(
            new_step.configuration,
            assistant_id=_JUDGED_ASSISTANT_ID,
            step_order=len(saved_steps) + index + 1,
            name=None,
        )
        for index, new_step in enumerate(update.new_steps)
    ]
    changed: dict[UUID, FlowEditorStepPatch] = {
        change.step_id: change.changes for change in update.step_edits
    }
    placed = sparse_placement(
        update=update,
        changed=changed,
        saved_steps=saved_steps,
        new_steps=new_steps,
    )
    ids_by_order = {
        position: item.saved.id if item.saved is not None else None
        for position, item in enumerate(placed, start=1)
    }
    definition = update.definition
    writes_metadata = "metadata_json" in definition.model_fields_set and not (
        isinstance(definition.metadata_json, NotProvided)
    )
    metadata = cast(
        FlowPersistedJsonObject | None,
        definition.metadata_json if writes_metadata else flow.metadata_json,
    )
    try:
        structure = restructure_steps(
            placed,
            prompts=prompts,
            saved_steps=saved_steps,
            form_fields=(
                form_field_change(saved_metadata=flow.metadata_json, metadata=metadata)
                if writes_metadata
                else None
            ),
        )
        written = steps_as_written(
            structure.steps,
            unchanged_step_ids=frozenset(
                step.id
                for step in saved_steps
                if step.id is not None and step.id not in changed
            ),
        )
        refusals = draft_step_refusals(
            written,
            metadata_json=draft_write_metadata(
                flow.metadata_json, metadata if writes_metadata else NOT_PROVIDED
            ),
            retained=retained_contracts(written, saved_steps),
        )
    except BadRequestException as exc:
        refusals = [exc]
    return tuple(_refusal(exc, ids_by_order=ids_by_order) for exc in refusals)


def _option(
    flow: Flow,
    kind: FlowStepKind,
    *,
    prompts: Mapping[UUID, str],
    position: int | None = None,
    step: FlowStep | None = None,
) -> StepKindOption:
    """``kind`` added at ``position``, or ``step`` turned to it."""

    if step is not None:
        judged = step_change(flow, kind, step=step, values=JUDGED_VALUES)
        return StepKindOption(
            kind=kind,
            change=step_change(flow, kind, step=step),
            refusals=judge_editor_update(
                flow, editor_update(flow, judged, step_id=step.id), prompts=prompts
            ),
        )
    assert position is not None
    judged = insertion_change(flow, kind, position=position, values=JUDGED_VALUES)
    return StepKindOption(
        kind=kind,
        change=insertion_change(flow, kind, position=position),
        refusals=_growth_refusals(flow)
        or judge_editor_update(
            flow, editor_update(flow, judged, position=position), prompts=prompts
        ),
    )


def _growth_refusals(flow: Flow) -> tuple[StepKindRefusal, ...]:
    """The refusals of any new step, in the order the save meets them: a
    published flow, then a flow with as many steps as a flow can have. The
    editor update refuses a step order longer than that before the save's
    rules run; the rule's own refusal stands for it here."""

    try:
        published = published_draft_refusal(flow)
        if published is not None:
            raise published
        validate_step_count(len(flow.steps) + 1)
    except BadRequestException as exc:
        return (_refusal(exc, ids_by_order={}),)
    return ()


def _refusal(
    exc: BadRequestException, *, ids_by_order: Mapping[int, UUID | None]
) -> StepKindRefusal:
    context = exc.context or {}
    raw_issue = context.get("issue_code")
    try:
        issue_code = FlowGraphIssueCode(raw_issue) if raw_issue else None
    except ValueError:
        issue_code = None
    raw_order = context.get("step_order")
    step_order = raw_order if isinstance(raw_order, int) else None
    return StepKindRefusal(
        code=exc.code,
        issue_code=issue_code,
        step_order=step_order,
        step_id=ids_by_order.get(step_order) if step_order is not None else None,
        message=str(exc),
    )


def _turns_on_transcription(flow: Flow, configuration: Mapping[str, object]) -> bool:
    step = FlowStep.model_validate(
        {**configuration, "assistant_id": _JUDGED_ASSISTANT_ID, "step_order": 1}
    )
    if not requires_audio_transcription([step]):
        return False
    try:
        return not parse_transcription_config(flow.metadata_json).enabled
    except FlowTranscriptionConfigError:
        # The save refuses the malformed choice; nothing is turned on over it.
        return False


def _with_transcription_on(
    metadata: FlowPersistedJsonObject | None,
) -> FlowPersistedJsonObject:
    turned_on = dict(metadata or {})
    wizard = turned_on.get("wizard")
    turned_on["wizard"] = {
        **(wizard if isinstance(wizard, dict) else {}),
        "transcription_enabled": True,
    }
    return turned_on


def _output_type(step: FlowStep | None) -> FlowOutputType | None:
    return None if step is None else FlowOutputType(step.output_type)


def _ordered(steps: Sequence[FlowStep]) -> list[FlowStep]:
    return sorted(steps, key=lambda step: step.step_order)
