from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from eneo.flow_packages.domain.flow_package_checksum import (
    compose_content_checksum,
    hash_json_value,
)
from eneo.flow_packages.domain.flow_package_draft import FlowPackageFlowDraft
from eneo.flow_packages.domain.flow_package_errors import (
    FlowPackageErrorCode,
    FlowPackageValidationError,
)
from eneo.flow_packages.domain.flow_package_manifest import (
    FLOW_PACKAGE_PAYLOAD_SCHEMA,
    EneoPackageKind,
    FlowPackageManifest,
    FlowPackageManifestMetadata,
)
from eneo.flow_packages.domain.flow_package_provenance import FlowPackageProvenance
from eneo.flow_packages.domain.flow_package_requirements import (
    FlowPackageRequirementSet,
)
from eneo.flows.flow_authoring_spec import FlowDraftSpecCore

MANIFEST_PATH = "manifest.json"
FLOW_DRAFT_PATH = "flow.draft.json"
REQUIREMENTS_PATH = "requirements.json"
PROVENANCE_PATH = "provenance.json"

PACKAGE_DOCUMENT_PATHS = (
    MANIFEST_PATH,
    FLOW_DRAFT_PATH,
    REQUIREMENTS_PATH,
    PROVENANCE_PATH,
)
REQUIRED_PACKAGE_FILES = frozenset(PACKAGE_DOCUMENT_PATHS)


@dataclass(frozen=True, slots=True)
class _FlowPackageDocumentHashes:
    spec_hash: str
    manifest_hash: str
    requirements_hash: str
    provenance_hash: str
    content_checksum: str


class FlowPackageEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    manifest: FlowPackageManifest
    draft: FlowPackageFlowDraft
    requirements: FlowPackageRequirementSet
    provenance: FlowPackageProvenance
    spec_hash: str
    manifest_hash: str
    requirements_hash: str
    provenance_hash: str
    content_checksum: str

    @property
    def spec(self) -> FlowDraftSpecCore:
        return self.draft.spec

    @classmethod
    def verify_from_subdocuments(
        cls,
        *,
        manifest: FlowPackageManifest,
        draft: FlowPackageFlowDraft,
        requirements: FlowPackageRequirementSet,
        provenance: FlowPackageProvenance,
    ) -> "FlowPackageEnvelope":
        _require_flow_payload(manifest)
        hashes = _calculate_hashes(
            manifest_metadata=manifest,
            draft=draft,
            requirements=requirements,
            provenance=provenance,
        )
        if manifest.content_checksum != hashes.content_checksum:
            raise FlowPackageValidationError(
                code=FlowPackageErrorCode.CHECKSUM_MISMATCH,
                message="Flow package content checksum does not match.",
            )
        return cls._from_subdocuments(
            manifest=manifest,
            draft=draft,
            requirements=requirements,
            provenance=provenance,
            hashes=hashes,
        )

    @classmethod
    def build_for_export(
        cls,
        *,
        manifest_metadata: FlowPackageManifestMetadata,
        draft: FlowPackageFlowDraft,
        requirements: FlowPackageRequirementSet,
        provenance: FlowPackageProvenance,
    ) -> "FlowPackageEnvelope":
        _require_flow_payload(manifest_metadata)
        hashes = _calculate_hashes(
            manifest_metadata=manifest_metadata,
            draft=draft,
            requirements=requirements,
            provenance=provenance,
        )
        return cls._from_subdocuments(
            manifest=manifest_metadata.with_content_checksum(hashes.content_checksum),
            draft=draft,
            requirements=requirements,
            provenance=provenance,
            hashes=hashes,
        )

    @classmethod
    def _from_subdocuments(
        cls,
        *,
        manifest: FlowPackageManifest,
        draft: FlowPackageFlowDraft,
        requirements: FlowPackageRequirementSet,
        provenance: FlowPackageProvenance,
        hashes: _FlowPackageDocumentHashes,
    ) -> "FlowPackageEnvelope":
        return cls(
            manifest=manifest,
            draft=draft,
            requirements=requirements,
            provenance=provenance,
            spec_hash=hashes.spec_hash,
            manifest_hash=hashes.manifest_hash,
            requirements_hash=hashes.requirements_hash,
            provenance_hash=hashes.provenance_hash,
            content_checksum=hashes.content_checksum,
        )


def _calculate_hashes(
    *,
    manifest_metadata: FlowPackageManifestMetadata,
    draft: FlowPackageFlowDraft,
    requirements: FlowPackageRequirementSet,
    provenance: FlowPackageProvenance,
) -> _FlowPackageDocumentHashes:
    spec_hash = draft.spec.spec_hash()
    manifest_hash = hash_json_value(manifest_metadata.canonical_hash_input())
    requirements_hash = hash_json_value(requirements.canonical_hash_input())
    provenance_hash = hash_json_value(provenance.canonical_hash_input())
    content_checksum = compose_content_checksum(
        spec_hash=spec_hash,
        manifest_hash=manifest_hash,
        requirements_hash=requirements_hash,
        provenance_hash=provenance_hash,
    )
    return _FlowPackageDocumentHashes(
        spec_hash=spec_hash,
        manifest_hash=manifest_hash,
        requirements_hash=requirements_hash,
        provenance_hash=provenance_hash,
        content_checksum=content_checksum,
    )


def _require_flow_payload(manifest: FlowPackageManifestMetadata) -> None:
    if (
        manifest.package_kind is EneoPackageKind.FLOW
        and manifest.payload_schema == FLOW_PACKAGE_PAYLOAD_SCHEMA
    ):
        return
    raise FlowPackageValidationError(
        code=FlowPackageErrorCode.PACKAGE_KIND_UNSUPPORTED,
        message="This package reader only supports flow package payloads.",
        context={
            "package_kind": manifest.package_kind.value,
            "payload_schema": manifest.payload_schema,
        },
    )
