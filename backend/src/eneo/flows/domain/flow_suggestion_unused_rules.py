"""Suggestions about data nobody reads, and steps that only pass it on.

``unread_contract_fields``, ``unread_result``, ``relay_step`` and
``unused_form_field``. "Read" is every channel ``DraftReads`` holds, the
configuration included: a template fill or an HTTP request forwards what it
reads even though no model sees it. A step whose reads cannot be computed
counts as reading everything, so these rules then stay silent about the
steps before it.
"""

from __future__ import annotations

from eneo.flows.domain.flow_suggestion_input_rules import contract_fields, mapped_mode
from eneo.flows.domain.flow_suggestion_model import (
    DraftReads,
    FlowSuggestion,
    FlowSuggestionCode,
    FlowSuggestionFix,
    SuggestionStep,
    exact_expression,
    make_suggestion,
    read_premise,
    uses_completion_model,
)
from eneo.flows.domain.flow_suggestion_patches import (
    contract_without_fields_patch,
    form_without_field_patch,
    relay_patch,
    remove_step_patch,
)
from eneo.flows.domain.text_processing import text_processing_config
from eneo.flows.enums import FlowInputSource, FlowOutputMode, FlowOutputType
from eneo.flows.input_binding_contract_rules import (
    has_explicit_underlag,
    question_binding,
    source_ref_bindings,
)
from eneo.flows.step_lineage import (
    INPUT_SOURCE_READ_SITE,
    STRUCTURED_SELECTOR_HEAD,
    StepRead,
)

# A result in these output types is a document the run delivers.
_DOCUMENT_OUTPUT_TYPES = frozenset({FlowOutputType.PDF, FlowOutputType.DOCX})
# A step in these modes does its work outside its result: it posts it, or
# its result is the transcript or the speaker mapping a run keeps.
_UNREAD_RESULT_EXEMPT_MODES = frozenset(
    {
        FlowOutputMode.HTTP_POST,
        FlowOutputMode.TRANSCRIBE_ONLY,
        FlowOutputMode.SPEAKER_MAPPING,
    }
)
_RELAY_MODES = frozenset({FlowOutputMode.COPY_INPUT, FlowOutputMode.COMPOSE_TEXT})


def unread_contract_fields(draft: DraftReads) -> list[FlowSuggestion]:
    """``unread_contract_fields``: top-level fields of an intermediate model
    step's output contract that no later read reaches by path, while no
    later read takes the whole result (its text, its structured value, or
    anything else of it). The fix removes them from the contract, so the
    model stops writing them.

    Not judged: the last step (its result is the flow's output), a step
    with a review policy (the reviewer reads the whole result), a step that
    posts its result or runs mapped or section by section (its contract
    describes more than what later steps read), and a step no later step
    reads at all (``unread_result``)."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        order = step.step_order
        if (
            order >= draft.last_order
            or step.has_review_policy
            or FlowOutputMode(step.output_mode) is not FlowOutputMode.PASS_THROUGH
            or mapped_mode(step) is not None
            or _processes_sections(step)
            or draft.unreadable_after(order)
        ):
            continue
        fields = contract_fields(step)
        readers = draft.readers_of(order)
        if not fields or not readers:
            continue
        if any(
            read.selector[:1] != (STRUCTURED_SELECTOR_HEAD,) or len(read.selector) < 2
            for _, read in readers
        ):
            continue
        read_fields = {read.selector[1] for _, read in readers}
        unread = [name for name in fields if name not in read_fields]
        if not unread or len(unread) == len(fields):
            continue
        patch = contract_without_fields_patch(step, unread)
        suggestions.append(
            make_suggestion(
                FlowSuggestionCode.UNREAD_CONTRACT_FIELDS,
                steps=(step.id,),
                premise={"unread_fields": sorted(unread)},
                params={
                    "fields": unread,
                    "read_fields": [name for name in fields if name in read_fields],
                },
                message=(
                    f"No later step reads the field"
                    f"{'s' if len(unread) > 1 else ''} "
                    f"{', '.join(repr(name) for name in unread)} of step "
                    f"{order}'s result, so its model writes "
                    f"{'them' if len(unread) > 1 else 'it'} for nothing."
                ),
                level="medium",
                fix=(
                    FlowSuggestionFix(kind="patch", patch=patch)
                    if patch is not None
                    else FlowSuggestionFix(kind="assisted")
                ),
            )
        )
    return suggestions


def unread_results(draft: DraftReads) -> list[FlowSuggestion]:
    """``unread_result``: an intermediate step whose result no later step
    reads in any channel. Advice, since the result may be read by people on
    the run page; ``params["remove_patch"]`` is the editor update that
    removes the step, offered as a second choice.

    Not judged: the last step, a step with a review policy, a document
    (pdf, docx), a step that posts its result, transcribes or maps
    speakers, and a step that calls a tool (the call may be the point)."""

    suggestions: list[FlowSuggestion] = []
    for step in draft.steps:
        order = step.step_order
        if (
            order >= draft.last_order
            or step.has_review_policy
            or FlowOutputType(step.output_type) in _DOCUMENT_OUTPUT_TYPES
            or FlowOutputMode(step.output_mode) in _UNREAD_RESULT_EXEMPT_MODES
            or FlowInputSource(step.input_source) is FlowInputSource.TOOL
            or draft.unreadable_after(order)
            or draft.readers_of(order)
        ):
            continue
        suggestions.append(
            make_suggestion(
                FlowSuggestionCode.UNREAD_RESULT,
                steps=(step.id,),
                premise={"read_by": []},
                params={"remove_patch": remove_step_patch(draft.steps, step)},
                message=(
                    f"No later step reads the result of step {order}, so it "
                    "runs on every run without feeding another step or the "
                    "flow's output."
                ),
                level="medium" if uses_completion_model(step) else "low",
                fix=FlowSuggestionFix(kind="advice"),
            )
        )
    return suggestions


def relay_steps(draft: DraftReads) -> list[FlowSuggestion]:
    """``relay_step``: a ``copy_input`` step, or a ``compose_text`` step that
    renders exactly one whole read (its ``previous_step`` input, or a
    question that is one expression), whose result later steps read: they
    could read its source directly. The fix rewrites every read of the relay
    to its source and removes the relay in one editor update
    (``relay_patch``); it is ``assisted`` when a read cannot be rewritten
    mechanically, when the relay copies the run input rather than a step,
    and when the relay overrides its output classification.

    Not judged: a step with a review policy (the review is the point)."""

    suggestions: list[FlowSuggestion] = []
    for relay in draft.steps:
        source = _relay_source(draft, relay)
        if source is None:
            continue
        readers = draft.readers_of(relay.step_order)
        if not readers or draft.unreadable_after(relay.step_order):
            continue
        source_order, source_read = source
        source_step = draft.step_at(source_order) if source_order else None
        patch = (
            relay_patch(draft, relay, source_order)
            if source_step is not None and relay.output_classification_override is None
            else None
        )
        by_reader: dict[int, list[str]] = {}
        for reader, read in readers:
            by_reader.setdefault(reader.step_order, []).append(read.site)
        what = f"step {source_order}" if source_step is not None else "the run input"
        suggestions.append(
            make_suggestion(
                FlowSuggestionCode.RELAY_STEP,
                steps=(relay.id, *((source_step.id,) if source_step else ())),
                # The relay is the finding: which step it passes on follows
                # the steps before it (removing an earlier relay makes it
                # pass on that relay's source), so only whether it passes on
                # a step or the run input, and how it reads it, are premise.
                identity_steps=(relay.id,),
                premise={
                    "source": "step" if source_step is not None else "run_input",
                    "read": read_premise(source_read),
                },
                params={
                    "source_step_order": source_order or None,
                    "source_step_id": str(source_step.id) if source_step else None,
                    "readers": [
                        {
                            "step_order": order,
                            "step_id": str(reader_step.id),
                            "sites": sites,
                        }
                        for order, sites in sorted(by_reader.items())
                        if (reader_step := draft.step_at(order)) is not None
                    ],
                },
                message=(
                    f"Step {relay.step_order} only passes on {what}; the steps "
                    f"that read it could read {what} directly."
                ),
                level="low",
                fix=(
                    FlowSuggestionFix(kind="patch", patch=patch)
                    if patch is not None
                    else FlowSuggestionFix(kind="assisted")
                ),
            )
        )
    return suggestions


def _relay_source(
    draft: DraftReads, step: SuggestionStep
) -> tuple[int, StepRead] | None:
    """What a relay passes on: the order of the step it copies whole (0 for
    the run input) and the read; None when the step is no relay."""
    mode = FlowOutputMode(step.output_mode)
    if (
        mode not in _RELAY_MODES
        or step.has_review_policy
        or step.step_order in draft.unreadable
    ):
        return None
    source = FlowInputSource(step.input_source)
    if source_ref_bindings(step.input_bindings):
        return None
    question = question_binding(step.input_bindings)
    if question is not None and exact_expression(question) is None:
        return None
    reads = [read for read in draft.reads[step.step_order] if read.channel != "config"]
    if not reads:
        if source is FlowInputSource.FLOW_INPUT and not has_explicit_underlag(
            step.input_bindings
        ):
            return 0, StepRead("input", 0, (), INPUT_SOURCE_READ_SITE)
        return None
    if len(reads) != 1 or reads[0].selector not in ((), (STRUCTURED_SELECTOR_HEAD,)):
        return None
    if reads[0].site == INPUT_SOURCE_READ_SITE and source is not (
        FlowInputSource.PREVIOUS_STEP
    ):
        return None
    return reads[0].step_order, reads[0]


def unused_form_fields(draft: DraftReads) -> list[FlowSuggestion]:
    """``unused_form_field``: a field of the run form that no step reads, by
    ``flow_input.<field>`` or its bare name, in any channel, while no step
    takes the whole run input. The fix removes it from
    ``metadata_json.form_schema``. About the form, so about no step."""

    if not draft.form_fields or draft.unreadable or draft.metadata_json is None:
        return []
    read = {
        field_read.field
        for reads in draft.form_field_reads.values()
        for field_read in reads
    }
    suggestions: list[FlowSuggestion] = []
    for field in draft.form_fields:
        if field in read:
            continue
        patch = form_without_field_patch(draft.metadata_json, field)
        suggestions.append(
            make_suggestion(
                FlowSuggestionCode.UNUSED_FORM_FIELD,
                steps=(),
                premise={"field": field},
                params={"field": field},
                message=(
                    f"No step reads the run form field '{field}', so whoever "
                    "starts a run fills it in for nothing."
                ),
                level="low",
                fix=(
                    FlowSuggestionFix(kind="patch", patch=patch)
                    if patch is not None
                    else FlowSuggestionFix(kind="assisted")
                ),
            )
        )
    return suggestions


def _processes_sections(step: SuggestionStep) -> bool:
    try:
        return text_processing_config(dict(step.input_config or {})) is not None
    except ValueError:
        return True


__all__ = [
    "relay_steps",
    "unread_contract_fields",
    "unread_results",
    "unused_form_fields",
]
