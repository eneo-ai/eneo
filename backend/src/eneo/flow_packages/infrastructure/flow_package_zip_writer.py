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
from eneo.resource_packages.archive import write_archive
from eneo.resource_packages.checksum import canonical_json_bytes, json_object_from_model


def write_flow_package(envelope: FlowPackageEnvelope) -> bytes:
    documents: dict[str, BaseModel] = {
        MANIFEST_PATH: envelope.manifest,
        FLOW_DRAFT_PATH: envelope.draft,
        REQUIREMENTS_PATH: envelope.requirements,
        PROVENANCE_PATH: envelope.provenance,
    }

    payloads = {
        path: canonical_json_bytes(json_object_from_model(document))
        for path, document in documents.items()
    }
    payloads.update(envelope.template_payloads)
    return write_archive(
        payloads,
        ordered_paths=(*PACKAGE_DOCUMENT_PATHS, *sorted(envelope.template_payloads)),
    )
