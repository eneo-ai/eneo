"""Which step reads what: one typed reader over a step's authoring spec.

Every input the runtime can hand a step is a read: its source refs, its
implicit input, its own upload, and each template reference to a step, a form
field, the run input or the upload. System values (datum, section_index) are
not.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from eneo.flows.domain.runtime_input import build_runtime_input_config
from eneo.flows.flow_authoring_spec import InputSource, InputType, OutputMode, StepSpec
from eneo.flows.flow_run_input_envelope import FLOW_INPUT_TRANSCRIPTION_KEY
from eneo.flows.flow_variable_definitions import (
    FLOW_INPUT_JSON_ALIAS,
    FLOW_INPUT_TEXT_ALIAS,
    PREVIOUS_STEP_TEXT_ALIAS,
)
from eneo.flows.input_binding_contract_rules import (
    SourceRefBinding,
    question_binding,
    source_ref_bindings,
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


_RUN_INPUT_ALIASES = frozenset(
    {FLOW_INPUT_TEXT_ALIAS, FLOW_INPUT_JSON_ALIAS, FLOW_INPUT_TRANSCRIPTION_KEY}
)


def step_template_sites(step: StepSpec) -> list[tuple[ReadSite, str]]:
    """Every template carrier of a step, as text, with the site it is read at."""

    sites = [(ReadSite.INSTRUCTIONS, step.assistant_spec.instructions)]
    for site, payload in (
        (ReadSite.QUESTION, step.input_bindings),
        (ReadSite.OUTPUT_CONFIG, step.output_config),
    ):
        if payload is not None:
            sites.append((site, _template_text(payload)))
    return sites


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
            step_refs.get(ref.step_ref),
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


def _template_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if isinstance(payload, (dict, list)):
        return json.dumps(payload, ensure_ascii=False)
    return str(payload)
