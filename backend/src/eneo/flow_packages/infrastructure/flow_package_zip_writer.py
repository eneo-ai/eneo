from __future__ import annotations

from pydantic import BaseModel

from eneo.flow_packages.domain.flow_package_envelope import (
    FLOW_DRAFT_PATH,
    MANIFEST_PATH,
    PACKAGE_DOCUMENT_PATHS,
    PROVENANCE_PATH,
    REQUIREMENTS_PATH,
    FlowPackageEnvelope,
)
from eneo.resource_packages.archive import write_json_archive


def write_flow_package(envelope: FlowPackageEnvelope) -> bytes:
    documents: dict[str, BaseModel] = {
        MANIFEST_PATH: envelope.manifest,
        FLOW_DRAFT_PATH: envelope.draft,
        REQUIREMENTS_PATH: envelope.requirements,
        PROVENANCE_PATH: envelope.provenance,
    }

    return write_json_archive(documents, ordered_paths=PACKAGE_DOCUMENT_PATHS)
