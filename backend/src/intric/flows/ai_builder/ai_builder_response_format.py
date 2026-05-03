from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from intric.completion_models.infrastructure.tenant_model_capabilities import (
    StructuredOutputCapabilityDecision,
    StructuredOutputMode,
)
from intric.flows.ai_builder.ai_builder_orchestrator import PlannerOutput


@dataclass(frozen=True, slots=True)
class PlannerResponseFormatSelection:
    request_mode: StructuredOutputMode
    litellm_kwargs: dict[str, object]
    capability_decision: StructuredOutputCapabilityDecision
    planner_output_strict_blockers: tuple[str, ...] = ()

    @property
    def planner_output_strict_blocked(self) -> bool:
        return (
            self.capability_decision.mode is StructuredOutputMode.STRICT_JSON_SCHEMA
            and bool(self.planner_output_strict_blockers)
        )


def build_planner_request_response_format(
    decision: StructuredOutputCapabilityDecision,
) -> PlannerResponseFormatSelection:
    blockers = planner_output_strict_schema_blockers()
    if decision.mode is StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION:
        return PlannerResponseFormatSelection(
            request_mode=StructuredOutputMode.PROMPT_WITH_PYDANTIC_VALIDATION,
            litellm_kwargs={},
            capability_decision=decision,
            planner_output_strict_blockers=blockers,
        )

    if decision.mode is StructuredOutputMode.STRICT_JSON_SCHEMA and not blockers:
        return PlannerResponseFormatSelection(
            request_mode=StructuredOutputMode.STRICT_JSON_SCHEMA,
            litellm_kwargs={
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "planner_output",
                        "schema": PlannerOutput.model_json_schema(),
                        "strict": True,
                    },
                }
            },
            capability_decision=decision,
            planner_output_strict_blockers=blockers,
        )

    return PlannerResponseFormatSelection(
        request_mode=StructuredOutputMode.JSON_OBJECT,
        litellm_kwargs={"response_format": {"type": "json_object"}},
        capability_decision=decision,
        planner_output_strict_blockers=blockers,
    )


@lru_cache(maxsize=1)
def planner_output_strict_schema_blockers() -> tuple[str, ...]:
    schema = PlannerOutput.model_json_schema()
    blockers: list[str] = []
    _collect_strict_schema_blockers(schema, "$", blockers)
    return tuple(blockers)


def _collect_strict_schema_blockers(
    node: object,
    path: str,
    blockers: list[str],
) -> None:
    if isinstance(node, dict):
        object_node = cast(dict[str, object], node)
        _collect_object_blockers(object_node, path, blockers)
        for key, value in object_node.items():
            _collect_strict_schema_blockers(value, f"{path}.{key}", blockers)
    elif isinstance(node, list):
        node_items = cast(list[object], node)
        for index, value in enumerate(node_items):
            _collect_strict_schema_blockers(value, f"{path}[{index}]", blockers)


def _collect_object_blockers(
    node: dict[str, object],
    path: str,
    blockers: list[str],
) -> None:
    for key in ("oneOf", "allOf", "not", "default"):
        if key in node:
            blockers.append(f"{path}: uses {key}")

    if node.get("type") != "object":
        return

    if node.get("additionalProperties") is not False:
        blockers.append(f"{path}: object lacks additionalProperties=false")

    properties = node.get("properties")
    if not isinstance(properties, dict):
        return

    property_names = set(cast(dict[str, object], properties))
    required = node.get("required")
    required_items = cast(list[object], required) if isinstance(required, list) else []
    required_names = {item for item in required_items if isinstance(item, str)}
    optional_names = sorted(property_names - required_names)
    if optional_names:
        blockers.append(f"{path}: optional properties {','.join(optional_names)}")


__all__ = [
    "PlannerResponseFormatSelection",
    "build_planner_request_response_format",
    "planner_output_strict_schema_blockers",
]
