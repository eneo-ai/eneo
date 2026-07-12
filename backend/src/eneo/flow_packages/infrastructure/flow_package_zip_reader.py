from __future__ import annotations

import stat
import zipfile
from collections.abc import Mapping
from io import BytesIO
from pathlib import PurePosixPath
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
        package = zipfile.ZipFile(BytesIO(package_bytes))
    except zipfile.BadZipFile as exc:
        raise _zip_unsafe(FlowPackageZipUnsafeReason.BAD_ZIP) from exc

    with package:
        entries = package.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise _zip_unsafe(
                FlowPackageZipUnsafeReason.TOO_MANY_ENTRIES,
                count=len(entries),
                max_entries=MAX_ZIP_ENTRIES,
            )

        payloads: dict[str, bytes] = {}
        total_uncompressed_bytes = 0
        for entry in entries:
            normalized_path = _validate_entry_path(entry)
            if entry.compress_size > MAX_PER_ENTRY_COMPRESSED_BYTES:
                raise _zip_unsafe(
                    FlowPackageZipUnsafeReason.COMPRESSED_ENTRY_TOO_LARGE,
                    path=normalized_path,
                    size=entry.compress_size,
                    max_size=MAX_PER_ENTRY_COMPRESSED_BYTES,
                )
            if normalized_path in payloads:
                raise _zip_unsafe(
                    FlowPackageZipUnsafeReason.DUPLICATE_ENTRY,
                    path=normalized_path,
                )
            remaining_budget = MAX_TOTAL_UNCOMPRESSED_BYTES - total_uncompressed_bytes
            if remaining_budget <= 0:
                raise _zip_unsafe(
                    FlowPackageZipUnsafeReason.TOTAL_UNCOMPRESSED_TOO_LARGE,
                    max_size=MAX_TOTAL_UNCOMPRESSED_BYTES,
                )
            read_limit = min(
                MAX_PER_ENTRY_UNCOMPRESSED_BYTES,
                remaining_budget,
            )
            with package.open(entry, "r") as file:
                payload = file.read(read_limit + 1)

            if len(payload) > MAX_PER_ENTRY_UNCOMPRESSED_BYTES:
                raise _zip_unsafe(
                    FlowPackageZipUnsafeReason.UNCOMPRESSED_ENTRY_TOO_LARGE,
                    path=normalized_path,
                    size=len(payload),
                    max_size=MAX_PER_ENTRY_UNCOMPRESSED_BYTES,
                )
            if len(payload) > remaining_budget:
                raise _zip_unsafe(
                    FlowPackageZipUnsafeReason.TOTAL_UNCOMPRESSED_TOO_LARGE,
                    path=normalized_path,
                    size=total_uncompressed_bytes + len(payload),
                    max_size=MAX_TOTAL_UNCOMPRESSED_BYTES,
                )

            total_uncompressed_bytes += len(payload)
            if _decompression_ratio_too_high(
                uncompressed_size=len(payload),
                compressed_size=entry.compress_size,
            ):
                raise _zip_unsafe(
                    FlowPackageZipUnsafeReason.DECOMPRESSION_RATIO_TOO_HIGH,
                    path=normalized_path,
                    ratio=MAX_DECOMPRESSION_RATIO + 1,
                    max_ratio=MAX_DECOMPRESSION_RATIO,
                )
            if len(payload) > MAX_JSON_BYTES:
                raise _zip_unsafe(
                    FlowPackageZipUnsafeReason.JSON_TOO_LARGE,
                    path=normalized_path,
                    size=len(payload),
                    max_size=MAX_JSON_BYTES,
                )
            payloads[normalized_path] = payload

        if MANIFEST_PATH not in payloads:
            raise _zip_unsafe(
                FlowPackageZipUnsafeReason.MISSING_REQUIRED_ENTRY,
                path=MANIFEST_PATH,
            )
        return payloads


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


def _validate_entry_path(entry: zipfile.ZipInfo) -> str:
    raw_path = entry.filename
    if entry.is_dir():
        raise _zip_unsafe(FlowPackageZipUnsafeReason.DIRECTORY_ENTRY, path=raw_path)
    if _is_symlink(entry):
        raise _zip_unsafe(FlowPackageZipUnsafeReason.SYMLINK_ENTRY, path=raw_path)
    if "\\" in raw_path:
        raise _zip_unsafe(FlowPackageZipUnsafeReason.BACKSLASH_PATH, path=raw_path)

    path = PurePosixPath(raw_path)
    if path.is_absolute():
        raise _zip_unsafe(FlowPackageZipUnsafeReason.ABSOLUTE_PATH, path=raw_path)
    if ".." in path.parts:
        raise _zip_unsafe(FlowPackageZipUnsafeReason.PATH_TRAVERSAL, path=raw_path)
    normalized = path.as_posix()
    if not normalized or normalized == ".":
        raise _zip_unsafe(FlowPackageZipUnsafeReason.UNKNOWN_ENTRY, path=raw_path)
    return normalized


def _is_symlink(entry: zipfile.ZipInfo) -> bool:
    mode = entry.external_attr >> 16
    return stat.S_ISLNK(mode)


def _decompression_ratio_too_high(
    *,
    uncompressed_size: int,
    compressed_size: int,
) -> bool:
    if uncompressed_size == 0:
        return False
    if compressed_size == 0:
        return True
    return (uncompressed_size / compressed_size) > MAX_DECOMPRESSION_RATIO


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
