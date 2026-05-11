from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, TypeGuard, cast
from uuid import UUID

from intric.flows.assistant_execution_snapshot import stable_hash
from intric.flows.domain.flow import JsonObject
from intric.flows.flow_metadata import (
    FlowMetadataParseMode,
    FlowMetadataV1,
    parse_flow_metadata,
)
from intric.flows.runtime.models import RuntimeStep
from intric.flows.runtime.step_definition_parser import parse_runtime_steps
from intric.main.exceptions import BadRequestException

FLOW_DEFINITION_SCHEMA_VERSION = 1

FLOW_DEFINITION_SCHEMA_VERSION_MISSING = "flow_definition_schema_version_missing"
FLOW_DEFINITION_SCHEMA_VERSION_UNSUPPORTED = (
    "flow_definition_schema_version_unsupported"
)
FLOW_DEFINITION_FLOW_ID_INVALID = "flow_definition_flow_id_invalid"
FLOW_DEFINITION_STEPS_INVALID = "flow_definition_steps_invalid"
FLOW_PUBLISHED_FORM_SCHEMA_INVALID = "flow_published_form_schema_invalid"


def _step_order_sort_key(step: JsonObject) -> int:
    step_order = step.get("step_order")
    if isinstance(step_order, int) and not isinstance(step_order, bool):
        return step_order
    return 0


def _is_json_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


@dataclass(frozen=True)
class PublishedFlowDefinition:
    schema_version: int
    flow_id: UUID
    name: str
    description: str | None
    steps: list[JsonObject]
    definition_json: JsonObject

    def metadata(self) -> FlowMetadataV1:
        raw_metadata: object = self.definition_json.get("metadata_json")
        metadata_json: Mapping[str, object] | None = (
            raw_metadata if _is_json_object(raw_metadata) else None
        )
        try:
            metadata = parse_flow_metadata(
                metadata_json,
                mode=FlowMetadataParseMode.PERSISTED_READ,
            )
        except BadRequestException as exc:
            raise BadRequestException(
                "Published flow form schema is invalid.",
                code=FLOW_PUBLISHED_FORM_SCHEMA_INVALID,
            ) from exc
        if (
            metadata_json is not None
            and metadata_json.get("form_schema") is not None
            and metadata.form_schema is None
        ):
            raise BadRequestException(
                "Published flow form schema is invalid.",
                code=FLOW_PUBLISHED_FORM_SCHEMA_INVALID,
            )
        return metadata

    def runtime_steps(self) -> list[RuntimeStep]:
        try:
            return parse_runtime_steps(self.definition_json)
        except BadRequestException as exc:
            if exc.code is not None:
                raise
            raise BadRequestException(
                str(exc),
                code=FLOW_DEFINITION_STEPS_INVALID,
                context=exc.context,
            ) from exc

    def checksum(self) -> str:
        return published_definition_checksum(self.definition_json)


def build_published_definition_json(
    *,
    flow_id: UUID,
    name: str,
    description: str | None,
    metadata_json: JsonObject | None,
    steps: list[JsonObject],
) -> JsonObject:
    sorted_steps: list[JsonObject] = sorted(steps, key=_step_order_sort_key)
    return {
        "schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
        "flow_id": str(flow_id),
        "name": name,
        "description": description,
        "metadata_json": metadata_json,
        "steps": sorted_steps,
    }


def parse_published_definition(
    definition_json: Mapping[str, object],
) -> PublishedFlowDefinition:
    schema_version = definition_json.get("schema_version")
    if not isinstance(schema_version, int):
        raise BadRequestException(
            "Flow definition snapshot is missing schema_version.",
            code=FLOW_DEFINITION_SCHEMA_VERSION_MISSING,
        )
    if schema_version != FLOW_DEFINITION_SCHEMA_VERSION:
        raise BadRequestException(
            "Flow definition snapshot schema_version is unsupported.",
            code=FLOW_DEFINITION_SCHEMA_VERSION_UNSUPPORTED,
            context={
                "schema_version": schema_version,
                "supported_schema_version": FLOW_DEFINITION_SCHEMA_VERSION,
            },
        )

    raw_steps = definition_json.get("steps")
    if not isinstance(raw_steps, list):
        raise BadRequestException(
            "Flow definition snapshot is missing steps.",
            code=FLOW_DEFINITION_STEPS_INVALID,
        )
    step_items = cast(list[object], raw_steps)
    if not all(isinstance(step, dict) for step in step_items):
        raise BadRequestException(
            "Invalid step definition in flow snapshot.",
            code=FLOW_DEFINITION_STEPS_INVALID,
        )

    try:
        flow_id = UUID(str(definition_json["flow_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise BadRequestException(
            "Flow definition snapshot has an invalid flow_id.",
            code=FLOW_DEFINITION_FLOW_ID_INVALID,
            context={"field": "flow_id"},
        ) from exc

    name = definition_json.get("name")
    description = definition_json.get("description")
    return PublishedFlowDefinition(
        schema_version=schema_version,
        flow_id=flow_id,
        name=name if isinstance(name, str) else "",
        description=description if isinstance(description, str) else None,
        steps=[cast(JsonObject, step) for step in step_items],
        definition_json=dict(definition_json),
    )


def parse_published_runtime_steps(
    definition_json: Mapping[str, object],
) -> list[RuntimeStep]:
    """Return runtime steps in published execution order.

    Published definitions are written through `build_published_definition_json`,
    which sorts by `step_order`. The runtime parser also rejects snapshots whose
    stored step order is not contiguous and ascending, so callers can safely use
    the final list item as the terminal step.
    """
    return parse_published_definition(definition_json).runtime_steps()


def published_definition_checksum(definition_json: Mapping[str, object]) -> str:
    return stable_hash(definition_json)
