"""Reorder, remove, insert and rename the steps of a draft, and rename or
remove its run form fields, without changing what a kept step reads.

A step reads an earlier step by its alias, ``step_N`` (the producer's
position), or by its name, and a run form field by the field's name. When
steps move or go, the aliases a kept step reads are renumbered with their
producers; when a step or a form field is renamed, the reads of its old name
follow it. This happens in the step's input bindings, in the configuration its
modes interpolate and in its assistant's prompt.

A read that was valid where it was saved refuses the change when the change
would make it name another step, or none: its producer is removed, renamed
away from it or moved to where the reader cannot see it. A read that was not
valid where it was saved (a forward or a dangling one) is written as it
stands, and refuses the change when the change would make it name a step it
could not read before. A form field the change removes refuses it while a kept
step reads it. Columns and prompts the same edit writes are taken as given.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast
from uuid import UUID

from eneo.flows.domain.flow import FlowPersistedJsonObject, FlowStep
from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_authoring_variable_rewriting import (
    StepAliasRead,
    config_alias_reads,
    input_binding_alias_reads,
    prompt_alias_reads,
    renumber_input_binding_aliases,
    renumber_step_aliases,
    rewrite_config_sites,
    rewrite_template_expressions,
)
from eneo.flows.flow_metadata import FlowFormSchemaParseMode, parse_flow_form_schema
from eneo.flows.flow_variable_definitions import can_expose_form_field_bare_alias
from eneo.flows.http_transport.authored_config import ConfigPath
from eneo.flows.input_binding_contract_rules import (
    SOURCE_REFS_BINDING_KEY,
    source_ref_step_order,
)
from eneo.flows.step_lineage import (
    ConfigChannel,
    ConfigColumn,
    build_step_ref_mapping,
    config_channel,
)
from eneo.main.exceptions import BadRequestException

_CONFIG_COLUMNS: tuple[ConfigColumn, ...] = ("input_config", "output_config")
# The columns of a step that hold reads of other steps and of form fields.
READ_COLUMNS: tuple[str, ...] = ("input_bindings", *_CONFIG_COLUMNS)
# A name a template can read: the resolver splits an expression at its dots.
_TEMPLATE_NAME_BREAKERS = frozenset(".{}")


class StepReadLostProducerReason(StrEnum):
    """Why a change would make a kept step read another step than it does."""

    PRODUCER_REMOVED = "producer_removed"
    PRODUCER_MOVED_AFTER_READER = "producer_moved_after_reader"
    READER_MOVED_BEFORE_PRODUCER = "reader_moved_before_producer"
    PRODUCER_RENAMED = "producer_renamed"
    WOULD_READ_ANOTHER_STEP = "would_read_another_step"


class StepReadLostItsProducerError(BadRequestException):
    """A kept step would read another step than the one it reads now."""

    def __init__(self, message: str, *, context: dict[str, object]) -> None:
        super().__init__(
            message,
            code=FlowApiErrorCode.STEP_READ_LOST_PRODUCER.value,
            context=context,
        )


class FormFieldStillReadError(BadRequestException):
    """The change removes a run form field that a kept step reads."""

    def __init__(self, message: str, *, context: dict[str, object]) -> None:
        super().__init__(
            message,
            code=FlowApiErrorCode.FORM_FIELD_STILL_READ.value,
            context=context,
        )


class FormFieldRenameInvalidError(BadRequestException):
    """``form_field_renames`` does not describe the form the change saves."""

    def __init__(self, message: str, *, context: dict[str, object]) -> None:
        super().__init__(
            message,
            code=FlowApiErrorCode.FORM_FIELD_RENAME_INVALID.value,
            context=context,
        )


@dataclass(frozen=True, slots=True)
class FormFieldChange:
    """The run form fields saved before the change, those it renames (saved
    name to new) and those it removes."""

    saved: frozenset[str]
    renamed: Mapping[str, str] = field(default_factory=dict[str, str])
    removed: frozenset[str] = frozenset()

    @property
    def changes_reads(self) -> bool:
        return bool(self.renamed or self.removed)


def form_field_names(metadata_json: Mapping[str, object] | None) -> frozenset[str]:
    """The names of the run form's fields, as a run reads them."""

    schema = parse_flow_form_schema(
        cast(FlowPersistedJsonObject | None, metadata_json),
        mode=FlowFormSchemaParseMode.PERSISTED_READ,
    )
    if schema is None:
        return frozenset()
    return frozenset(name for item in schema.fields if (name := item.name.strip()))


def form_field_change(
    *,
    saved_metadata: Mapping[str, object] | None,
    metadata: Mapping[str, object] | None,
    renames: Mapping[str, str] | None = None,
) -> FormFieldChange:
    """What saving ``metadata`` over ``saved_metadata`` does to the run form's
    fields. ``renames`` names each field the change renames, from its saved
    name to its new one; a saved field the new form does not have and
    ``renames`` does not name is removed."""

    saved = form_field_names(saved_metadata)
    current = form_field_names(metadata)
    renamed = {
        old.strip(): new.strip()
        for old, new in (renames or {}).items()
        if old.strip() != new.strip()
    }
    targets = list(renamed.values())
    for old, new in renamed.items():
        problem = None
        if old not in saved:
            problem = "unknown_field"
        elif new not in current:
            problem = "not_in_form"
        elif old in current and old not in targets:
            problem = "still_in_form"
        elif new in saved and new not in renamed:
            problem = "name_taken"
        elif targets.count(new) > 1:
            problem = "renamed_twice"
        if problem is not None:
            raise FormFieldRenameInvalidError(
                f"form_field_renames renames '{old}' to '{new}', which the form "
                f"does not allow ({problem}). Rename each saved field once, to "
                "its name in metadata_json.form_schema.",
                context={"from": old, "to": new, "problem": problem},
            )
    return FormFieldChange(
        saved=saved,
        renamed=renamed,
        removed=frozenset(saved - current - renamed.keys()),
    )


@dataclass(frozen=True, slots=True)
class PlacedStep:
    """A step at its place in the new order: a saved step (``saved``) or a new
    one. ``step`` holds the columns the edit writes for it; for a saved step
    ``written_columns`` names them, and every other column is the saved one.
    ``prompt_written``: the edit writes the prompt this step reads, as given,
    and no other step's."""

    step: FlowStep
    saved: FlowStep | None = None
    written_columns: frozenset[str] = frozenset()
    prompt_written: bool = False


@dataclass(frozen=True, slots=True)
class StepStructure:
    """The steps in their new order, numbered from 1; the prompts whose reads
    followed the change (by assistant); and what they followed
    (``step_order_changed``, ``step_renamed``, ``form_field_renamed``)."""

    steps: list[FlowStep]
    changed_prompts: dict[UUID, str]
    causes: frozenset[str] = frozenset()


def restructure_steps(
    placed: Sequence[PlacedStep],
    *,
    prompts: Mapping[UUID, str],
    rewritten_prompts: frozenset[UUID] = frozenset(),
    saved_steps: Sequence[FlowStep] | None = None,
    form_fields: FormFieldChange | None = None,
) -> StepStructure:
    """``placed`` in their new order; ``prompts`` the saved prompt of each
    kept step's assistant, and ``rewritten_prompts`` the assistants whose
    prompt the same edit writes, as given. ``saved_steps`` are all steps as
    saved, the ones the change removes included (by default the kept ones);
    ``form_fields`` what the change does to the run form."""

    owner_at = {
        index + 1: (item.saved.step_order if item.saved is not None else None)
        for index, item in enumerate(placed)
    }
    change = _Change(
        owner_at=owner_at,
        renumbering={
            saved: position
            for position, saved in owner_at.items()
            if saved is not None and saved != position
        },
        names=_Names.of(
            placed,
            saved_steps
            if saved_steps is not None
            else [item.saved for item in placed if item.saved is not None],
        ),
        form_fields=form_fields or FormFieldChange(saved=frozenset()),
    )
    steps: list[FlowStep] = []
    changed_prompts: dict[UUID, str] = {}
    for index, item in enumerate(placed):
        position = index + 1
        saved = item.saved
        if saved is None:
            steps.append(item.step.model_copy(update={"step_order": position}))
            continue
        written = item.written_columns
        # A step given another assistant reads that assistant's prompt, which
        # the step did not read where it was saved.
        prompt = (
            prompts.get(saved.assistant_id)
            if saved.assistant_id not in rewritten_prompts
            and not item.prompt_written
            and item.step.assistant_id == saved.assistant_id
            else None
        )
        reads = _saved_reads(saved, written=written)
        if prompt is not None:
            reads.extend(prompt_alias_reads(prompt, step_order=saved.step_order))
        for read in reads:
            change.keep_alias_meaning(read, reader=saved, position=position)
        follow = _Follower(change, reader=saved, position=position)
        updates: dict[str, object] = {"step_order": position}
        if "input_bindings" not in written:
            updates["input_bindings"] = follow.input_bindings(
                renumber_input_binding_aliases(
                    item.step.input_bindings, change.renumbering
                )
            )
        for column in _CONFIG_COLUMNS:
            if column not in written:
                updates[column] = follow.config(
                    getattr(item.step, column), _channel(column, saved)
                )
        untouched = item.step is saved and all(
            getattr(saved, column) == value for column, value in updates.items()
        )
        steps.append(saved if untouched else item.step.model_copy(update=updates))
        if prompt is not None:
            followed = follow.template(
                renumber_step_aliases(prompt, change.renumbering),
                site="prompt",
                visible_below=saved.step_order,
            )
            if followed != prompt:
                changed_prompts[saved.assistant_id] = followed
    change.refuse_removed_form_field_reads()
    return StepStructure(
        steps=steps, changed_prompts=changed_prompts, causes=change.causes()
    )


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


def owner_position(owner_at: Mapping[int, int | None], saved_order: int) -> int | None:
    """The new position of the saved step at ``saved_order``, None when the
    change removes it."""

    for position, owner in owner_at.items():
        if owner == saved_order:
            return position
    return None


def _template_name(name: str | None) -> str | None:
    """``name`` as a template reads it, None when no template can: a blank
    name, or one the resolver would split at a dot."""

    stripped = (name or "").strip()
    if not stripped or _TEMPLATE_NAME_BREAKERS & set(stripped):
        return None
    return stripped


@dataclass(frozen=True, slots=True)
class _Names:
    """Step names as reads resolve them: by name, the saved order of the step
    it named before the change and the position of the step it names after."""

    before: Mapping[str, int]
    after: Mapping[str, int]
    # By saved order, the name each kept step has after the change.
    new_names: Mapping[int, str | None]

    @classmethod
    def of(
        cls, placed: Sequence[PlacedStep], saved_steps: Sequence[FlowStep]
    ) -> _Names:
        return cls(
            before=build_step_ref_mapping(
                {
                    "step_order": step.step_order,
                    "user_description": step.user_description,
                }
                for step in saved_steps
            ),
            after=build_step_ref_mapping(
                {
                    "step_order": index + 1,
                    "user_description": item.step.user_description,
                }
                for index, item in enumerate(placed)
            ),
            new_names={
                item.saved.step_order: (item.step.user_description or "").strip()
                or None
                for item in placed
                if item.saved is not None
            },
        )

    def renamed(self) -> bool:
        return any(
            order in self.new_names and self.new_names[order] != name
            for name, order in self.before.items()
        )


@dataclass(slots=True)
class _Change:
    owner_at: Mapping[int, int | None]
    renumbering: Mapping[int, int]
    names: _Names
    form_fields: FormFieldChange
    removed_field_readers: list[dict[str, object]] = field(
        default_factory=list[dict[str, object]]
    )

    def causes(self) -> frozenset[str]:
        causes: set[str] = set()
        if self.renumbering:
            causes.add("step_order_changed")
        if self.names.renamed():
            causes.add("step_renamed")
        if self.form_fields.renamed:
            causes.add("form_field_renamed")
        return frozenset(causes)

    def keep_alias_meaning(
        self, read: StepAliasRead, *, reader: FlowStep, position: int
    ) -> None:
        # The read's channel shows the steps before the reader (or, for a
        # webhook, the reader too), wherever the reader now is.
        visible_below = position + (read.visible_below - reader.step_order)
        if 1 <= read.order < read.visible_below:
            moved_to = owner_position(self.owner_at, read.order)
            if moved_to is None:
                raise _refusal(
                    reader,
                    read.site,
                    read.order,
                    StepReadLostProducerReason.PRODUCER_REMOVED,
                )
            if moved_to >= visible_below:
                raise _refusal(
                    reader,
                    read.site,
                    read.order,
                    _moved_reason(reader, position, read.order, moved_to),
                )
            return
        # Not a read when saved: it follows its step if that moved, and must
        # not come to name a step the reader can read that it did not name.
        now = self.renumbering.get(read.order, read.order)
        if 1 <= now < visible_below and self.owner_at.get(now, -1) != read.order:
            raise _refusal(
                reader,
                read.site,
                read.order,
                StepReadLostProducerReason.WOULD_READ_ANOTHER_STEP,
            )

    def follow_name(
        self,
        name: str,
        *,
        reader: FlowStep,
        position: int,
        site: str,
        visible_below: int,
        readable: Callable[[str | None], str | None],
    ) -> str:
        """The name a by-name read of ``name`` is written with after the
        change: the new name of its step when it has one a read can use."""

        named = self.names.before[name]
        moved_to = owner_position(self.owner_at, named)
        written = name
        if moved_to is not None:
            new_name = readable(self.names.new_names.get(named))
            if new_name is not None:
                written = new_name
        target = self.names.after.get(written)
        same_step = target is not None and self.owner_at.get(target) == named
        visible_below_now = position + (visible_below - reader.step_order)

        def refuse(reason: StepReadLostProducerReason) -> StepReadLostItsProducerError:
            return _refusal(reader, site, named, reason, name=name)

        if named < visible_below:
            if moved_to is None:
                raise refuse(StepReadLostProducerReason.PRODUCER_REMOVED)
            if not same_step:
                raise refuse(StepReadLostProducerReason.PRODUCER_RENAMED)
            if cast(int, target) >= visible_below_now:
                raise refuse(_moved_reason(reader, position, named, cast(int, target)))
        elif target is not None and target < visible_below_now and not same_step:
            raise refuse(StepReadLostProducerReason.WOULD_READ_ANOTHER_STEP)
        return written

    def follow_field(self, name: str, *, reader: FlowStep, site: str) -> str | None:
        """The new name of a form field the change renames; None when it
        keeps it. A read of a field the change removes is recorded."""

        renamed = self.form_fields.renamed.get(name)
        if renamed is None and name in self.form_fields.removed:
            self.removed_field_readers.append(
                {
                    "field": name,
                    "step_id": str(reader.id) if reader.id is not None else None,
                    "step_order": reader.step_order,
                    "step_name": reader.user_description,
                    "site": site,
                }
            )
        return renamed

    def refuse_removed_form_field_reads(self) -> None:
        readers = self.removed_field_readers
        if not readers:
            return
        fields = sorted({str(reader["field"]) for reader in readers})
        where = "; ".join(
            f"{reader['step_name'] or 'Step ' + str(reader['step_order'])} "
            f"(step {reader['step_order']}) reads '{reader['field']}' in its "
            f"{reader['site']}"
            for reader in readers
        )
        raise FormFieldStillReadError(
            f"This change removes the form field{'s' if len(fields) > 1 else ''} "
            f"{', '.join(repr(name) for name in fields)}, which steps still read: "
            f"{where}. Change those reads first, or rename the field with "
            "form_field_renames so they follow it.",
            context={
                "fields": fields,
                "readers": [
                    {key: value for key, value in reader.items() if key != "step_name"}
                    for reader in readers
                ],
            },
        )


class _Follower:
    """Rewrites the by-name and form field reads of one kept step so they
    follow the change, and refuses the change for those that cannot."""

    def __init__(self, change: _Change, *, reader: FlowStep, position: int) -> None:
        self._change = change
        self._reader = reader
        self._position = position

    def template(self, text: str, *, site: str, visible_below: int) -> str:
        change = self._change

        def rewrite(expression: str) -> str | None:
            segments = expression.split(".")
            head = segments[0].strip()
            if head in change.names.before:
                written = change.follow_name(
                    head,
                    reader=self._reader,
                    position=self._position,
                    site=site,
                    visible_below=visible_below,
                    readable=_template_name,
                )
                return _with_segment(segments, 0, written)
            index = _form_field_segment(
                segments, change.form_fields.saved, change.names.before
            )
            if index is None:
                return None
            renamed = change.follow_field(
                segments[index].strip(), reader=self._reader, site=site
            )
            if renamed is None:
                return None
            if index == 0 and not can_expose_form_field_bare_alias(renamed):
                renamed = f"flow_input.{renamed}"
            return _with_segment(segments, index, renamed)

        if not change.names.before and not change.form_fields.changes_reads:
            return text
        return rewrite_template_expressions(text, rewrite)

    def input_bindings(
        self, bindings: FlowPersistedJsonObject | None
    ) -> FlowPersistedJsonObject | None:
        if not bindings:
            return bindings
        result: dict[str, Any] = dict(bindings)
        question = result.get("question")
        if isinstance(question, str):
            result["question"] = self.template(
                question,
                site="input_bindings.question",
                visible_below=self._reader.step_order,
            )
        source_refs = result.get(SOURCE_REFS_BINDING_KEY)
        if isinstance(source_refs, list):
            result[SOURCE_REFS_BINDING_KEY] = [
                self._source_ref(index, item)
                for index, item in enumerate(cast(list[Any], source_refs))
            ]
        return bindings if result == bindings else result

    def _source_ref(self, index: int, item: Any) -> Any:
        if not isinstance(item, dict):
            return item
        payload = cast(dict[str, Any], item)
        step_ref = payload.get("step_ref")
        if (
            not isinstance(step_ref, str)
            or source_ref_step_order(step_ref) is not None
            or step_ref not in self._change.names.before
        ):
            return payload
        written = self._change.follow_name(
            step_ref,
            reader=self._reader,
            position=self._position,
            site=f"input_bindings.{SOURCE_REFS_BINDING_KEY}[{index}].step_ref",
            visible_below=self._reader.step_order,
            readable=lambda name: (name or "").strip() or None,
        )
        return payload if written == step_ref else {**payload, "step_ref": written}

    def config(self, config: Any, channel: ConfigChannel | None) -> Any:
        if channel is None or channel.sites is None:
            return config
        change = self._change

        def rewrite(path: ConfigPath, text: str) -> str:
            return self.template(
                renumber_step_aliases(text, change.renumbering),
                site=channel.column
                + "".join(
                    f"[{part}]" if isinstance(part, int) else f".{part}"
                    for part in path
                ),
                visible_below=channel.context_step_order,
            )

        return rewrite_config_sites(config, channel, rewrite)


def _form_field_segment(
    segments: Sequence[str], fields: frozenset[str], step_names: Mapping[str, int]
) -> int | None:
    """Which segment of an expression names a run form field: the one after
    ``flow_input``, after ``flow.input``, or a field's bare name."""

    if not fields:
        return None
    parts = [segment.strip() for segment in segments]
    if parts[0] == "flow_input" and len(parts) > 1 and parts[1] in fields:
        return 1
    if (
        parts[0] == "flow"
        and len(parts) > 2
        and parts[1] == "input"
        and parts[2] in fields
    ):
        return 2
    if (
        parts[0] in fields
        and parts[0] not in step_names
        and can_expose_form_field_bare_alias(parts[0])
    ):
        return 0
    return None


def _with_segment(segments: Sequence[str], index: int, value: str) -> str:
    """The expression with segment ``index`` replaced by ``value``, keeping the
    spaces the author put around it."""

    segment = segments[index]
    leading = segment[: len(segment) - len(segment.lstrip())]
    trailing = segment[len(segment.rstrip()) :]
    return ".".join(
        [*segments[:index], f"{leading}{value}{trailing}", *segments[index + 1 :]]
    )


def _moved_reason(
    reader: FlowStep, position: int, producer_order: int, producer_position: int
) -> StepReadLostProducerReason:
    """Which of the two steps the change moved: the one that moved farther."""

    reader_moved = abs(position - reader.step_order)
    producer_moved = abs(producer_position - producer_order)
    return (
        StepReadLostProducerReason.READER_MOVED_BEFORE_PRODUCER
        if reader_moved > producer_moved
        else StepReadLostProducerReason.PRODUCER_MOVED_AFTER_READER
    )


_FATES = {
    StepReadLostProducerReason.PRODUCER_REMOVED: "reads a step this change removes",
    StepReadLostProducerReason.PRODUCER_MOVED_AFTER_READER: (
        "reads a step this change moves to where it cannot read it"
    ),
    StepReadLostProducerReason.READER_MOVED_BEFORE_PRODUCER: (
        "would move before a step it reads"
    ),
    StepReadLostProducerReason.PRODUCER_RENAMED: (
        "reads a step by a name this change takes from it"
    ),
    StepReadLostProducerReason.WOULD_READ_ANOTHER_STEP: (
        "would come to read a step it did not read before this change"
    ),
}


def _refusal(
    reader: FlowStep,
    site: str,
    reads_step: int,
    reason: StepReadLostProducerReason,
    *,
    name: str | None = None,
) -> StepReadLostItsProducerError:
    label = reader.user_description or f"Step {reader.step_order}"
    read = f"'{name}' (step {reads_step})" if name is not None else f"step {reads_step}"
    context: dict[str, object] = {
        "step_id": str(reader.id) if reader.id is not None else None,
        "step_order": reader.step_order,
        "site": site,
        "reads_step": reads_step,
        "reason": reason.value,
    }
    if name is not None:
        context["reads_name"] = name
    return StepReadLostItsProducerError(
        f"{label} (step {reader.step_order}) {_FATES[reason]}: {read} in its "
        f"{site}. Change that read first, or keep each step before the steps "
        "that read it.",
        context=context,
    )
