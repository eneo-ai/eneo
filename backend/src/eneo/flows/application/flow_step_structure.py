"""Reorder, remove and insert the steps of a draft without changing what a
kept step reads.

A step reads an earlier step by its alias, ``step_N``: the producer's position.
When steps move or go, the aliases a kept step reads are renumbered with their
producers, in its input bindings, in the configuration its modes interpolate
and in its assistant's prompt. A read that was valid where it was saved and
whose producer the change removes, or moves to where the reader cannot see it,
refuses the change: written as it stands it would name another step. A read
that was not valid where it was saved (a forward or a dangling one) is written
as it stands, and refuses the change when the change would make it name a step
it could not before. Columns the same edit writes are taken as given.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from uuid import UUID

from eneo.flows.domain.flow import FlowStep
from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_authoring_variable_rewriting import (
    StepAliasRead,
    config_alias_reads,
    input_binding_alias_reads,
    prompt_alias_reads,
    renumber_config_aliases,
    renumber_input_binding_aliases,
    renumber_step_aliases,
)
from eneo.flows.step_lineage import ConfigChannel, ConfigColumn, config_channel
from eneo.main.exceptions import BadRequestException

_CONFIG_COLUMNS: tuple[ConfigColumn, ...] = ("input_config", "output_config")


class StepReadLostItsProducerError(BadRequestException):
    """A kept step would read another step than the one it reads now."""

    def __init__(self, message: str, *, context: dict[str, object]) -> None:
        super().__init__(
            message,
            code=FlowApiErrorCode.STEP_READ_LOST_PRODUCER.value,
            context=context,
        )


@dataclass(frozen=True, slots=True)
class PlacedStep:
    """A step at its place in the new order: a saved step (``saved``) or a new
    one. ``step`` holds the columns the edit writes for it; for a saved step
    ``written_columns`` names them, and every other column is the saved one."""

    step: FlowStep
    saved: FlowStep | None = None
    written_columns: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class StepStructure:
    """The steps in their new order, numbered from 1, and the prompts whose
    aliases moved with their producers (by assistant)."""

    steps: list[FlowStep]
    renumbered_prompts: dict[UUID, str]


def restructure_steps(
    placed: Sequence[PlacedStep],
    *,
    prompts: Mapping[UUID, str],
    rewritten_prompts: frozenset[UUID] = frozenset(),
) -> StepStructure:
    """``placed`` in their new order; ``prompts`` the saved prompt of each
    kept step's assistant, and ``rewritten_prompts`` the assistants whose
    prompt the same edit writes, as given."""

    owner_at = {
        index + 1: (item.saved.step_order if item.saved is not None else None)
        for index, item in enumerate(placed)
    }
    renumbering = {
        saved: position
        for position, saved in owner_at.items()
        if saved is not None and saved != position
    }
    steps: list[FlowStep] = []
    renumbered_prompts: dict[UUID, str] = {}
    for index, item in enumerate(placed):
        position = index + 1
        saved = item.saved
        if saved is None:
            steps.append(item.step.model_copy(update={"step_order": position}))
            continue
        reads = _saved_reads(saved, written=item.written_columns)
        prompt = prompts.get(saved.assistant_id)
        if prompt is not None and saved.assistant_id not in rewritten_prompts:
            reads.extend(prompt_alias_reads(prompt, step_order=saved.step_order))
        for read in reads:
            _keep_meaning(
                read,
                reader=saved,
                position=position,
                renumbering=renumbering,
                owner_at=owner_at,
            )
        updates: dict[str, object] = {"step_order": position}
        if "input_bindings" not in item.written_columns:
            updates["input_bindings"] = renumber_input_binding_aliases(
                saved.input_bindings, renumbering
            )
        for column in _CONFIG_COLUMNS:
            if column not in item.written_columns:
                updates[column] = renumber_config_aliases(
                    getattr(saved, column),
                    _channel(column, saved),
                    renumbering,
                )
        untouched = item.step is saved and all(
            getattr(saved, column) == value for column, value in updates.items()
        )
        steps.append(saved if untouched else item.step.model_copy(update=updates))
        if prompt is not None and saved.assistant_id not in rewritten_prompts:
            renumbered = renumber_step_aliases(prompt, renumbering)
            if renumbered != prompt:
                renumbered_prompts[saved.assistant_id] = renumbered
    return StepStructure(steps=steps, renumbered_prompts=renumbered_prompts)


def _saved_reads(saved: FlowStep, *, written: frozenset[str]) -> list[StepAliasRead]:
    reads: list[StepAliasRead] = []
    if "input_bindings" not in written:
        reads.extend(
            input_binding_alias_reads(saved.input_bindings, step_order=saved.step_order)
        )
    for column in _CONFIG_COLUMNS:
        if column not in written:
            reads.extend(config_alias_reads(_channel(column, saved)))
    return reads


def _channel(column: ConfigColumn, saved: FlowStep) -> ConfigChannel | None:
    return config_channel(
        column=column,
        config=getattr(saved, column),
        input_source=FlowInputSource(saved.input_source),
        output_mode=FlowOutputMode(saved.output_mode),
        step_order=saved.step_order,
    )


def _keep_meaning(
    read: StepAliasRead,
    *,
    reader: FlowStep,
    position: int,
    renumbering: Mapping[int, int],
    owner_at: Mapping[int, int | None],
) -> None:
    """``owner_at``: by new position, the saved position of the step there, or
    None for a new step."""

    # The read's channel shows the steps before the reader (or, for a webhook,
    # the reader too), wherever the reader now is.
    visible_below = position + (read.visible_below - reader.step_order)
    if 1 <= read.order < read.visible_below:
        moved_to = owner_position(owner_at, read.order)
        if moved_to is None:
            raise _refusal(reader, read, "reads a step this change removes")
        if moved_to >= visible_below:
            raise _refusal(
                reader,
                read,
                "reads a step this change moves to where it cannot read it",
            )
        return
    # Not a read when saved: it follows its step if that moved, and must not
    # come to name a step the reader can read that it did not name before.
    now = renumbering.get(read.order, read.order)
    if 1 <= now < visible_below and owner_at.get(now, -1) != read.order:
        raise _refusal(
            reader,
            read,
            "would come to read a step it did not read before this change",
        )


def owner_position(owner_at: Mapping[int, int | None], saved_order: int) -> int | None:
    """The new position of the saved step at ``saved_order``, None when the
    change removes it."""

    for position, owner in owner_at.items():
        if owner == saved_order:
            return position
    return None


def _refusal(
    reader: FlowStep, read: StepAliasRead, fate: str
) -> StepReadLostItsProducerError:
    name = reader.user_description or f"Step {reader.step_order}"
    return StepReadLostItsProducerError(
        f"{name} (step {reader.step_order}) {fate}: step {read.order} in its "
        f"{read.site}. Change that read first, or keep each step before the "
        "steps that read it.",
        context={
            "step_id": str(reader.id) if reader.id is not None else None,
            "step_order": reader.step_order,
            "site": read.site,
            "reads_step": read.order,
        },
    )
