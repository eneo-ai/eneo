from __future__ import annotations

import stat
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from pathlib import PurePosixPath

from pydantic import BaseModel

from eneo.resource_packages.checksum import (
    canonical_json_bytes,
    json_object_from_model,
)

_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_FILE_MODE = 0o600 << 16
_ZIP_COMPRESSION_LEVEL = 9


class ResourcePackageArchiveUnsafeReason(StrEnum):
    BAD_ZIP = "bad_zip"
    TOO_MANY_ENTRIES = "too_many_entries"
    DIRECTORY_ENTRY = "directory_entry"
    SYMLINK_ENTRY = "symlink_entry"
    ABSOLUTE_PATH = "absolute_path"
    PATH_TRAVERSAL = "path_traversal"
    BACKSLASH_PATH = "backslash_path"
    DUPLICATE_ENTRY = "duplicate_entry"
    COMPRESSED_ENTRY_TOO_LARGE = "compressed_entry_too_large"
    UNCOMPRESSED_ENTRY_TOO_LARGE = "uncompressed_entry_too_large"
    TOTAL_UNCOMPRESSED_TOO_LARGE = "total_uncompressed_too_large"
    DECOMPRESSION_RATIO_TOO_HIGH = "decompression_ratio_too_high"
    JSON_TOO_LARGE = "json_too_large"
    UNKNOWN_ENTRY = "unknown_entry"


class ResourcePackageArchiveError(ValueError):
    def __init__(
        self,
        reason: ResourcePackageArchiveUnsafeReason,
        **context: str | int,
    ) -> None:
        self.reason = reason
        self.context = context
        super().__init__(f"Unsafe resource-package archive: {reason.value}.")


@dataclass(frozen=True, slots=True)
class ResourcePackageArchiveLimits:
    max_entries: int
    max_compressed_entry_bytes: int
    max_uncompressed_entry_bytes: int
    max_total_uncompressed_bytes: int
    max_json_bytes: int
    max_decompression_ratio: int


def read_bounded_json_archive(
    package_bytes: bytes,
    *,
    limits: ResourcePackageArchiveLimits,
) -> dict[str, bytes]:
    try:
        package = zipfile.ZipFile(BytesIO(package_bytes))
    except zipfile.BadZipFile as exc:
        raise ResourcePackageArchiveError(
            ResourcePackageArchiveUnsafeReason.BAD_ZIP
        ) from exc

    with package:
        entries = package.infolist()
        if len(entries) > limits.max_entries:
            raise ResourcePackageArchiveError(
                ResourcePackageArchiveUnsafeReason.TOO_MANY_ENTRIES,
                count=len(entries),
                max_entries=limits.max_entries,
            )

        payloads: dict[str, bytes] = {}
        total_uncompressed_bytes = 0
        for entry in entries:
            normalized_path = validate_archive_entry_path(entry)
            if entry.compress_size > limits.max_compressed_entry_bytes:
                raise ResourcePackageArchiveError(
                    ResourcePackageArchiveUnsafeReason.COMPRESSED_ENTRY_TOO_LARGE,
                    path=normalized_path,
                    size=entry.compress_size,
                    max_size=limits.max_compressed_entry_bytes,
                )
            if normalized_path in payloads:
                raise ResourcePackageArchiveError(
                    ResourcePackageArchiveUnsafeReason.DUPLICATE_ENTRY,
                    path=normalized_path,
                )
            remaining_budget = (
                limits.max_total_uncompressed_bytes - total_uncompressed_bytes
            )
            if remaining_budget <= 0:
                raise ResourcePackageArchiveError(
                    ResourcePackageArchiveUnsafeReason.TOTAL_UNCOMPRESSED_TOO_LARGE,
                    max_size=limits.max_total_uncompressed_bytes,
                )
            read_limit = min(
                limits.max_uncompressed_entry_bytes,
                remaining_budget,
            )
            with package.open(entry, "r") as file:
                payload = file.read(read_limit + 1)

            if len(payload) > limits.max_uncompressed_entry_bytes:
                raise ResourcePackageArchiveError(
                    ResourcePackageArchiveUnsafeReason.UNCOMPRESSED_ENTRY_TOO_LARGE,
                    path=normalized_path,
                    size=len(payload),
                    max_size=limits.max_uncompressed_entry_bytes,
                )
            if len(payload) > remaining_budget:
                raise ResourcePackageArchiveError(
                    ResourcePackageArchiveUnsafeReason.TOTAL_UNCOMPRESSED_TOO_LARGE,
                    path=normalized_path,
                    size=total_uncompressed_bytes + len(payload),
                    max_size=limits.max_total_uncompressed_bytes,
                )

            total_uncompressed_bytes += len(payload)
            if decompression_ratio_too_high(
                uncompressed_size=len(payload),
                compressed_size=entry.compress_size,
                max_ratio=limits.max_decompression_ratio,
            ):
                raise ResourcePackageArchiveError(
                    ResourcePackageArchiveUnsafeReason.DECOMPRESSION_RATIO_TOO_HIGH,
                    path=normalized_path,
                    ratio=limits.max_decompression_ratio + 1,
                    max_ratio=limits.max_decompression_ratio,
                )
            if len(payload) > limits.max_json_bytes:
                raise ResourcePackageArchiveError(
                    ResourcePackageArchiveUnsafeReason.JSON_TOO_LARGE,
                    path=normalized_path,
                    size=len(payload),
                    max_size=limits.max_json_bytes,
                )
            payloads[normalized_path] = payload
        return payloads


def write_json_archive(
    documents: Mapping[str, BaseModel],
    *,
    ordered_paths: Sequence[str],
) -> bytes:
    if set(documents) != set(ordered_paths):
        raise ValueError("Archive documents must exactly match ordered paths.")

    buffer = BytesIO()
    with zipfile.ZipFile(
        buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=_ZIP_COMPRESSION_LEVEL,
    ) as package:
        for path in ordered_paths:
            package.writestr(
                _package_entry(path),
                canonical_json_bytes(json_object_from_model(documents[path])),
            )
    return buffer.getvalue()


def _package_entry(path: str) -> zipfile.ZipInfo:
    entry = zipfile.ZipInfo(path, date_time=_ZIP_TIMESTAMP)
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = _ZIP_FILE_MODE
    return entry


def validate_archive_entry_path(entry: zipfile.ZipInfo) -> str:
    raw_path = entry.filename
    if entry.is_dir():
        raise ResourcePackageArchiveError(
            ResourcePackageArchiveUnsafeReason.DIRECTORY_ENTRY,
            path=raw_path,
        )
    if _is_symlink(entry):
        raise ResourcePackageArchiveError(
            ResourcePackageArchiveUnsafeReason.SYMLINK_ENTRY,
            path=raw_path,
        )
    if "\\" in raw_path:
        raise ResourcePackageArchiveError(
            ResourcePackageArchiveUnsafeReason.BACKSLASH_PATH,
            path=raw_path,
        )

    path = PurePosixPath(raw_path)
    if path.is_absolute():
        raise ResourcePackageArchiveError(
            ResourcePackageArchiveUnsafeReason.ABSOLUTE_PATH,
            path=raw_path,
        )
    if ".." in path.parts:
        raise ResourcePackageArchiveError(
            ResourcePackageArchiveUnsafeReason.PATH_TRAVERSAL,
            path=raw_path,
        )
    normalized = path.as_posix()
    if not normalized or normalized == ".":
        raise ResourcePackageArchiveError(
            ResourcePackageArchiveUnsafeReason.UNKNOWN_ENTRY,
            path=raw_path,
        )
    return normalized


def _is_symlink(entry: zipfile.ZipInfo) -> bool:
    mode = entry.external_attr >> 16
    return stat.S_ISLNK(mode)


def decompression_ratio_too_high(
    *,
    uncompressed_size: int,
    compressed_size: int,
    max_ratio: int,
) -> bool:
    if uncompressed_size == 0:
        return False
    if compressed_size == 0:
        return True
    return (uncompressed_size / compressed_size) > max_ratio
