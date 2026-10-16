"""Which step reads what: one typed reader over a step's authoring spec.

Every input the runtime can hand a step is a read: its source refs, its
implicit input, its own upload, and each template reference to a step, a form
field, the run input or the upload. System values (datum, section_index) are
not.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import cast

from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_authoring_spec import InputSource, InputType, OutputMode, StepSpec
from eneo.flows.flow_authoring_variable_rewriting import renumber_step_aliases
from eneo.flows.flow_run_input_envelope import FLOW_INPUT_TRANSCRIPTION_KEY
from eneo.flows.flow_variable_definitions import (
    FLOW_INPUT_ALIASES,
    PREVIOUS_STEP_TEXT_ALIAS,
)
from eneo.flows.input_binding_contract_rules import (
    SourceRefBinding,
    question_binding,
    source_ref_bindings,
    source_ref_step_order,
)
from eneo.flows.step_lineage import (
    ConfigChannel,
    ConfigColumn,
    build_step_ref_mapping,
    config_channel,
)
from eneo.flows.template_reference_analyzer import (
    TemplateReference,
    TemplateReferenceKind,
    analyze_template,
)


class ReadChannel(StrEnum):
    TEXT = "text"
    STRUCTURED = "structured"
    # The producer's structured output when it is an object or list, else its
    # text: what a JSON-input step's implicit previous_step read receives.
    STRUCTURED_ELSE_TEXT = "structured_else_text"
    # A step's status, error message, or any other non-output path.
    STEP_OTHER = "step_other"
    FORM_FIELD = "form_field"
    RUN_INPUT = "run_input"
    # Read by alias name, never by payload key: indata_text exists only for
    # non-blank text, indata_json falls back to `structured`, and transkribering
    # takes the first transcript key present.
    RUN_INPUT_ALIAS = "run_input_alias"
    # The text and files uploaded to this step: step_input.*, or the whole
    # upload when read implicitly.
    STEP_INPUT = "step_input"


class ReadSite(StrEnum):
    IMPLICIT = "implicit"
    SOURCE_REF = "source_ref"
    # Anywhere in input_bindings; the question is the only templated key.
    QUESTION = "question"
    INSTRUCTIONS = "instructions"
    # A tool step's bound arguments.
    INPUT_CONFIG = "input_config"
    OUTPUT_CONFIG = "output_config"


@dataclass(frozen=True, slots=True)
class StepRead:
    """One read, compared by what is read and where; not by how it was written.

    `producer_order` is the 1-based order of the step read; None when the read
    names no step order (a form field, the run input, an unknown step name,
    föregående_steg on the first step). `path` is the structured path, the
    form field, the run-input key, the alias and its path, or the step_input key.
    """

    producer_order: int | None
    channel: ReadChannel
    path: tuple[str, ...]
    site: ReadSite
    # The producer is chosen by position (the implicit chain, föregående_steg).
    positional: bool = field(default=False, compare=False)
    # The source ref (with its label and item_template), or the template expression.
    origin: SourceRefBinding | str | None = field(default=None, compare=False)

    @property
    def reads_whole_run_input(self) -> bool:
        """The whole run payload, as {{ flow_input }} or wrapped as {{ flow }}."""

        return (self.channel is ReadChannel.RUN_INPUT and not self.path) or (
            self.channel is ReadChannel.RUN_INPUT_ALIAS and self.path == ("flow",)
        )


_RUN_INPUT_ALIASES = FLOW_INPUT_ALIASES | {FLOW_INPUT_TRANSCRIPTION_KEY}


def step_config_channel(step: StepSpec, column: ConfigColumn) -> ConfigChannel | None:
    """The strings of one config column of a step the runtime interpolates for
    its modes, found by the owner the platform uses, None when it interpolates
    none: any other key is literal text. The authoring modes have no delivery,
    so the step's order does not matter here."""

    return config_channel(
        column=column,
        config=step.input_config if column == "input_config" else step.output_config,
        input_source=FlowInputSource(step.input_source.value),
        output_mode=FlowOutputMode(step.output_mode.value),
        step_order=1,
    )


def step_template_sites(step: StepSpec) -> list[tuple[ReadSite, str]]:
    """Every template carrier of a step, as text, with the site it is read at."""

    sites = [(ReadSite.INSTRUCTIONS, step.assistant_spec.instructions)]
    sites.extend(
        (ReadSite.QUESTION, text) for text in _binding_strings(step.input_bindings)
    )
    for site, column in _CONFIG_SITES:
        channel = step_config_channel(step, column)
        if channel is not None and channel.sites is not None:
            sites.extend((site, text) for _, text in channel.sites)
    return sites


_CONFIG_SITES: tuple[tuple[ReadSite, ConfigColumn], ...] = (
    (ReadSite.INPUT_CONFIG, "input_config"),
    (ReadSite.OUTPUT_CONFIG, "output_config"),
)


def run_step_names(steps: Sequence[tuple[str | None, str]]) -> dict[str, int]:
    """The step names the run binds, to their 1-based order: `steps` is the
    flow in run order as (saved ref, name)."""

    return build_step_ref_mapping(
        {"step_order": order, "user_description": name}
        for order, (_, name) in enumerate(steps, 1)
    )


def kept_step_read_producers(
    step: StepSpec,
    steps: Sequence[tuple[str | None, str]],
    names: Mapping[str, int],
    renumbering: Mapping[int, int],
    *,
    excluded_sites: frozenset[ReadSite] = frozenset(),
) -> tuple[str | None, ...]:
    """Which listed step each step read at every template site of `step`
    (step_template_sites) but `excluded_sites` names when the flow runs, by
    that step's saved ref: None for a step an edit adds or a read that names
    no listed step. `steps` is the flow in run order as (saved ref, name),
    `names` its run_step_names, and `renumbering` the step_N aliases the
    apply rewrites (saved position to new).

    Read as the run binds it (variable_resolver): a step_N alias by position
    and a step's name to that step's text (a step may not be named like a
    runtime variable or an alias). No compiler ref takes part, so a step named
    like one is read by its name."""

    return tuple(
        steps[order - 1][0]
        if (order := reference.step_order) is not None and 1 <= order <= len(steps)
        else None
        for site, text in step_template_sites(step)
        if site not in excluded_sites
        for reference in analyze_template(
            renumber_step_aliases(text, renumbering),
            step_refs=dict(names),
            form_field_names=set(),
        )
        if reference.kind is TemplateReferenceKind.STEP
    )


def spec_step_refs(steps: Sequence[StepSpec]) -> dict[str, int]:
    """Every name a step of an authoring spec is read by, to its 1-based order:
    its plan ref, its saved ref and its runtime alias (step_<order>)."""

    return {
        ref: order
        for order, step in enumerate(steps, 1)
        for ref in (step.plan_step_ref, step.existing_step_ref, f"step_{order}")
        if ref is not None
    }


def step_reads(
    step: StepSpec,
    *,
    order: int,
    step_refs: dict[str, int],
    form_field_names: set[str],
) -> tuple[StepRead, ...]:
    """What `step` reads, in order: source refs, templates by site, the implicit input.

    `order` is the step's 1-based position; `step_refs` maps every name a step
    can be referenced by to its order. Explicit underlag (a question or source
    refs) replaces the implicit chain, and so does transcribing a required
    audio upload; the step's own upload is read either way.
    """

    source_refs = source_ref_bindings(step.input_bindings)
    reads = [
        StepRead(
            source_ref_step_order(ref.step_ref, step_refs),
            ReadChannel.TEXT if ref.output == "text" else ReadChannel.STRUCTURED,
            ref.field_path,
            ReadSite.SOURCE_REF,
            origin=ref,
        )
        for ref in source_refs
    ]
    for site, template in step_template_sites(step):
        for reference in analyze_template(
            template, step_refs=step_refs, form_field_names=form_field_names
        ):
            read = _template_read(reference, site=site, order=order)
            if read is not None:
                reads.append(read)
    runtime_input = build_runtime_input_config(step.input_config)
    transcribes_audio_upload = (
        runtime_input.enabled
        and runtime_input.required
        and runtime_input.input_format == "audio"
        and step.output_mode == OutputMode.TRANSCRIBE_ONLY
    )
    if (
        not source_refs
        and question_binding(step.input_bindings) is None
        and not transcribes_audio_upload
    ):
        reads.extend(_implicit_reads(step, order=order))
    if runtime_input.enabled:
        reads.append(StepRead(None, ReadChannel.STEP_INPUT, (), ReadSite.IMPLICIT))
    return tuple(reads)


# What a run is started with, on a flow that declares no form fields: its
# text or payload, an alias of it, a step's own upload.
_RUN_INPUT_CHANNELS = frozenset(
    {ReadChannel.RUN_INPUT, ReadChannel.RUN_INPUT_ALIAS, ReadChannel.STEP_INPUT}
)


def no_step_reads_run_input(steps: Sequence[StepSpec]) -> bool:
    """Whether, on a flow that declares no form fields, every step's reads are
    known and none is of what a run is started with, at any site `step_reads`
    enumerates (a tool argument bound to {{flow_input.text}} too). A
    configuration that cannot be read is unknown, never "reads nothing"."""

    if any(_has_unreadable_config(step) for step in steps):
        return False
    step_refs = spec_step_refs(steps)
    return not any(
        read.channel in _RUN_INPUT_CHANNELS
        for order, step in enumerate(steps, 1)
        for read in step_reads(
            step, order=order, step_refs=step_refs, form_field_names=set()
        )
    )


def _has_unreadable_config(step: StepSpec) -> bool:
    return any(
        channel is not None and channel.sites is None
        for channel in (
            step_config_channel(step, column) for _, column in _CONFIG_SITES
        )
    )


def form_fields_read(
    step: StepSpec,
    *,
    order: int,
    step_refs: dict[str, int],
    form_field_names: set[str],
) -> frozenset[str]:
    """The form fields a step reads at any site `step_reads` enumerates (its
    question, instructions, output mapping) and by reading the whole run input.
    The one answer to "does this step read that field", so no site is missed."""

    names: set[str] = set()
    for read in step_reads(
        step, order=order, step_refs=step_refs, form_field_names=form_field_names
    ):
        if read.channel is ReadChannel.FORM_FIELD:
            names.add(read.path[0])
        elif read.reads_whole_run_input:
            names.update(form_field_names)
    return frozenset(names)


def _implicit_reads(step: StepSpec, *, order: int) -> list[StepRead]:
    if step.input_source == InputSource.FLOW_INPUT:
        # The run's text, or its semantic payload when there is no text.
        return [StepRead(None, ReadChannel.RUN_INPUT, (), ReadSite.IMPLICIT)]
    if step.input_source == InputSource.PREVIOUS_STEP and order > 1:
        channel = (
            ReadChannel.STRUCTURED_ELSE_TEXT
            if step.input_type == InputType.JSON
            else ReadChannel.TEXT
        )
        return [StepRead(order - 1, channel, (), ReadSite.IMPLICIT, positional=True)]
    if step.input_source == InputSource.ALL_PREVIOUS_STEPS:
        return [
            StepRead(producer, ReadChannel.TEXT, (), ReadSite.IMPLICIT, positional=True)
            for producer in range(1, order)
        ]
    return []


def _template_read(
    reference: TemplateReference, *, site: ReadSite, order: int
) -> StepRead | None:
    expression = reference.expression
    if reference.head == PREVIOUS_STEP_TEXT_ALIAS:
        return StepRead(
            order - 1 if order > 1 else None,
            ReadChannel.TEXT,
            (),
            site,
            positional=True,
            origin=expression,
        )
    if reference.kind is TemplateReferenceKind.STEP:
        channel, path = _step_output_read(reference)
        return StepRead(reference.step_order, channel, path, site, origin=expression)
    if reference.kind is TemplateReferenceKind.FORM_FIELD:
        field_path = (reference.head, *_segments(reference.tail))
    elif reference.form_field_name is not None:
        # flow_input.<field>... or flow.input.<field>...: drop the prefix by position.
        segments = _segments(reference.tail)
        field_path = segments[1:] if reference.head == "flow" else segments
    else:
        field_path = None
    if field_path is not None:
        return StepRead(
            None, ReadChannel.FORM_FIELD, field_path, site, origin=expression
        )
    runtime_read = _runtime_read(reference)
    if runtime_read is None:
        return None
    channel, path = runtime_read
    return StepRead(None, channel, path, site, origin=expression)


def _step_output_read(
    reference: TemplateReference,
) -> tuple[ReadChannel, tuple[str, ...]]:
    if reference.tail == "output.text":
        return ReadChannel.TEXT, ()
    if reference.tail == "output.structured":
        return ReadChannel.STRUCTURED, ()
    if reference.structured_path is not None:
        return ReadChannel.STRUCTURED, reference.structured_path
    return ReadChannel.STEP_OTHER, _segments(reference.tail)


def _runtime_read(
    reference: TemplateReference,
) -> tuple[ReadChannel, tuple[str, ...]] | None:
    if reference.kind is not TemplateReferenceKind.RUNTIME:
        return None
    head, segments = reference.head, _segments(reference.tail)
    if head in _RUN_INPUT_ALIASES:
        return ReadChannel.RUN_INPUT_ALIAS, (head, *segments)
    if head == "step_input":
        return ReadChannel.STEP_INPUT, segments
    if head == "flow_input":
        return ReadChannel.RUN_INPUT, segments
    if head == "flow" and not segments:
        # {{ flow }} renders {"input": payload}, not the payload itself.
        return ReadChannel.RUN_INPUT_ALIAS, ("flow",)
    if head == "flow" and segments[0] == "input":
        return ReadChannel.RUN_INPUT, segments[1:]
    return None


def _segments(tail: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in tail.split(".")) if tail else ()


def _binding_strings(value: object) -> Iterator[str]:
    """Every string in the bindings as stored: the runtime interpolates the
    strings themselves, so an encoding (an escaped newline) must not change
    what a reference reads."""

    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in cast(Mapping[str, object], value).values():
            yield from _binding_strings(item)
    elif isinstance(value, list):
        for item in cast(list[object], value):
            yield from _binding_strings(item)
