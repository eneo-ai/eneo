from __future__ import annotations

import zipfile
from io import BytesIO

from pydantic import BaseModel

from eneo.flow_packages.domain.flow_package_checksum import (
    canonical_json_bytes,
    json_object_from_model,
)
from eneo.flow_packages.domain.flow_package_envelope import (
    FLOW_DRAFT_PATH,
    MANIFEST_PATH,
    PACKAGE_DOCUMENT_PATHS,
    PROVENANCE_PATH,
    REQUIREMENTS_PATH,
    FlowPackageEnvelope,
)

_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_FILE_MODE = 0o600 << 16
_ZIP_COMPRESSION_LEVEL = 9


def write_flow_package(envelope: FlowPackageEnvelope) -> bytes:
    documents: dict[str, BaseModel] = {
        MANIFEST_PATH: envelope.manifest,
        FLOW_DRAFT_PATH: envelope.draft,
        REQUIREMENTS_PATH: envelope.requirements,
        PROVENANCE_PATH: envelope.provenance,
    }

    buffer = BytesIO()
    with zipfile.ZipFile(
        buffer,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=_ZIP_COMPRESSION_LEVEL,
    ) as package:
        for path in PACKAGE_DOCUMENT_PATHS:
            package.writestr(
                _package_entry(path),
                canonical_json_bytes(json_object_from_model(documents[path])),
            )
    return buffer.getvalue()


def _package_entry(path: str) -> zipfile.ZipInfo:
    # Pin zip metadata for local byte-stability; content_checksum is the package identity.
    entry = zipfile.ZipInfo(path, date_time=_ZIP_TIMESTAMP)
    entry.compress_type = zipfile.ZIP_DEFLATED
    entry.external_attr = _ZIP_FILE_MODE
    return entry
