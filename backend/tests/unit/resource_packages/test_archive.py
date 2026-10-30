import zipfile
from io import BytesIO

import pytest
from pydantic import BaseModel

from eneo.resource_packages.archive import (
    ResourcePackageArchiveError,
    ResourcePackageArchiveLimits,
    ResourcePackageArchiveUnsafeReason,
    read_bounded_json_archive,
    write_json_archive,
)


class _Document(BaseModel):
    value: str


def _limits() -> ResourcePackageArchiveLimits:
    return ResourcePackageArchiveLimits(
        max_entries=2,
        max_compressed_entry_bytes=1024,
        max_uncompressed_entry_bytes=1024,
        max_total_uncompressed_bytes=2048,
        max_json_bytes=1024,
        max_decompression_ratio=100,
    )


def test_archive_round_trip_is_resource_kind_neutral_and_deterministic() -> None:
    documents = {
        "manifest.json": _Document(value="manifest"),
        "assistant.json": _Document(value="assistant"),
    }

    first = write_json_archive(
        documents,
        ordered_paths=("manifest.json", "assistant.json"),
    )
    second = write_json_archive(
        documents,
        ordered_paths=("manifest.json", "assistant.json"),
    )

    assert first == second
    assert set(read_bounded_json_archive(first, limits=_limits())) == {
        "manifest.json",
        "assistant.json",
    }


def test_archive_rejects_cross_directory_traversal() -> None:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as package:
        package.writestr("../assistant.json", "{}")

    with pytest.raises(ResourcePackageArchiveError) as exc_info:
        read_bounded_json_archive(buffer.getvalue(), limits=_limits())

    assert exc_info.value.reason is ResourcePackageArchiveUnsafeReason.PATH_TRAVERSAL
