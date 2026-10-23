from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias, TypeGuard, cast

from pydantic import ValidationError

from eneo.flows.domain.tool_input import tool_reference_sites
from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_variable_definitions import PREVIOUS_STEP_TEXT_ALIAS
from eneo.flows.http_transport import (
    HTTP_CONFIG_KEYS,
    HttpAuthoredConfig,
    is_authored_config,
    sends_http_config,
)
from eneo.flows.http_transport.authored_config import ConfigPath
from eneo.flows.input_binding_contract_rules import (
    effective_question_binding,
    question_binding,
    source_ref_bindings,
)
from eneo.flows.template_reference_analyzer import (
    TemplateReference,
    analyze_template,
    referenced_form_fields,
)
from eneo.flows.variable_resolver import decimal_number


class _StepReferenceFields(Protocol):
    @property
    def step_order(self) -> int: ...

    @property
    def plan_step_ref(self) -> str | None: ...

    @property
    def existing_step_ref(self) -> str | None: ...

    @property
    def user_description(self) -> str | None: ...


_StepReferenceSource: TypeAlias = Mapping[str, object] | _StepReferenceFields
_EXISTING_STEP_REF_PREFIX = "existing_step_"


def existing_step_ref_for_order(step_order: int) -> str:
    if step_order < 1:
        raise ValueError("Existing step refs are 1-based.")
    return f"{_EXISTING_STEP_REF_PREFIX}{step_order}"


def existing_step_order_from_ref(existing_step_ref: str | None) -> int | None:
    if existing_step_ref is None or not existing_step_ref.startswith(
        _EXISTING_STEP_REF_PREFIX
    ):
        return None
    raw_order = existing_step_ref.removeprefix(_EXISTING_STEP_REF_PREFIX)
    step_order = decimal_number(raw_order)
    # Reject non-canonical aliases such as existing_step_01.
    if step_order is None or raw_order != str(step_order):
        return None
    return step_order if step_order >= 1 else None


def build_step_ref_mapping(steps: Iterable[_StepReferenceSource]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    display_labels: list[tuple[str, int]] = []
    for step in steps:
        step_order = _step_order(step)
        if not _is_step_order(step_order):
            continue
        for key in ("plan_step_ref", "existing_step_ref"):
            raw_ref = _step_ref(step, key)
            if isinstance(raw_ref, str) and raw_ref.strip():
                mapping[raw_ref.strip()] = step_order
        raw_label = _step_ref(step, "user_description")
        if isinstance(raw_label, str) and raw_label.strip():
            display_labels.append((raw_label.strip(), step_order))
    display_labels.sort(key=lambda item: item[1])
    for display_label, step_order in display_labels:
        mapping.setdefault(display_label, step_order)
    return mapping


def resolve_upstream_step_orders(
    *,
    input_source: FlowInputSource | str,
    step_order: int,
    binding_references: Iterable[TemplateReference] | None,
    max_prior_step_order: int,
) -> list[int]:
    """Return the prior step orders whose output the step reads.

    Explicit underlag (``input_bindings``) is the whole step input, so its
    step references decide alone; ``input_source`` describes the input only
    for a step without underlag. ``None`` for ``binding_references`` means the
    step has no underlag.

    ``input_source`` is a ``FlowInputSource`` or the value it is stored as.
    Anything else raises ``ValueError``: the security-classification check
    reads its upstream set from here, and a source it cannot read must fail
    that check rather than read as "no prior step".
    """
    source = FlowInputSource(input_source)
    if binding_references is not None:
        return resolve_reference_step_orders(
            references=binding_references,
            step_order=step_order,
            max_prior_step_order=max_prior_step_order,
        )
    return list(_implicit_input_orders(source, step_order))


def _implicit_input_orders(source: FlowInputSource, step_order: int) -> range:
    """The earlier steps a step without underlag reads through its
    ``input_source``: the step before it for ``previous_step``, every earlier
    step for ``all_previous_steps``, none for any other source."""
    if step_order <= 1:
        return range(0)
    if source is FlowInputSource.PREVIOUS_STEP:
        return range(step_order - 1, step_order)
    if source is FlowInputSource.ALL_PREVIOUS_STEPS:
        return range(1, step_order)
    return range(0)


ReadChannel = Literal["input", "prompt", "config"]
"""Where a read enters a step: ``input`` is the step input (the question
binding or the source refs when present, otherwise ``input_source``),
``prompt`` an interpolation in the step assistant's prompt, ``config`` a
template the runtime fills in the step's configuration (template-fill
bindings, HTTP requests, tool arguments). The first two reach the step's
model; the third forwards data without reaching it."""

# The site of a prompt read, as the runtime records the edge of that read
# (``interpolate_with_evidence`` with ``binding_ref="assistant_prompt"``), so
# measured evidence and the definition name the same read.
PROMPT_READ_SITE_PREFIX = "assistant_prompt:"
# The site of the implicit input a step without underlag reads.
INPUT_SOURCE_READ_SITE = "input_source"
# The selector of a whole structured value, and the head of a structured path.
STRUCTURED_SELECTOR_HEAD = "structured"


@dataclass(frozen=True, slots=True)
class StepRead:
    """One read a step makes of an earlier step's result.

    ``selector`` is what it reads of that result: ``()`` the whole text,
    ``("structured",)`` the whole structured value, ``("structured", "a",
    "b")`` a structured path, any other tail its segments. ``site`` is where
    the read is written: ``input_source``, ``input_bindings.question``,
    ``input_bindings.source_refs[2]``, ``assistant_prompt:<expression>``,
    ``output_config.bindings.x``, ``input_config.url``,
    ``input_config.tool.arguments.name``; the column alone when a
    configuration cannot be read and counts as every earlier step.
    """

    channel: ReadChannel
    step_order: int
    selector: tuple[str, ...]
    site: str


def step_reads_by_channel(
    *,
    input_source: FlowInputSource | str,
    step_order: int,
    input_bindings: object,
    prompt_template: str | None,
    output_mode: FlowOutputMode | str,
    input_config: Mapping[str, object] | None,
    output_config: Mapping[str, object] | None,
    step_ref_mapping: dict[str, int],
    max_prior_step_order: int,
) -> tuple[StepRead, ...]:
    """Every read the step makes of an earlier step, typed by channel.

    The one place that says what a step reads and where: the merged resolvers
    (``resolve_step_input_orders``, ``resolve_step_upstream_orders``) are
    the sorted set of ``step_order`` over its channels, so they cannot drift
    from it. Input and prompt reads come first, in the order they are
    written; configuration reads follow, ``output_config`` before
    ``input_config``. ``input_source`` and ``output_mode`` fail closed as in
    the resolvers.
    """
    reads = list(
        _model_channel_reads(
            input_source=input_source,
            step_order=step_order,
            input_bindings=input_bindings,
            prompt_template=prompt_template,
            step_ref_mapping=step_ref_mapping,
            max_prior_step_order=max_prior_step_order,
        )
    )
    source = FlowInputSource(input_source)
    mode = FlowOutputMode(output_mode)
    configs: tuple[tuple[ConfigColumn, Mapping[str, object] | None], ...] = (
        ("output_config", output_config),
        ("input_config", input_config),
    )
    for column, config in configs:
        channel = config_channel(
            column=column,
            config=config,
            input_source=source,
            output_mode=mode,
            step_order=step_order,
        )
        if channel is not None:
            reads.extend(
                _config_channel_reads(
                    channel,
                    step_ref_mapping=step_ref_mapping,
                    max_prior_step_order=max_prior_step_order,
                )
            )
    return tuple(reads)


def _model_channel_reads(
    *,
    input_source: FlowInputSource | str,
    step_order: int,
    input_bindings: object,
    prompt_template: str | None,
    step_ref_mapping: dict[str, int],
    max_prior_step_order: int,
) -> list[StepRead]:
    """The ``input`` and ``prompt`` reads: what reaches the step's model."""
    source = FlowInputSource(input_source)
    reads: list[StepRead] = []
    if effective_question_binding(input_bindings) is not None:
        # Explicit underlag is the whole step input. The question and each
        # source ref are read where they are written; their expressions are
        # exactly those of the lowered question the runtime interpolates.
        question = question_binding(input_bindings)
        if question is not None:
            reads.extend(
                _template_reads(
                    "input",
                    question,
                    site="input_bindings.question",
                    context_step_order=step_order,
                    step_ref_mapping=step_ref_mapping,
                    max_prior_step_order=max_prior_step_order,
                )
            )
        for index, ref in enumerate(source_ref_bindings(input_bindings)):
            reads.extend(
                _template_reads(
                    "input",
                    ref.template_expression(),
                    site=f"input_bindings.source_refs[{index}]",
                    context_step_order=step_order,
                    step_ref_mapping=step_ref_mapping,
                    max_prior_step_order=max_prior_step_order,
                )
            )
    else:
        reads.extend(
            StepRead("input", order, (), INPUT_SOURCE_READ_SITE)
            for order in _implicit_input_orders(source, step_order)
        )
    if prompt_template:
        for reference in analyze_template(
            prompt_template, step_refs=step_ref_mapping, form_field_names=set()
        ):
            read = _reference_read(
                "prompt",
                reference,
                site=f"{PROMPT_READ_SITE_PREFIX}{reference.expression}",
                step_order=step_order,
                max_prior_step_order=max_prior_step_order,
            )
            if read is not None:
                reads.append(read)
    return reads


def _config_channel_reads(
    channel: ConfigChannel,
    *,
    step_ref_mapping: dict[str, int],
    max_prior_step_order: int,
) -> list[StepRead]:
    if channel.sites is None:
        return [
            StepRead("config", order, (), channel.column)
            for order in range(1, max_prior_step_order + 1)
        ]
    reads: list[StepRead] = []
    for path, template in channel.sites:
        site = ".".join((channel.column, *(str(segment) for segment in path)))
        reads.extend(
            _template_reads(
                "config",
                template,
                site=site,
                context_step_order=channel.context_step_order,
                step_ref_mapping=step_ref_mapping,
                max_prior_step_order=max_prior_step_order,
            )
        )
    return reads


def _template_reads(
    channel: ReadChannel,
    template: str,
    *,
    site: str,
    context_step_order: int,
    step_ref_mapping: dict[str, int],
    max_prior_step_order: int,
) -> list[StepRead]:
    """The reads of ``template``, read in the variable context of step
    ``context_step_order`` (which decides what ``föregående_steg`` names)."""
    reads: list[StepRead] = []
    for reference in analyze_template(
        template, step_refs=step_ref_mapping, form_field_names=set()
    ):
        read = _reference_read(
            channel,
            reference,
            site=site,
            step_order=context_step_order,
            max_prior_step_order=max_prior_step_order,
        )
        if read is not None:
            reads.append(read)
    return reads


def _reference_read(
    channel: ReadChannel,
    reference: TemplateReference,
    *,
    site: str,
    step_order: int,
    max_prior_step_order: int,
) -> StepRead | None:
    """The read ``reference`` makes in step ``step_order``, or None when it
    names no step with a result, by the rule of ``resolve_reference_step_orders``."""
    referenced_order = referenced_step_order(reference, step_order=step_order)
    if (
        not isinstance(referenced_order, int)
        or not 1 <= referenced_order <= max_prior_step_order
    ):
        return None
    return StepRead(channel, referenced_order, read_selector(reference), site)


def read_selector(reference: TemplateReference) -> tuple[str, ...]:
    """What a step reference reads of the step's result: ``()`` for its text
    (bare, ``output``, ``output.text`` and ``föregående_steg``),
    ``("structured", ...)`` for the structured value or a path in it, and
    the tail's segments for anything else."""
    if reference.head == PREVIOUS_STEP_TEXT_ALIAS and not reference.tail:
        return ()
    if reference.tail in {"", "output", "output.text"}:
        return ()
    if reference.tail == f"output.{STRUCTURED_SELECTOR_HEAD}":
        return (STRUCTURED_SELECTOR_HEAD,)
    if reference.structured_path is not None:
        return (STRUCTURED_SELECTOR_HEAD, *reference.structured_path)
    return tuple(reference.tail.split("."))


def _channel_orders(
    reads: Iterable[StepRead], channels: Iterable[ReadChannel]
) -> list[int]:
    wanted = set(channels)
    return sorted({read.step_order for read in reads if read.channel in wanted})


@dataclass(frozen=True, slots=True)
class FormFieldRead:
    """One read a step makes of a run form field: the channel and the site,
    named as in ``StepRead``."""

    channel: ReadChannel
    field: str
    site: str


def step_form_field_reads(
    *,
    input_source: FlowInputSource | str,
    step_order: int,
    input_bindings: object,
    prompt_template: str | None,
    output_mode: FlowOutputMode | str,
    input_config: Mapping[str, object] | None,
    output_config: Mapping[str, object] | None,
    step_ref_mapping: dict[str, int],
    form_field_names: Iterable[str],
) -> tuple[FormFieldRead, ...]:
    """Every read the step makes of the run form fields ``form_field_names``,
    in the templates ``step_reads_by_channel`` reads steps in.

    A step that takes the whole run input reads every field: one whose input
    is ``flow_input`` without underlag, and a template that reads
    ``flow_input`` (or ``flow.input``) whole. So does a configuration that
    cannot be read, as it counts as reading every earlier step. A field is
    read by ``flow_input.<field>`` or by its bare name, by the rule of
    ``template_reference_analyzer.referenced_form_fields``.
    """
    fields = set(form_field_names)
    if not fields:
        return ()
    reads: list[FormFieldRead] = []

    def every_field(channel: ReadChannel, site: str) -> None:
        reads.extend(FormFieldRead(channel, name, site) for name in sorted(fields))

    def template(channel: ReadChannel, text: str, site: str | None) -> None:
        for reference in analyze_template(
            text, step_refs=step_ref_mapping, form_field_names=fields
        ):
            reads.extend(
                FormFieldRead(
                    channel,
                    name,
                    site or f"{PROMPT_READ_SITE_PREFIX}{reference.expression}",
                )
                for name in sorted(
                    referenced_form_fields([reference], form_field_names=fields)
                )
            )

    source = FlowInputSource(input_source)
    if effective_question_binding(input_bindings) is not None:
        question = question_binding(input_bindings)
        if question is not None:
            template("input", question, "input_bindings.question")
        for index, ref in enumerate(source_ref_bindings(input_bindings)):
            template(
                "input",
                ref.template_expression(),
                f"input_bindings.source_refs[{index}]",
            )
    elif source is FlowInputSource.FLOW_INPUT:
        every_field("input", INPUT_SOURCE_READ_SITE)
    if prompt_template:
        template("prompt", prompt_template, None)
    mode = FlowOutputMode(output_mode)
    configs: tuple[tuple[ConfigColumn, Mapping[str, object] | None], ...] = (
        ("output_config", output_config),
        ("input_config", input_config),
    )
    for column, config in configs:
        channel = config_channel(
            column=column,
            config=config,
            input_source=source,
            output_mode=mode,
            step_order=step_order,
        )
        if channel is None:
            continue
        if channel.sites is None:
            every_field("config", column)
            continue
        for path, text in channel.sites:
            template(
                "config",
                text,
                ".".join((column, *(str(segment) for segment in path))),
            )
    return tuple(reads)


def resolve_step_input_orders(
    *,
    input_source: FlowInputSource | str,
    step_order: int,
    input_bindings: object,
    prompt_template: str | None,
    step_ref_mapping: dict[str, int],
    max_prior_step_order: int,
) -> list[int]:
    """Resolve the prior steps whose output reaches the step's model.

    The step input is the explicit underlag when present, otherwise the
    implicit source. The assistant prompt is a second input channel: its step
    references are interpolated into the prompt regardless of the input, so
    they always join the set. The set is the ``input`` and ``prompt`` reads
    of ``step_reads_by_channel``.
    """
    return _channel_orders(
        _model_channel_reads(
            input_source=input_source,
            step_order=step_order,
            input_bindings=input_bindings,
            prompt_template=prompt_template,
            step_ref_mapping=step_ref_mapping,
            max_prior_step_order=max_prior_step_order,
        ),
        ("input", "prompt"),
    )


def resolve_step_upstream_orders(
    *,
    input_source: FlowInputSource | str,
    step_order: int,
    input_bindings: object,
    prompt_template: str | None,
    output_mode: FlowOutputMode | str,
    input_config: Mapping[str, object] | None,
    output_config: Mapping[str, object] | None,
    step_ref_mapping: dict[str, int],
    max_prior_step_order: int,
) -> list[int]:
    """Resolve every prior step whose output reaches the step's result.

    The step's input and prompt (``resolve_step_input_orders``), plus the
    templates the runtime fills from earlier results in the configuration of
    the mode the step runs: the bindings of a template fill, the request of an
    ``http_post`` delivery, the request of an ``http_get`` input, the bound
    arguments of a ``tool`` input. What a
    template reads is carried by the result or the request, so the security
    classification counts it like any other input.

    A configuration this cannot read reads as every earlier step: the step
    cannot run with it, and a classification check must not take "unreadable"
    for "reads nothing". ``output_mode`` is a ``FlowOutputMode`` or the value it
    is stored as; anything else raises ``ValueError`` like ``input_source``.
    The set is every channel of ``step_reads_by_channel``.
    """
    return _channel_orders(
        step_reads_by_channel(
            input_source=input_source,
            step_order=step_order,
            input_bindings=input_bindings,
            prompt_template=prompt_template,
            output_mode=output_mode,
            input_config=input_config,
            output_config=output_config,
            step_ref_mapping=step_ref_mapping,
            max_prior_step_order=max_prior_step_order,
        ),
        ("input", "prompt", "config"),
    )


def resolve_tool_argument_orders(
    *,
    input_source: FlowInputSource | str,
    step_order: int,
    input_config: Mapping[str, object] | None,
    step_ref_mapping: dict[str, int],
    max_prior_step_order: int,
) -> list[int]:
    """Resolve the prior steps whose output a ``tool`` step sends to the tool's
    server: the steps its bound arguments read, and nothing its input or its
    prompt reads. Empty for a step with another input source.

    An unreadable tool configuration reads as every earlier step, as in
    ``resolve_step_upstream_orders``.
    """
    if FlowInputSource(input_source) is not FlowInputSource.TOOL:
        return []
    return _channel_step_orders(
        _tool_channel(input_config, step_order),
        step_ref_mapping=step_ref_mapping,
        max_prior_step_order=max_prior_step_order,
    )


def _channel_step_orders(
    channel: ConfigChannel,
    *,
    step_ref_mapping: dict[str, int],
    max_prior_step_order: int,
) -> list[int]:
    if channel.sites is None:
        return list(range(1, max_prior_step_order + 1))
    orders: set[int] = set()
    for _, template in channel.sites:
        orders.update(
            resolve_reference_step_orders(
                references=analyze_template(
                    template, step_refs=step_ref_mapping, form_field_names=set()
                ),
                step_order=channel.context_step_order,
                max_prior_step_order=max_prior_step_order,
            )
        )
    return sorted(orders)


ConfigColumn = Literal["input_config", "output_config"]


@dataclass(frozen=True, slots=True)
class ConfigChannel:
    """The templates the runtime interpolates in one configuration column of
    a step, each with its path in the column's object; None when the
    configuration cannot be read."""

    column: ConfigColumn
    sites: list[tuple[ConfigPath, str]] | None
    # The runtime builds the variable context for the step at this order: the
    # steps before it are the ones its templates read, and ``föregående_steg``
    # names the step before it.
    context_step_order: int


def config_channel(
    *,
    column: ConfigColumn,
    config: Mapping[str, object] | None,
    input_source: FlowInputSource,
    output_mode: FlowOutputMode,
    step_order: int,
) -> ConfigChannel | None:
    """The channel of ``column`` for the modes the step runs, or None when they
    interpolate nothing in it: a configuration of a mode the step does not run
    is literal data."""
    if column == "output_config" and output_mode is FlowOutputMode.TEMPLATE_FILL:
        return ConfigChannel(column, _template_fill_sites(config), step_order)
    if column == "input_config" and input_source is FlowInputSource.TOOL:
        return _tool_channel(config, step_order)
    if not sends_http_config(column, input_source, output_mode, config):
        return None
    # A webhook is built once the step has answered, so its context is the
    # step's own: ``föregående_steg`` is the step's result there.
    return ConfigChannel(
        column,
        _http_config_sites(config),
        step_order + 1 if column == "output_config" else step_order,
    )


def _tool_channel(
    config: Mapping[str, object] | None, step_order: int
) -> ConfigChannel:
    return ConfigChannel("input_config", tool_reference_sites(config), step_order)


def _template_fill_sites(
    config: Mapping[str, object] | None,
) -> list[tuple[ConfigPath, str]] | None:
    bindings = config.get("bindings") if config is not None else None
    if bindings is None:
        return []
    if not isinstance(bindings, Mapping):
        return None
    sites: list[tuple[ConfigPath, str]] = []
    for key, value in cast(Mapping[str, object], bindings).items():
        if not isinstance(value, str):
            return None
        sites.append((("bindings", key), value))
    return sites


def _http_config_sites(
    config: Mapping[str, object] | None,
) -> list[tuple[ConfigPath, str]] | None:
    # Only the HTTP fields are read. Other keys of the object (the retrieval
    # policy, runtime input) hold no template of this channel.
    http_fields = {
        key: value for key, value in (config or {}).items() if key in HTTP_CONFIG_KEYS
    }
    if not http_fields:
        return []
    if not is_authored_config(http_fields):
        return None
    try:
        return HttpAuthoredConfig.model_validate(
            http_fields
        ).interpolated_template_sites()
    except ValidationError:
        return None


def selected_source_step_order(
    reference: TemplateReference,
    *,
    step_order: int,
    section_processing: bool,
) -> int | None:
    """Return the prior step whose result a step's input reference selects.

    The runtime selects step material by this rule and publish checks it, so
    the two cannot drift. ``föregående_steg`` selects the previous step. A step
    reference selects that step for its text (bare, ``output``,
    ``output.text``) and, under section processing, for any ``output.`` path.
    """
    if reference.tail not in {"", "output", "output.text"} and not (
        section_processing and reference.tail.startswith("output.")
    ):
        return None
    if names_step_without_result(reference, step_order=step_order):
        return None
    return referenced_step_order(reference, step_order=step_order)


def referenced_step_order(
    reference: TemplateReference, *, step_order: int
) -> int | None:
    """Return the step a reference in step ``step_order`` names, if any.

    A step reference names its step; ``föregående_steg`` names the previous
    step (``0`` on the first step, which no step has).
    """
    if reference.head == PREVIOUS_STEP_TEXT_ALIAS and not reference.tail:
        return step_order - 1
    return reference.step_order


def names_step_without_result(reference: TemplateReference, *, step_order: int) -> bool:
    """Whether a reference in step ``step_order`` names a step whose result
    does not exist when that step runs: the step itself, a later one, or an
    order the flow does not have. Step orders are contiguous from 1, so the
    steps with a result are exactly the orders below ``step_order``. A
    reference that names no step at all is not this function's to judge."""
    referenced_order = referenced_step_order(reference, step_order=step_order)
    return referenced_order is not None and not 1 <= referenced_order < step_order


def resolve_reference_step_orders(
    *,
    references: Iterable[TemplateReference],
    step_order: int,
    max_prior_step_order: int,
) -> list[int]:
    orders: set[int] = set()
    for reference in references:
        referenced_order = referenced_step_order(reference, step_order=step_order)
        if (
            isinstance(referenced_order, int)
            and 1 <= referenced_order <= max_prior_step_order
        ):
            orders.add(referenced_order)
    return sorted(orders)


def _step_order(step: _StepReferenceSource) -> object:
    if isinstance(step, Mapping):
        return step.get("step_order")
    return step.step_order


def _is_step_order(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _step_ref(
    step: _StepReferenceSource,
    key: Literal["plan_step_ref", "existing_step_ref", "user_description"],
) -> object:
    if isinstance(step, Mapping):
        return step.get(key)
    if key == "plan_step_ref":
        return step.plan_step_ref
    if key == "existing_step_ref":
        return step.existing_step_ref
    return step.user_description
