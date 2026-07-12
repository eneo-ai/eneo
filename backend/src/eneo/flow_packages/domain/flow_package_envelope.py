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
    FlowPackageKnowledgeRequirement,
    FlowPackageModelKind,
    FlowPackageModelRequirement,
    FlowPackageRequirementSet,
)
from eneo.flows.flow_authoring_spec import AssistantSpec, FlowDraftSpecCore, OutputMode
from eneo.flows.flow_resource_bindings import ResourceSlotRef
from eneo.flows.flow_validators_template import has_template_fill_resource_reference

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

    def validated_resource_contract(
        self,
    ) -> "ValidatedFlowPackageResourceContract":
        declared_requirements = {
            requirement.slot_ref.ref: requirement
            for requirement in self.requirements.requirements
        }
        declared_slot_refs = {
            ref: requirement.slot_ref
            for ref, requirement in declared_requirements.items()
        }
        referenced_slot_refs = frozenset(
            ref
            for step in self.spec.steps
            for ref in _assistant_slot_refs(step.assistant_spec)
        )
        unknown_slot_refs = referenced_slot_refs.difference(declared_slot_refs)
        if unknown_slot_refs:
            first_unknown = min(unknown_slot_refs)
            raise FlowPackageValidationError(
                code=(FlowPackageErrorCode.IMPORT_DRAFT_REFERENCES_UNDECLARED_SLOT),
                message=(
                    "Flow package draft references a resource slot that is not "
                    "declared."
                ),
                context={
                    "slot_ref": first_unknown,
                    "unknown_count": len(unknown_slot_refs),
                },
            )
        for step in self.spec.steps:
            model_ref = step.assistant_spec.model_ref
            if model_ref is not None:
                requirement = declared_requirements[model_ref]
                if not isinstance(requirement, FlowPackageModelRequirement):
                    raise _invalid_requirement_use(
                        slot_ref=model_ref,
                        reason="assistant_model_ref_kind_mismatch",
                    )
                if requirement.model_kind is not FlowPackageModelKind.COMPLETION_MODEL:
                    raise _invalid_requirement_use(
                        slot_ref=model_ref,
                        reason="assistant_model_requires_completion_model",
                    )
                if not requirement.required:
                    raise _invalid_requirement_use(
                        slot_ref=model_ref,
                        reason="referenced_model_must_be_required",
                    )
            for knowledge_ref in step.assistant_spec.knowledge_refs:
                if not isinstance(
                    declared_requirements[knowledge_ref],
                    FlowPackageKnowledgeRequirement,
                ):
                    raise _invalid_requirement_use(
                        slot_ref=knowledge_ref,
                        reason="assistant_knowledge_ref_kind_mismatch",
                    )
        return ValidatedFlowPackageResourceContract(
            declared_slot_refs=declared_slot_refs,
            referenced_slot_refs=referenced_slot_refs,
        )

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
        envelope = cls(
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
        _validate_portable_step_identity(envelope.spec)
        _reject_unsupported_template_use(envelope.spec)
        envelope.validated_resource_contract()
        return envelope


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


@dataclass(frozen=True, slots=True)
class ValidatedFlowPackageResourceContract:
    declared_slot_refs: dict[str, ResourceSlotRef]
    referenced_slot_refs: frozenset[str]


def _assistant_slot_refs(assistant: AssistantSpec) -> tuple[str, ...]:
    refs: list[str] = []
    if assistant.model_ref is not None:
        refs.append(assistant.model_ref)
    refs.extend(assistant.knowledge_refs)
    return tuple(refs)


def _invalid_requirement_use(
    *,
    slot_ref: str,
    reason: str,
) -> FlowPackageValidationError:
    return FlowPackageValidationError(
        code=FlowPackageErrorCode.REQUIREMENTS_INVALID,
        message="Flow package resource requirements do not match draft usage.",
        context={"slot_ref": slot_ref, "reason": reason},
    )


def _reject_unsupported_template_use(spec: FlowDraftSpecCore) -> None:
    for step in spec.steps:
        if (
            step.output_mode is OutputMode.TEMPLATE_FILL
            or has_template_fill_resource_reference(step.output_config)
        ):
            raise FlowPackageValidationError(
                code=FlowPackageErrorCode.IMPORT_TEMPLATE_ASSETS_UNSUPPORTED,
                message=(
                    "Flow package import does not support template asset "
                    "installation yet."
                ),
                context={"plan_step_ref": step.plan_step_ref},
            )


def _validate_portable_step_identity(spec: FlowDraftSpecCore) -> None:
    seen_refs: set[str] = set()
    for step in spec.steps:
        if not step.plan_step_ref or step.plan_step_ref != step.plan_step_ref.strip():
            raise _invalid_portable_step_ref(
                plan_step_ref=step.plan_step_ref,
                reason="invalid_plan_step_ref",
            )
        if step.plan_step_ref in seen_refs:
            raise _invalid_portable_step_ref(
                plan_step_ref=step.plan_step_ref,
                reason="duplicate_plan_step_ref",
            )
        seen_refs.add(step.plan_step_ref)
        if step.existing_step_ref is not None:
            raise _invalid_portable_step_ref(
                plan_step_ref=step.plan_step_ref,
                reason="existing_step_ref_not_portable",
            )


def _invalid_portable_step_ref(
    *,
    plan_step_ref: str,
    reason: str,
) -> FlowPackageValidationError:
    return FlowPackageValidationError(
        code=FlowPackageErrorCode.FLOW_DRAFT_INVALID,
        message="Flow package step identity is not portable.",
        context={"plan_step_ref": plan_step_ref, "reason": reason},
    )
