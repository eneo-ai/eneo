from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Mapping, TypeGuard, cast
from uuid import UUID

from intric.flows.assistant_execution_snapshot import stable_hash
from intric.flows.domain.flow import FlowPersistedJsonObject
from intric.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
)
from intric.flows.flow_api_error_code import FlowApiErrorCode
from intric.flows.flow_metadata import (
    FlowMetadata,
    FlowMetadataParseMode,
    parse_flow_metadata,
)
from intric.flows.runtime.models import RuntimeStep
from intric.flows.runtime.step_definition_parser import (
    PublishedStepIdentity,
    parse_published_step_identities,
    parse_runtime_steps,
)
from intric.flows.runtime_input import build_runtime_input_config
from intric.main.exceptions import BadRequestException

FLOW_DEFINITION_SCHEMA_VERSION = 1

FLOW_DEFINITION_SCHEMA_VERSION_MISSING = (
    FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_MISSING.value
)
FLOW_DEFINITION_SCHEMA_VERSION_UNSUPPORTED = (
    FlowApiErrorCode.DEFINITION_SCHEMA_VERSION_UNSUPPORTED.value
)
FLOW_DEFINITION_FLOW_ID_INVALID = FlowApiErrorCode.DEFINITION_FLOW_ID_INVALID.value
FLOW_DEFINITION_STEPS_INVALID = FlowApiErrorCode.DEFINITION_STEPS_INVALID.value
FLOW_PUBLISHED_FORM_SCHEMA_INVALID = (
    FlowApiErrorCode.PUBLISHED_FORM_SCHEMA_INVALID.value
)


class PublishedTemplateReferenceUndeterminedReason(str, Enum):
    UNKNOWN_SCHEMA = "unknown_schema"
    UNREADABLE_REFERENCE = "unreadable_reference"


@dataclass(frozen=True, slots=True)
class PublishedTemplateReferenceScan:
    template_asset_ids: frozenset[UUID]
    template_file_ids: frozenset[UUID]
    undetermined_reason: PublishedTemplateReferenceUndeterminedReason | None = None

    @property
    def can_determine_safety(self) -> bool:
        return self.undetermined_reason is None

    def may_reference(self, *, template_asset_id: UUID, template_file_id: UUID) -> bool:
        return (
            not self.can_determine_safety
            or template_asset_id in self.template_asset_ids
            or template_file_id in self.template_file_ids
        )


def _step_order_sort_key(step: FlowPersistedJsonObject) -> int:
    step_order = step.get("step_order")
    if isinstance(step_order, int) and not isinstance(step_order, bool):
        return step_order
    return 0


def _is_json_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _normalized_uuid(value: object) -> UUID | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _template_reference_from_output_config(
    output_config: Mapping[str, object],
    key: str,
) -> tuple[UUID | None, bool]:
    value = output_config.get(key)
    if value in (None, ""):
        return None, False
    normalized = _normalized_uuid(value)
    return normalized, normalized is None


def scan_published_template_references(
    definition_json: Mapping[str, object],
) -> PublishedTemplateReferenceScan:
    """Return template ids visible in a known-schema published snapshot.

    Unknown schemas and unreadable template-reference values are not safe to
    reclaim because over-reclaiming a blob is unrecoverable while retention can
    clean up a skipped blob after a schema-aware follow-up.
    """
    schema_version = definition_json.get("schema_version")
    if schema_version != FLOW_DEFINITION_SCHEMA_VERSION:
        return PublishedTemplateReferenceScan(
            template_asset_ids=frozenset(),
            template_file_ids=frozenset(),
            undetermined_reason=(
                PublishedTemplateReferenceUndeterminedReason.UNKNOWN_SCHEMA
            ),
        )

    asset_ids: set[UUID] = set()
    file_ids: set[UUID] = set()
    raw_steps = definition_json.get("steps")
    if not isinstance(raw_steps, list):
        return PublishedTemplateReferenceScan(
            template_asset_ids=frozenset(),
            template_file_ids=frozenset(),
        )

    for raw_step in cast(list[object], raw_steps):
        if not _is_json_object(raw_step):
            continue
        raw_output_config = raw_step.get("output_config")
        if not _is_json_object(raw_output_config):
            continue
        template_asset_id, unreadable_asset_reference = (
            _template_reference_from_output_config(
                raw_output_config,
                "template_asset_id",
            )
        )
        template_file_id, unreadable_file_reference = (
            _template_reference_from_output_config(
                raw_output_config,
                "template_file_id",
            )
        )
        if unreadable_asset_reference or unreadable_file_reference:
            return PublishedTemplateReferenceScan(
                template_asset_ids=frozenset(asset_ids),
                template_file_ids=frozenset(file_ids),
                undetermined_reason=(
                    PublishedTemplateReferenceUndeterminedReason.UNREADABLE_REFERENCE
                ),
            )
        if template_asset_id is not None:
            asset_ids.add(template_asset_id)
        if template_file_id is not None:
            file_ids.add(template_file_id)

    return PublishedTemplateReferenceScan(
        template_asset_ids=frozenset(asset_ids),
        template_file_ids=frozenset(file_ids),
    )


def merge_published_template_reference_scans(
    scans: Iterable[PublishedTemplateReferenceScan],
) -> PublishedTemplateReferenceScan:
    asset_ids: set[UUID] = set()
    file_ids: set[UUID] = set()
    for scan in scans:
        asset_ids.update(scan.template_asset_ids)
        file_ids.update(scan.template_file_ids)
        if scan.undetermined_reason is not None:
            return PublishedTemplateReferenceScan(
                template_asset_ids=frozenset(asset_ids),
                template_file_ids=frozenset(file_ids),
                undetermined_reason=scan.undetermined_reason,
            )
    return PublishedTemplateReferenceScan(
        template_asset_ids=frozenset(asset_ids),
        template_file_ids=frozenset(file_ids),
    )


@dataclass(frozen=True)
class PublishedFlowDefinition:
    schema_version: int
    flow_id: UUID
    name: str
    description: str | None
    steps: list[FlowPersistedJsonObject]
    step_identities: list[PublishedStepIdentity]
    definition_json: FlowPersistedJsonObject

    def metadata(self) -> FlowMetadata:
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
                context=exc.context,
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

    def has_required_runtime_input(self) -> bool:
        for step in self.steps:
            raw_input_config: object = step.get("input_config")
            if raw_input_config is None:
                input_config = None
            elif _is_json_object(raw_input_config):
                input_config = raw_input_config
            else:
                raise BadRequestException("Step input_config must be an object.")
            runtime_input = build_runtime_input_config(input_config)
            if runtime_input.enabled and runtime_input.required:
                return True
        return False


def build_published_definition_json(
    *,
    flow_id: UUID,
    name: str,
    description: str | None,
    metadata_json: FlowPersistedJsonObject | None,
    steps: list[FlowPersistedJsonObject],
) -> FlowPersistedJsonObject:
    sorted_steps: list[FlowPersistedJsonObject] = sorted(
        steps, key=_step_order_sort_key
    )
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
    *,
    flow_version: int,
) -> PublishedFlowDefinition:
    """Parse and validate a published snapshot.

    A successful return guarantees that the envelope is well-formed and all step
    identities are valid and non-empty.
    """
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
    steps = [cast(FlowPersistedJsonObject, step) for step in step_items]
    step_identities = parse_published_step_identities(steps)
    if not step_identities:
        raise FlowPublishedDefinitionWithoutExecutableStepsError(
            flow_id=flow_id,
            flow_version=flow_version,
        )
    return PublishedFlowDefinition(
        schema_version=schema_version,
        flow_id=flow_id,
        name=name if isinstance(name, str) else "",
        description=description if isinstance(description, str) else None,
        steps=steps,
        step_identities=step_identities,
        definition_json=dict(definition_json),
    )


def parse_published_runtime_steps(
    definition_json: Mapping[str, object],
    *,
    flow_version: int,
) -> list[RuntimeStep]:
    """Return runtime steps in published execution order.

    Published definitions are written through `build_published_definition_json`,
    which sorts by `step_order`. The runtime parser also rejects snapshots whose
    stored step order is not contiguous and ascending, so callers can safely use
    the final list item as the terminal step. The wrapped parser also guarantees
    at least one executable step identity.
    """
    return parse_published_definition(
        definition_json,
        flow_version=flow_version,
    ).runtime_steps()


def published_definition_checksum(definition_json: Mapping[str, object]) -> str:
    return stable_hash(definition_json)
