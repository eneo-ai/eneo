from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from intric.flows.enums import FlowInputSource, RerunDependencyKind
from intric.flows.http_transport import HttpAuthMode, HttpBodyMode, is_authored_config
from intric.flows.runtime.models import RuntimeStep
from intric.flows.step_lineage import build_step_ref_mapping
from intric.flows.template_reference_analyzer import (
    TemplateReferenceKind,
    analyze_template,
)

_PREVIOUS_STEP_RUNTIME_ALIAS = "föregående_steg"


class RerunGraphStepNotFound(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RerunDependencyEdge:
    upstream_step_id: UUID
    upstream_step_order: int
    downstream_step_id: UUID
    downstream_step_order: int
    dependency_kinds: tuple[RerunDependencyKind, ...]


@dataclass(frozen=True, slots=True)
class RerunInvalidatedStep:
    step_id: UUID
    step_order: int
    dependency_kinds: tuple[RerunDependencyKind, ...]


@dataclass(frozen=True, slots=True)
class RerunInvalidationGraph:
    root_step_id: UUID
    invalidated_steps: tuple[RerunInvalidatedStep, ...]
    dependency_edges: tuple[RerunDependencyEdge, ...]

    @property
    def invalidated_step_ids(self) -> tuple[UUID, ...]:
        return tuple(step.step_id for step in self.invalidated_steps)


def build_rerun_invalidation_graph(
    *,
    steps: Sequence[RuntimeStep],
    root_step_id: UUID,
) -> RerunInvalidationGraph:
    sorted_steps = tuple(sorted(steps, key=lambda step: step.step_order))
    steps_by_id = {step.step_id: step for step in sorted_steps}
    root_step = steps_by_id.get(root_step_id)
    if root_step is None:
        raise RerunGraphStepNotFound(f"Step {root_step_id} is not in the run graph.")

    all_edges = _build_dependency_edges(sorted_steps)
    downstream_by_upstream: dict[UUID, list[RerunDependencyEdge]] = {}
    for edge in all_edges:
        downstream_by_upstream.setdefault(edge.upstream_step_id, []).append(edge)

    invalidated_ids = _collect_downstream_step_ids(
        root_step_id=root_step_id,
        downstream_by_upstream=downstream_by_upstream,
    )
    dependency_kinds_by_step_id = _dependency_kinds_by_invalidated_step(
        invalidated_ids=invalidated_ids,
        dependency_edges=all_edges,
        root_step_id=root_step_id,
    )
    invalidated_steps = tuple(
        RerunInvalidatedStep(
            step_id=step.step_id,
            step_order=step.step_order,
            dependency_kinds=dependency_kinds_by_step_id.get(step.step_id, ()),
        )
        for step in sorted_steps
        if step.step_id in invalidated_ids
    )
    invalidated_edges = tuple(
        edge
        for edge in all_edges
        if edge.upstream_step_id in invalidated_ids
        and edge.downstream_step_id in invalidated_ids
    )
    return RerunInvalidationGraph(
        root_step_id=root_step.step_id,
        invalidated_steps=invalidated_steps,
        dependency_edges=invalidated_edges,
    )


def _build_dependency_edges(
    steps: Sequence[RuntimeStep],
) -> tuple[RerunDependencyEdge, ...]:
    steps_by_order = {step.step_order: step for step in steps}
    step_ref_mapping = _build_rerun_step_ref_mapping(steps)
    grouped_kinds: dict[tuple[UUID, UUID], set[RerunDependencyKind]] = {}

    for step in steps:
        for upstream_order, dependency_kind in _dependency_orders_for_step(
            step=step,
            step_ref_mapping=step_ref_mapping,
        ):
            upstream_step = steps_by_order.get(upstream_order)
            if upstream_step is None or upstream_order >= step.step_order:
                continue
            edge_key = (upstream_step.step_id, step.step_id)
            grouped_kinds.setdefault(edge_key, set()).add(dependency_kind)

    edges: list[RerunDependencyEdge] = []
    for (
        upstream_step_id,
        downstream_step_id,
    ), dependency_kinds in grouped_kinds.items():
        upstream_step = _step_by_id(steps, upstream_step_id)
        downstream_step = _step_by_id(steps, downstream_step_id)
        edges.append(
            RerunDependencyEdge(
                upstream_step_id=upstream_step.step_id,
                upstream_step_order=upstream_step.step_order,
                downstream_step_id=downstream_step.step_id,
                downstream_step_order=downstream_step.step_order,
                dependency_kinds=tuple(
                    sorted(dependency_kinds, key=lambda kind: kind.value)
                ),
            )
        )
    return tuple(
        sorted(
            edges,
            key=lambda edge: (edge.downstream_step_order, edge.upstream_step_order),
        )
    )


def _dependency_orders_for_step(
    *,
    step: RuntimeStep,
    step_ref_mapping: Mapping[str, int],
) -> list[tuple[int, RerunDependencyKind]]:
    dependencies: list[tuple[int, RerunDependencyKind]] = []
    if step.input_source == FlowInputSource.PREVIOUS_STEP.value and step.step_order > 1:
        dependencies.append(
            (step.step_order - 1, RerunDependencyKind.INPUT_SOURCE_PREVIOUS_STEP)
        )
    if step.input_source == FlowInputSource.ALL_PREVIOUS_STEPS.value:
        dependencies.extend(
            (upstream_order, RerunDependencyKind.INPUT_SOURCE_ALL_PREVIOUS_STEPS)
            for upstream_order in range(1, step.step_order)
        )
    dependencies.extend(_template_dependency_orders(step, step_ref_mapping))
    return dependencies


def _template_dependency_orders(
    step: RuntimeStep,
    step_ref_mapping: Mapping[str, int],
) -> list[tuple[int, RerunDependencyKind]]:
    references: list[tuple[str, RerunDependencyKind]] = []
    input_bindings = _mapping(step.input_bindings)
    if input_bindings is not None:
        question = input_bindings.get("question")
        if isinstance(question, str):
            references.append((question, RerunDependencyKind.INPUT_BINDINGS_QUESTION))

    references.extend(
        _http_config_templates(
            config=step.input_config,
            prefix="input_config",
        )
    )
    references.extend(
        _http_config_templates(
            config=step.output_config,
            prefix="output_config",
        )
    )

    output_config = _mapping(step.output_config)
    if output_config is not None:
        bindings = _mapping(output_config.get("bindings"))
        if bindings is not None:
            references.extend(
                (binding_value, RerunDependencyKind.OUTPUT_CONFIG_BINDINGS)
                for binding_value in bindings.values()
                if isinstance(binding_value, str)
            )

    assistant_snapshot = _mapping(step.assistant_snapshot)
    if assistant_snapshot is not None:
        instructions = assistant_snapshot.get("instructions")
        if isinstance(instructions, str):
            references.append(
                (instructions, RerunDependencyKind.ASSISTANT_SNAPSHOT_INSTRUCTIONS)
            )

    dependency_orders: list[tuple[int, RerunDependencyKind]] = []
    for template, dependency_kind in references:
        dependency_orders.extend(
            _template_reference_dependency_orders(
                template=template,
                current_step_order=step.step_order,
                step_ref_mapping=step_ref_mapping,
                dependency_kind=dependency_kind,
            )
        )
    return dependency_orders


def _http_config_templates(
    *,
    config: object,
    prefix: str,
) -> list[tuple[str, RerunDependencyKind]]:
    config_mapping = _mapping(config)
    if config_mapping is None:
        return []

    if prefix == "input_config":
        url_kind = RerunDependencyKind.INPUT_CONFIG_URL
        headers_kind = RerunDependencyKind.INPUT_CONFIG_HEADERS
        body_template_kind = RerunDependencyKind.INPUT_CONFIG_BODY_TEMPLATE
        body_json_kind = RerunDependencyKind.INPUT_CONFIG_BODY_JSON
    else:
        url_kind = RerunDependencyKind.OUTPUT_CONFIG_URL
        headers_kind = RerunDependencyKind.OUTPUT_CONFIG_HEADERS
        body_template_kind = RerunDependencyKind.OUTPUT_CONFIG_BODY_TEMPLATE
        body_json_kind = RerunDependencyKind.OUTPUT_CONFIG_BODY_JSON

    if is_authored_config(config_mapping):
        return _authored_http_config_templates(
            config_mapping=config_mapping,
            url_kind=url_kind,
            headers_kind=headers_kind,
            body_template_kind=body_template_kind,
        )

    return _legacy_http_config_templates(
        config_mapping=config_mapping,
        url_kind=url_kind,
        headers_kind=headers_kind,
        body_template_kind=body_template_kind,
        body_json_kind=body_json_kind,
    )


def _legacy_http_config_templates(
    *,
    config_mapping: Mapping[str, object],
    url_kind: RerunDependencyKind,
    headers_kind: RerunDependencyKind,
    body_template_kind: RerunDependencyKind,
    body_json_kind: RerunDependencyKind,
) -> list[tuple[str, RerunDependencyKind]]:
    templates: list[tuple[str, RerunDependencyKind]] = []
    url = config_mapping.get("url")
    if isinstance(url, str):
        templates.append((url, url_kind))

    headers = _mapping(config_mapping.get("headers"))
    if headers is not None:
        templates.extend(
            (header_value, headers_kind)
            for header_value in headers.values()
            if isinstance(header_value, str)
        )

    body_template = config_mapping.get("body_template")
    if isinstance(body_template, str):
        templates.append((body_template, body_template_kind))

    body_json = config_mapping.get("body_json")
    templates.extend(
        (template, body_json_kind) for template in _iter_nested_strings(body_json)
    )
    return templates


def _authored_http_config_templates(
    *,
    config_mapping: Mapping[str, object],
    url_kind: RerunDependencyKind,
    headers_kind: RerunDependencyKind,
    body_template_kind: RerunDependencyKind,
) -> list[tuple[str, RerunDependencyKind]]:
    templates: list[tuple[str, RerunDependencyKind]] = []
    _append_string_template(
        templates=templates,
        value=config_mapping.get("url"),
        dependency_kind=url_kind,
    )
    _extend_authored_auth_templates(
        templates=templates,
        auth=config_mapping.get("auth"),
        dependency_kind=headers_kind,
    )
    custom_headers = config_mapping.get("custom_headers")
    if isinstance(custom_headers, Sequence) and not isinstance(
        custom_headers, (str, bytes, bytearray)
    ):
        for header in cast(Sequence[object], custom_headers):
            header_mapping = _mapping(header)
            if header_mapping is None:
                continue
            _append_string_template(
                templates=templates,
                value=header_mapping.get("value"),
                dependency_kind=headers_kind,
            )

    body = _mapping(config_mapping.get("body"))
    if body is not None and body.get("mode") in {
        HttpBodyMode.JSON_TEMPLATE.value,
        HttpBodyMode.TEXT_TEMPLATE.value,
    }:
        _append_string_template(
            templates=templates,
            value=body.get("template"),
            dependency_kind=body_template_kind,
        )
    return templates


def _extend_authored_auth_templates(
    *,
    templates: list[tuple[str, RerunDependencyKind]],
    auth: object,
    dependency_kind: RerunDependencyKind,
) -> None:
    auth_mapping = _mapping(auth)
    if auth_mapping is None:
        return
    mode = auth_mapping.get("mode")
    if mode == HttpAuthMode.BEARER_TOKEN.value:
        _append_string_template(
            templates=templates,
            value=auth_mapping.get("token"),
            dependency_kind=dependency_kind,
        )
    elif mode == HttpAuthMode.API_KEY.value:
        _append_string_template(
            templates=templates,
            value=auth_mapping.get("header_name"),
            dependency_kind=dependency_kind,
        )
        _append_string_template(
            templates=templates,
            value=auth_mapping.get("key"),
            dependency_kind=dependency_kind,
        )
    elif mode == HttpAuthMode.BASIC_AUTH.value:
        _append_string_template(
            templates=templates,
            value=auth_mapping.get("username"),
            dependency_kind=dependency_kind,
        )
        _append_string_template(
            templates=templates,
            value=auth_mapping.get("password"),
            dependency_kind=dependency_kind,
        )


def _append_string_template(
    *,
    templates: list[tuple[str, RerunDependencyKind]],
    value: object,
    dependency_kind: RerunDependencyKind,
) -> None:
    if isinstance(value, str):
        templates.append((value, dependency_kind))


def _template_reference_dependency_orders(
    *,
    template: str,
    current_step_order: int,
    step_ref_mapping: Mapping[str, int],
    dependency_kind: RerunDependencyKind,
) -> tuple[tuple[int, RerunDependencyKind], ...]:
    references = analyze_template(
        template,
        step_refs=dict(step_ref_mapping),
        form_field_names=set(),
    )
    dependency_orders: list[tuple[int, RerunDependencyKind]] = []
    for reference in references:
        if reference.kind is TemplateReferenceKind.STEP and isinstance(
            reference.step_order, int
        ):
            dependency_orders.append((reference.step_order, dependency_kind))
            continue
        if (
            reference.kind is TemplateReferenceKind.RUNTIME
            and reference.head == _PREVIOUS_STEP_RUNTIME_ALIAS
            and current_step_order > 1
        ):
            dependency_orders.append(
                (
                    current_step_order - 1,
                    RerunDependencyKind.RUNTIME_ALIAS_PREVIOUS_STEP,
                )
            )
    return tuple(
        dict.fromkeys(
            dependency_orders,
        )
    )


def _collect_downstream_step_ids(
    *,
    root_step_id: UUID,
    downstream_by_upstream: Mapping[UUID, Sequence[RerunDependencyEdge]],
) -> set[UUID]:
    invalidated_ids = {root_step_id}
    queue: deque[UUID] = deque([root_step_id])
    while queue:
        upstream_step_id = queue.popleft()
        for edge in downstream_by_upstream.get(upstream_step_id, ()):
            if edge.downstream_step_id in invalidated_ids:
                continue
            invalidated_ids.add(edge.downstream_step_id)
            queue.append(edge.downstream_step_id)
    return invalidated_ids


def _dependency_kinds_by_invalidated_step(
    *,
    invalidated_ids: set[UUID],
    dependency_edges: Sequence[RerunDependencyEdge],
    root_step_id: UUID,
) -> dict[UUID, tuple[RerunDependencyKind, ...]]:
    kinds_by_step_id: dict[UUID, set[RerunDependencyKind]] = {}
    for edge in dependency_edges:
        if edge.downstream_step_id == root_step_id:
            continue
        if (
            edge.upstream_step_id not in invalidated_ids
            or edge.downstream_step_id not in invalidated_ids
        ):
            continue
        kinds_by_step_id.setdefault(edge.downstream_step_id, set()).update(
            edge.dependency_kinds
        )
    return {
        step_id: tuple(sorted(kinds, key=lambda kind: kind.value))
        for step_id, kinds in kinds_by_step_id.items()
    }


def _build_rerun_step_ref_mapping(steps: Sequence[RuntimeStep]) -> dict[str, int]:
    mapping = build_step_ref_mapping(steps)
    for step in sorted(steps, key=lambda item: item.step_order):
        user_description = step.user_description
        if isinstance(user_description, str) and user_description.strip():
            mapping.setdefault(user_description.strip(), step.step_order)
    return mapping


def _iter_nested_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        strings: list[str] = []
        for item in cast(Sequence[object], value):
            strings.extend(_iter_nested_strings(item))
        return tuple(strings)
    if isinstance(value, Mapping):
        strings: list[str] = []
        for item_value in cast(Mapping[object, object], value).values():
            strings.extend(_iter_nested_strings(item_value))
        return tuple(strings)
    return ()


def _mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def _step_by_id(steps: Sequence[RuntimeStep], step_id: UUID) -> RuntimeStep:
    for step in steps:
        if step.step_id == step_id:
            return step
    raise RerunGraphStepNotFound(f"Step {step_id} is not in the run graph.")
