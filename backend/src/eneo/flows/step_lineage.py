from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias, TypeGuard, cast

from pydantic import ValidationError

from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_variable_definitions import PREVIOUS_STEP_TEXT_ALIAS
from eneo.flows.http_transport import (
    HTTP_CONFIG_KEYS,
    HttpAuthoredConfig,
    is_authored_config,
)
from eneo.flows.input_binding_contract_rules import effective_question_binding
from eneo.flows.template_reference_analyzer import TemplateReference, analyze_template


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
    if not raw_order.isdigit():
        return None
    step_order = int(raw_order)
    # Reject non-canonical aliases such as existing_step_01.
    if raw_order != str(step_order):
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
    if source is FlowInputSource.PREVIOUS_STEP and step_order > 1:
        return [step_order - 1]
    if source is FlowInputSource.ALL_PREVIOUS_STEPS and step_order > 1:
        return list(range(1, step_order))
    return []


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
    they always join the set.
    """
    question_template = effective_question_binding(input_bindings)
    binding_references = (
        analyze_template(
            question_template,
            step_refs=step_ref_mapping,
            form_field_names=set(),
        )
        if question_template is not None
        else None
    )
    orders = set(
        resolve_upstream_step_orders(
            input_source=input_source,
            step_order=step_order,
            binding_references=binding_references,
            max_prior_step_order=max_prior_step_order,
        )
    )
    if prompt_template:
        orders.update(
            resolve_reference_step_orders(
                references=analyze_template(
                    prompt_template,
                    step_refs=step_ref_mapping,
                    form_field_names=set(),
                ),
                step_order=step_order,
                max_prior_step_order=max_prior_step_order,
            )
        )
    return sorted(orders)


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
    ``http_post`` delivery, the request of an ``http_get`` input. What a
    template reads is carried by the result or the request, so the security
    classification counts it like any other input.

    A configuration this cannot read reads as every earlier step: the step
    cannot run with it, and a classification check must not take "unreadable"
    for "reads nothing". ``output_mode`` is a ``FlowOutputMode`` or the value it
    is stored as; anything else raises ``ValueError`` like ``input_source``.
    """
    orders = set(
        resolve_step_input_orders(
            input_source=input_source,
            step_order=step_order,
            input_bindings=input_bindings,
            prompt_template=prompt_template,
            step_ref_mapping=step_ref_mapping,
            max_prior_step_order=max_prior_step_order,
        )
    )
    channels = _config_channels(
        input_source=FlowInputSource(input_source),
        output_mode=FlowOutputMode(output_mode),
        input_config=input_config,
        output_config=output_config,
        step_order=step_order,
    )
    if channels is None:
        return list(range(1, max_prior_step_order + 1))
    for channel in channels:
        for template in channel.templates:
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


@dataclass(frozen=True, slots=True)
class _ConfigChannel:
    templates: list[str]
    # The runtime builds the variable context for the step at this order, and
    # ``föregående_steg`` names the step before it.
    context_step_order: int


def _config_channels(
    *,
    input_source: FlowInputSource,
    output_mode: FlowOutputMode,
    input_config: Mapping[str, object] | None,
    output_config: Mapping[str, object] | None,
    step_order: int,
) -> list[_ConfigChannel] | None:
    """The configured templates the runtime interpolates, or None if unreadable."""
    channels: list[_ConfigChannel] = []
    if output_mode is FlowOutputMode.TEMPLATE_FILL:
        bindings = _template_fill_bindings(output_config)
        if bindings is None:
            return None
        channels.append(_ConfigChannel(bindings, step_order))
    if output_mode is FlowOutputMode.HTTP_POST:
        templates = _http_config_templates(output_config)
        if templates is None:
            return None
        # A webhook is built once the step has answered, so its context is the
        # step's own: ``föregående_steg`` is the step's result there.
        channels.append(_ConfigChannel(templates, step_order + 1))
    if input_source is FlowInputSource.HTTP_GET:
        templates = _http_config_templates(input_config)
        if templates is None:
            return None
        channels.append(_ConfigChannel(templates, step_order))
    return channels


def _template_fill_bindings(config: Mapping[str, object] | None) -> list[str] | None:
    bindings = config.get("bindings") if config is not None else None
    if bindings is None:
        return []
    if not isinstance(bindings, Mapping):
        return None
    values = list(cast(Mapping[object, object], bindings).values())
    if not all(isinstance(value, str) for value in values):
        return None
    return cast(list[str], values)


def _http_config_templates(config: Mapping[str, object] | None) -> list[str] | None:
    # The lineage reads the HTTP fields only. Other keys of the object (the
    # retrieval policy, runtime input) hold no template of this channel.
    http_fields = {
        key: value for key, value in (config or {}).items() if key in HTTP_CONFIG_KEYS
    }
    if not http_fields:
        return []
    if not is_authored_config(http_fields):
        return None
    try:
        return HttpAuthoredConfig.model_validate(http_fields).interpolated_templates()
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
    order = referenced_step_order(reference, step_order=step_order)
    if order is None or not 1 <= order < step_order:
        return None
    return order


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
