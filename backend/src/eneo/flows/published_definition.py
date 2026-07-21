from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Mapping, TypeGuard, cast
from uuid import UUID

from pydantic import ValidationError

from eneo.flows.assistant_execution_snapshot import stable_hash
from eneo.flows.domain.flow import FlowPersistedJsonObject
from eneo.flows.domain.runtime import RuntimeStep
from eneo.flows.domain.runtime_invariant_exceptions import (
    FlowPublishedDefinitionWithoutExecutableStepsError,
    FlowRuntimeInvariantError,
)
from eneo.flows.enums import FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.flow_metadata import (
    FlowMetadata,
    FlowMetadataParseMode,
    parse_flow_metadata,
)
from eneo.flows.runtime.step_definition_parser import (
    PublishedStepIdentity,
    parse_published_step_identities,
    parse_runtime_steps,
)
from eneo.flows.runtime_input import build_runtime_input_config
from eneo.main.exceptions import BadRequestException

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


class PublishedDefinitionIntegrityStatus(StrEnum):
    VERIFIED = "verified"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class PublishedDefinitionIntegrity:
    """Integrity state for one immutable stored published definition."""

    status: PublishedDefinitionIntegrityStatus
    expected_checksum: str
    current_checksum: str

    def to_dict(self) -> dict[str, str]:
        return {
            "status": self.status.value,
            "expected_checksum": self.expected_checksum,
            "current_checksum": self.current_checksum,
        }


class PublishedDefinitionChecksumMismatchError(FlowBadRequestException):
    __slots__ = ("integrity",)

    def __init__(self, integrity: PublishedDefinitionIntegrity) -> None:
        super().__init__(
            "Published flow definition checksum does not match the stored snapshot. "
            "Do not retry this pinned version. Publish a valid version and start a "
            "new run.",
            code=FlowApiErrorCode.DEFINITION_CHECKSUM_MISMATCH,
            context={
                "expected_checksum": integrity.expected_checksum,
                "current_checksum": integrity.current_checksum,
            },
        )
        self.integrity = integrity


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


class PublishedTemplateIdentityBlockerReason(str, Enum):
    UNKNOWN_SCHEMA = "unknown_schema"
    STEPS_UNREADABLE = "steps_unreadable"
    STEP_UNREADABLE = "step_unreadable"
    UNREADABLE_OUTPUT_CONFIG = "unreadable_output_config"
    MISSING_TEMPLATE_ASSET_ID = "missing_template_asset_id"
    INVALID_TEMPLATE_ASSET_ID = "invalid_template_asset_id"
    INVALID_TEMPLATE_FILE_ID = "invalid_template_file_id"
    MISSING_TEMPLATE_CHECKSUM = "missing_template_checksum"
    ASSET_NOT_LIVE = "asset_not_live"
    ASSET_FILE_MISMATCH = "asset_file_mismatch"
    TEMPLATE_CHECKSUM_MISMATCH = "template_checksum_mismatch"
    AMBIGUOUS_FILE_TO_ASSET_MAPPING = "ambiguous_file_to_asset_mapping"


@dataclass(frozen=True, slots=True)
class PublishedTemplateIdentityAuditSnapshot:
    tenant_id: UUID
    flow_id: UUID
    version: int
    definition_json: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PublishedTemplateIdentityLiveAsset:
    tenant_id: UUID
    flow_id: UUID
    asset_id: UUID
    file_id: UUID
    checksum: str


@dataclass(frozen=True, slots=True)
class PublishedTemplateIdentityBlockerCount:
    reason: PublishedTemplateIdentityBlockerReason
    count: int


@dataclass(frozen=True, slots=True)
class PublishedTemplateIdentityBlockerSample:
    tenant_id: UUID
    flow_id: UUID
    version: int
    step_order: int | None
    reason: PublishedTemplateIdentityBlockerReason
    template_asset_id: UUID | None = None
    template_file_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class PublishedTemplateIdentityAuditResult:
    total_versions: int
    template_fill_steps: int
    ready_template_fill_steps: int
    blocked_template_fill_steps: int
    blocker_counts: tuple[PublishedTemplateIdentityBlockerCount, ...]
    samples: tuple[PublishedTemplateIdentityBlockerSample, ...]

    @property
    def is_ready_for_template_file_fallback_deletion(self) -> bool:
        return not self.blocker_counts


def _step_order_sort_key(step: FlowPersistedJsonObject) -> int:
    step_order = step.get("step_order")
    if isinstance(step_order, int) and not isinstance(step_order, bool):
        return step_order
    return 0


def _is_json_object(value: object) -> TypeGuard[dict[str, object]]:
    return isinstance(value, dict)


def _is_json_array(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def _normalized_uuid(value: object) -> UUID | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _runtime_optional_string(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
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


def _published_template_step_order(step: Mapping[str, object]) -> int | None:
    step_order = step.get("step_order")
    if isinstance(step_order, int) and not isinstance(step_order, bool):
        return step_order
    return None


def audit_published_template_identity_readiness(
    *,
    snapshots: Iterable[PublishedTemplateIdentityAuditSnapshot],
    live_assets: Iterable[PublishedTemplateIdentityLiveAsset],
    sample_limit: int = 50,
) -> PublishedTemplateIdentityAuditResult:
    live_assets_by_id: dict[
        tuple[UUID, UUID, UUID], PublishedTemplateIdentityLiveAsset
    ] = {}
    live_assets_by_file: dict[
        tuple[UUID, UUID, UUID], list[PublishedTemplateIdentityLiveAsset]
    ] = {}
    for asset in live_assets:
        live_assets_by_id[(asset.tenant_id, asset.flow_id, asset.asset_id)] = asset
        live_assets_by_file.setdefault(
            (asset.tenant_id, asset.flow_id, asset.file_id), []
        ).append(asset)

    max_samples = max(sample_limit, 0)
    counts: Counter[PublishedTemplateIdentityBlockerReason] = Counter()
    samples: list[PublishedTemplateIdentityBlockerSample] = []
    total_versions = 0
    template_fill_steps = 0
    ready_template_fill_steps = 0
    blocked_template_fill_steps = 0

    def add_blocker(
        *,
        snapshot: PublishedTemplateIdentityAuditSnapshot,
        step_order: int | None,
        reason: PublishedTemplateIdentityBlockerReason,
        template_asset_id: UUID | None = None,
        template_file_id: UUID | None = None,
    ) -> None:
        counts[reason] += 1
        if len(samples) >= max_samples:
            return
        samples.append(
            PublishedTemplateIdentityBlockerSample(
                tenant_id=snapshot.tenant_id,
                flow_id=snapshot.flow_id,
                version=snapshot.version,
                step_order=step_order,
                reason=reason,
                template_asset_id=template_asset_id,
                template_file_id=template_file_id,
            )
        )

    for snapshot in snapshots:
        total_versions += 1
        if (
            snapshot.definition_json.get("schema_version")
            != FLOW_DEFINITION_SCHEMA_VERSION
        ):
            add_blocker(
                snapshot=snapshot,
                step_order=None,
                reason=PublishedTemplateIdentityBlockerReason.UNKNOWN_SCHEMA,
            )
            continue

        raw_steps = snapshot.definition_json.get("steps")
        if not _is_json_array(raw_steps):
            add_blocker(
                snapshot=snapshot,
                step_order=None,
                reason=PublishedTemplateIdentityBlockerReason.STEPS_UNREADABLE,
            )
            continue

        for raw_step in raw_steps:
            if not _is_json_object(raw_step):
                add_blocker(
                    snapshot=snapshot,
                    step_order=None,
                    reason=PublishedTemplateIdentityBlockerReason.STEP_UNREADABLE,
                )
                continue
            if raw_step.get("output_mode") != FlowOutputMode.TEMPLATE_FILL.value:
                continue

            template_fill_steps += 1
            step_order = _published_template_step_order(raw_step)
            raw_output_config = raw_step.get("output_config")
            if not _is_json_object(raw_output_config):
                add_blocker(
                    snapshot=snapshot,
                    step_order=step_order,
                    reason=(
                        PublishedTemplateIdentityBlockerReason.UNREADABLE_OUTPUT_CONFIG
                    ),
                )
                blocked_template_fill_steps += 1
                continue

            step_blocked = False
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
            template_checksum = _runtime_optional_string(
                raw_output_config.get("template_checksum")
            )

            if unreadable_asset_reference:
                add_blocker(
                    snapshot=snapshot,
                    step_order=step_order,
                    reason=(
                        PublishedTemplateIdentityBlockerReason.INVALID_TEMPLATE_ASSET_ID
                    ),
                    template_file_id=template_file_id,
                )
                step_blocked = True
            elif template_asset_id is None:
                add_blocker(
                    snapshot=snapshot,
                    step_order=step_order,
                    reason=(
                        PublishedTemplateIdentityBlockerReason.MISSING_TEMPLATE_ASSET_ID
                    ),
                    template_file_id=template_file_id,
                )
                step_blocked = True

            if unreadable_file_reference:
                add_blocker(
                    snapshot=snapshot,
                    step_order=step_order,
                    reason=(
                        PublishedTemplateIdentityBlockerReason.INVALID_TEMPLATE_FILE_ID
                    ),
                    template_asset_id=template_asset_id,
                )
                step_blocked = True

            if template_checksum is None:
                add_blocker(
                    snapshot=snapshot,
                    step_order=step_order,
                    reason=(
                        PublishedTemplateIdentityBlockerReason.MISSING_TEMPLATE_CHECKSUM
                    ),
                    template_asset_id=template_asset_id,
                    template_file_id=template_file_id,
                )
                step_blocked = True

            if template_asset_id is None:
                if template_file_id is not None:
                    mapped_assets = live_assets_by_file.get(
                        (snapshot.tenant_id, snapshot.flow_id, template_file_id),
                        [],
                    )
                    if len(mapped_assets) > 1:
                        add_blocker(
                            snapshot=snapshot,
                            step_order=step_order,
                            reason=(
                                PublishedTemplateIdentityBlockerReason.AMBIGUOUS_FILE_TO_ASSET_MAPPING
                            ),
                            template_file_id=template_file_id,
                        )
                        step_blocked = True
            else:
                live_asset = live_assets_by_id.get(
                    (snapshot.tenant_id, snapshot.flow_id, template_asset_id)
                )
                if live_asset is None:
                    add_blocker(
                        snapshot=snapshot,
                        step_order=step_order,
                        reason=PublishedTemplateIdentityBlockerReason.ASSET_NOT_LIVE,
                        template_asset_id=template_asset_id,
                        template_file_id=template_file_id,
                    )
                    step_blocked = True
                else:
                    if (
                        template_file_id is not None
                        and live_asset.file_id != template_file_id
                    ):
                        add_blocker(
                            snapshot=snapshot,
                            step_order=step_order,
                            reason=(
                                PublishedTemplateIdentityBlockerReason.ASSET_FILE_MISMATCH
                            ),
                            template_asset_id=template_asset_id,
                            template_file_id=template_file_id,
                        )
                        step_blocked = True
                    if (
                        template_checksum is not None
                        and live_asset.checksum != template_checksum
                    ):
                        add_blocker(
                            snapshot=snapshot,
                            step_order=step_order,
                            reason=(
                                PublishedTemplateIdentityBlockerReason.TEMPLATE_CHECKSUM_MISMATCH
                            ),
                            template_asset_id=template_asset_id,
                            template_file_id=template_file_id,
                        )
                        step_blocked = True

            if step_blocked:
                blocked_template_fill_steps += 1
            else:
                ready_template_fill_steps += 1

    return PublishedTemplateIdentityAuditResult(
        total_versions=total_versions,
        template_fill_steps=template_fill_steps,
        ready_template_fill_steps=ready_template_fill_steps,
        blocked_template_fill_steps=blocked_template_fill_steps,
        blocker_counts=tuple(
            PublishedTemplateIdentityBlockerCount(reason=reason, count=counts[reason])
            for reason in sorted(counts, key=lambda item: item.value)
        ),
        samples=tuple(samples),
    )


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
    _metadata: FlowMetadata
    _runtime_steps: tuple[RuntimeStep, ...]
    _has_required_runtime_input: bool

    def metadata(self) -> FlowMetadata:
        return self._metadata.model_copy(deep=True)

    def runtime_steps(self) -> list[RuntimeStep]:
        return list(self._runtime_steps)

    def has_required_runtime_input(self) -> bool:
        return self._has_required_runtime_input


def _parse_published_metadata(
    definition_json: Mapping[str, object],
) -> FlowMetadata:
    raw_metadata: object = definition_json.get("metadata_json")
    metadata_json: Mapping[str, object] | None = (
        raw_metadata if _is_json_object(raw_metadata) else None
    )
    try:
        metadata = parse_flow_metadata(
            metadata_json,
            mode=FlowMetadataParseMode.PERSISTED_READ,
        )
    except (BadRequestException, ValidationError) as exc:
        raise BadRequestException(
            "Published flow form schema is invalid.",
            code=FLOW_PUBLISHED_FORM_SCHEMA_INVALID,
            context=(exc.context if isinstance(exc, BadRequestException) else None),
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


def _parse_published_runtime_steps(
    definition_json: Mapping[str, object],
) -> tuple[RuntimeStep, ...]:
    try:
        return tuple(parse_runtime_steps(definition_json))
    except BadRequestException as exc:
        if exc.code is not None:
            raise
        raise BadRequestException(
            str(exc),
            code=FLOW_DEFINITION_STEPS_INVALID,
            context=exc.context,
        ) from exc


def _has_required_runtime_input(runtime_steps: Iterable[RuntimeStep]) -> bool:
    for step in runtime_steps:
        runtime_input = build_runtime_input_config(step.input_config)
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

    A successful return guarantees that the envelope, persisted metadata, and
    every runtime step configuration, binding, output contract, order, and chain
    are valid. The returned value retains those typed validation results so
    functional consumers do not parse the immutable snapshot again.
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
    metadata = _parse_published_metadata(definition_json)
    runtime_steps = _parse_published_runtime_steps(definition_json)
    return PublishedFlowDefinition(
        schema_version=schema_version,
        flow_id=flow_id,
        name=name if isinstance(name, str) else "",
        description=description if isinstance(description, str) else None,
        steps=steps,
        step_identities=step_identities,
        definition_json=dict(definition_json),
        _metadata=metadata,
        _runtime_steps=runtime_steps,
        _has_required_runtime_input=_has_required_runtime_input(runtime_steps),
    )


@dataclass(frozen=True, slots=True)
class _PublishedDefinitionInspection:
    integrity: PublishedDefinitionIntegrity
    definition: PublishedFlowDefinition | None
    parse_error: BadRequestException | FlowRuntimeInvariantError | None


def _inspect_published_definition(
    definition_json: Mapping[str, object],
    *,
    expected_checksum: str,
    flow_version: int,
) -> _PublishedDefinitionInspection:
    current_checksum = published_definition_checksum(definition_json)
    integrity = PublishedDefinitionIntegrity(
        status=PublishedDefinitionIntegrityStatus.INVALID,
        expected_checksum=expected_checksum,
        current_checksum=current_checksum,
    )
    if current_checksum != expected_checksum:
        return _PublishedDefinitionInspection(
            integrity=integrity,
            definition=None,
            parse_error=None,
        )

    try:
        definition = parse_published_definition(
            definition_json,
            flow_version=flow_version,
        )
    except (BadRequestException, FlowRuntimeInvariantError) as exc:
        return _PublishedDefinitionInspection(
            integrity=integrity,
            definition=None,
            parse_error=exc,
        )

    return _PublishedDefinitionInspection(
        integrity=PublishedDefinitionIntegrity(
            status=PublishedDefinitionIntegrityStatus.VERIFIED,
            expected_checksum=expected_checksum,
            current_checksum=current_checksum,
        ),
        definition=definition,
        parse_error=None,
    )


def inspect_published_definition_integrity(
    definition_json: Mapping[str, object],
    *,
    expected_checksum: str,
    flow_version: int,
) -> PublishedDefinitionIntegrity:
    return _inspect_published_definition(
        definition_json,
        expected_checksum=expected_checksum,
        flow_version=flow_version,
    ).integrity


def parse_verified_published_definition(
    definition_json: Mapping[str, object],
    *,
    expected_checksum: str,
    flow_version: int,
) -> PublishedFlowDefinition:
    inspection = _inspect_published_definition(
        definition_json,
        expected_checksum=expected_checksum,
        flow_version=flow_version,
    )
    if inspection.definition is not None:
        return inspection.definition
    if inspection.parse_error is not None:
        raise inspection.parse_error
    raise PublishedDefinitionChecksumMismatchError(inspection.integrity)


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
