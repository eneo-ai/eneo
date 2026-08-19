from __future__ import annotations

from collections.abc import Mapping
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from eneo.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from eneo.flow_packages.domain.flow_package_envelope import (
    FLOW_DRAFT_PATH,
    MANIFEST_PATH,
    PROVENANCE_PATH,
    REQUIRED_PACKAGE_FILES,
    REQUIREMENTS_PATH,
    FlowPackageEnvelope,
    require_flow_package_manifest,
)
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
    FlowPackageZipUnsafeReason,
)
from eneo.flow_packages.domain.flow_package_limits import MAX_FLOW_PACKAGE_BYTES
from eneo.flow_packages.domain.flow_package_manifest import FlowPackageManifest
from eneo.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageRequirementSet,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpecLocalRefNotPortableError,
    has_flow_mcp_unsupported_error,
)
from eneo.resource_packages.archive import (
    ResourcePackageArchiveError,
    ResourcePackageArchiveLimits,
    read_bounded_json_archive,
)
from eneo.resource_packages.archive import (
    decompression_ratio_too_high as _resource_package_ratio_too_high,
)
from eneo.resource_packages.archive import (
    validate_archive_entry_path as _validate_resource_package_entry_path,
)

MAX_ZIP_ENTRIES = 4
# Four compressed JSON entries plus zip metadata headroom for the current package schema.
MAX_PACKAGE_UPLOAD_BYTES = MAX_FLOW_PACKAGE_BYTES
MAX_PER_ENTRY_COMPRESSED_BYTES = 1 * 1024 * 1024
MAX_PER_ENTRY_UNCOMPRESSED_BYTES = 2 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 8 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_DECOMPRESSION_RATIO = 50

ModelT = TypeVar("ModelT", bound=BaseModel)


def read_flow_package(package_bytes: bytes) -> FlowPackageEnvelope:
    payloads = _read_bounded_json_payloads(package_bytes)
    manifest = _parse_subdocument(
        FlowPackageManifest,
        payloads[MANIFEST_PATH],
        invalid_code=FlowPackageErrorCode.MANIFEST_INVALID,
    )
    require_flow_package_manifest(manifest)
    _validate_flow_profile_entries(payloads)
    draft = _parse_subdocument(
        FlowPackageFlowDraft,
        payloads[FLOW_DRAFT_PATH],
        invalid_code=FlowPackageErrorCode.FLOW_DRAFT_INVALID,
    )
    requirements = _parse_subdocument(
        FlowPackageRequirementSet,
        payloads[REQUIREMENTS_PATH],
        invalid_code=FlowPackageErrorCode.REQUIREMENTS_INVALID,
    )
    provenance = _parse_subdocument(
        FlowPackageProvenance,
        payloads[PROVENANCE_PATH],
        invalid_code=FlowPackageErrorCode.PROVENANCE_INVALID,
    )
    return FlowPackageEnvelope.verify_from_subdocuments(
        manifest=manifest,
        draft=draft,
        requirements=requirements,
        provenance=provenance,
    )


def _read_bounded_json_payloads(package_bytes: bytes) -> dict[str, bytes]:
    try:
        payloads = read_bounded_json_archive(
            package_bytes,
            limits=ResourcePackageArchiveLimits(
                max_entries=MAX_ZIP_ENTRIES,
                max_compressed_entry_bytes=MAX_PER_ENTRY_COMPRESSED_BYTES,
                max_uncompressed_entry_bytes=MAX_PER_ENTRY_UNCOMPRESSED_BYTES,
                max_total_uncompressed_bytes=MAX_TOTAL_UNCOMPRESSED_BYTES,
                max_json_bytes=MAX_JSON_BYTES,
                max_decompression_ratio=MAX_DECOMPRESSION_RATIO,
            ),
        )
    except ResourcePackageArchiveError as exc:
        raise _zip_unsafe(
            FlowPackageZipUnsafeReason(exc.reason.value),
            **exc.context,
        ) from exc
    if MANIFEST_PATH not in payloads:
        raise _zip_unsafe(
            FlowPackageZipUnsafeReason.MISSING_REQUIRED_ENTRY,
            path=MANIFEST_PATH,
        )
    return payloads


def _decompression_ratio_too_high(  # pyright: ignore[reportUnusedFunction]
    *,
    uncompressed_size: int,
    compressed_size: int,
) -> bool:
    return _resource_package_ratio_too_high(
        uncompressed_size=uncompressed_size,
        compressed_size=compressed_size,
        max_ratio=MAX_DECOMPRESSION_RATIO,
    )


def _validate_entry_path(  # pyright: ignore[reportUnusedFunction]
    entry: object,
) -> str:
    try:
        return _validate_resource_package_entry_path(entry)  # type: ignore[arg-type]
    except ResourcePackageArchiveError as exc:
        raise _zip_unsafe(
            FlowPackageZipUnsafeReason(exc.reason.value),
            **exc.context,
        ) from exc


def _validate_flow_profile_entries(payloads: Mapping[str, bytes]) -> None:
    unexpected_files = payloads.keys() - REQUIRED_PACKAGE_FILES
    if unexpected_files:
        raise _zip_unsafe(
            FlowPackageZipUnsafeReason.UNKNOWN_ENTRY,
            path=sorted(unexpected_files)[0],
        )
    missing_files = REQUIRED_PACKAGE_FILES - payloads.keys()
    if missing_files:
        raise _zip_unsafe(
            FlowPackageZipUnsafeReason.MISSING_REQUIRED_ENTRY,
            path=sorted(missing_files)[0],
        )


def _parse_subdocument(
    model: type[ModelT],
    payload: bytes,
    *,
    invalid_code: FlowPackageErrorCode,
) -> ModelT:
    try:
        return model.model_validate_json(
            payload,
            strict=True,
            extra="forbid",
        )
    except ValidationError as exc:
        if _has_unsupported_schema_version(exc):
            raise FlowPackageValidationError(
                code=FlowPackageErrorCode.SCHEMA_UNSUPPORTED,
                message="Flow package schema version is unsupported.",
            ) from exc
        if _has_local_resource_ref_error(exc):
            raise FlowPackageValidationError(
                code=FlowPackageErrorCode.LOCAL_RESOURCE_REFS_NOT_PORTABLE,
                message="Flow package draft contains source-local resource refs.",
            ) from exc
        if _has_removed_flow_mcp_field(exc):
            raise FlowPackageValidationError(
                code=FlowPackageErrorCode.IMPORT_MCP_UNSUPPORTED,
                message="Flow packages do not support MCP fields or resources.",
            ) from exc
        raise FlowPackageValidationError(
            code=invalid_code,
            message="Flow package subdocument is invalid.",
        ) from exc


def _has_unsupported_schema_version(exc: ValidationError) -> bool:
    for error in exc.errors():
        loc = error.get("loc")
        error_type = error.get("type")
        if loc == ("schema_version",) and error_type != "missing":
            return True
    return False


def _has_local_resource_ref_error(exc: ValidationError) -> bool:
    for error in exc.errors():
        ctx = error.get("ctx")
        if not isinstance(ctx, Mapping):
            continue
        original_error = ctx.get("error")
        if isinstance(original_error, AssistantSpecLocalRefNotPortableError):
            return True
    return False


def _has_removed_flow_mcp_field(exc: ValidationError) -> bool:
    if has_flow_mcp_unsupported_error(exc):
        return True
    for error in exc.errors():
        ctx = error.get("ctx")
        if isinstance(ctx, Mapping) and ctx.get("tag") == "mcp_tool":
            return True
    return False


def _zip_unsafe(
    reason: FlowPackageZipUnsafeReason,
    **context: str | int,
) -> FlowPackageValidationError:
    return FlowPackageValidationError(
        code=FlowPackageErrorCode.ZIP_UNSAFE,
        message="Flow package zip is unsafe.",
        context={"reason": reason.value, **context},
    )
