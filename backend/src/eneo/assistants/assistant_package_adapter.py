from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from eneo.resource_packages.manifest import (
    ASSISTANT_PACKAGE_PAYLOAD_SCHEMA,
    EneoPackageKind,
    ResourcePackageManifestMetadata,
)

if TYPE_CHECKING:
    from eneo.assistants.assistant import Assistant


class AssistantPackageKnowledgeKind(StrEnum):
    COLLECTION = "collection"
    WEBSITE = "website"
    INTEGRATION_KNOWLEDGE = "integration_knowledge"


class AssistantPackageModelReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str
    provider_type: str | None = None
    litellm_model_name: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Assistant package model name must not be empty.")
        return normalized

    @field_validator("provider_type", "litellm_model_name")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class AssistantPackageKnowledgeReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    slot_ref: str
    kind: AssistantPackageKnowledgeKind
    name: str

    @field_validator("slot_ref", "name")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Assistant package knowledge text must not be empty.")
        return normalized


class AssistantPackagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    name: str
    description: str = ""
    prompt: str
    model: AssistantPackageModelReference
    knowledge: tuple[AssistantPackageKnowledgeReference, ...] = ()

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Assistant package name must not be empty.")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str) -> str:
        return value.strip()


class AssistantPackageImportBindings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    completion_model_id: UUID
    knowledge_by_slot: dict[str, UUID] = Field(default_factory=dict)


class AssistantPackageInstallSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    name: str
    description: str
    prompt: str
    completion_model_id: UUID
    collection_ids: tuple[UUID, ...] = ()
    website_ids: tuple[UUID, ...] = ()
    integration_knowledge_ids: tuple[UUID, ...] = ()


class AssistantPackageBindingError(ValueError):
    def __init__(self, *, missing: set[str], unexpected: set[str]) -> None:
        self.missing = frozenset(missing)
        self.unexpected = frozenset(unexpected)
        super().__init__("Assistant package knowledge bindings do not match payload.")


class AssistantPackageAdapter:
    """Portable prompt/model/knowledge adapter for real Assistant resources."""

    kind = EneoPackageKind.ASSISTANT
    payload_schema = ASSISTANT_PACKAGE_PAYLOAD_SCHEMA

    def manifest_metadata(
        self,
        *,
        package_id: str,
        package_version: str,
        assistant: Assistant,
    ) -> ResourcePackageManifestMetadata:
        return ResourcePackageManifestMetadata(
            schema_version=1,
            package_id=package_id,
            package_version=package_version,
            name=assistant.name,
            description=assistant.description or "",
            kind=self.kind,
            payload_schema=self.payload_schema,
        )

    def export_payload(self, assistant: Assistant) -> AssistantPackagePayload:
        if assistant.prompt is None:
            raise ValueError("Assistant package export requires a prompt.")
        if assistant.completion_model is None:
            raise ValueError("Assistant package export requires a completion model.")

        knowledge: list[tuple[AssistantPackageKnowledgeKind, str, str]] = []
        for kind, resources in (
            (AssistantPackageKnowledgeKind.COLLECTION, assistant.collections),
            (AssistantPackageKnowledgeKind.WEBSITE, assistant.websites),
            (
                AssistantPackageKnowledgeKind.INTEGRATION_KNOWLEDGE,
                assistant.integration_knowledge_list,
            ),
        ):
            for resource in resources:
                knowledge.append((kind, resource.name or "", str(resource.id or "")))
        knowledge.sort(key=lambda item: (item[0].value, item[1].casefold(), item[2]))

        counters: dict[AssistantPackageKnowledgeKind, int] = {}
        references: list[AssistantPackageKnowledgeReference] = []
        for kind, name, _ in knowledge:
            counters[kind] = counters.get(kind, 0) + 1
            references.append(
                AssistantPackageKnowledgeReference(
                    slot_ref=f"{kind.value}:{counters[kind]:04d}",
                    kind=kind,
                    name=name,
                )
            )

        model = assistant.completion_model
        return AssistantPackagePayload(
            name=assistant.name,
            description=assistant.description or "",
            prompt=assistant.prompt.text,
            model=AssistantPackageModelReference(
                name=model.name,
                provider_type=model.provider_type,
                litellm_model_name=model.litellm_model_name,
            ),
            knowledge=tuple(references),
        )

    def prepare_import(
        self,
        payload: AssistantPackagePayload,
        bindings: AssistantPackageImportBindings,
    ) -> AssistantPackageInstallSpec:
        required_slots = {item.slot_ref for item in payload.knowledge}
        selected_slots = set(bindings.knowledge_by_slot)
        if required_slots != selected_slots:
            raise AssistantPackageBindingError(
                missing=required_slots - selected_slots,
                unexpected=selected_slots - required_slots,
            )

        ids_by_kind: dict[AssistantPackageKnowledgeKind, list[UUID]] = {
            kind: [] for kind in AssistantPackageKnowledgeKind
        }
        for reference in payload.knowledge:
            ids_by_kind[reference.kind].append(
                bindings.knowledge_by_slot[reference.slot_ref]
            )

        return AssistantPackageInstallSpec(
            name=payload.name,
            description=payload.description,
            prompt=payload.prompt,
            completion_model_id=bindings.completion_model_id,
            collection_ids=tuple(ids_by_kind[AssistantPackageKnowledgeKind.COLLECTION]),
            website_ids=tuple(ids_by_kind[AssistantPackageKnowledgeKind.WEBSITE]),
            integration_knowledge_ids=tuple(
                ids_by_kind[AssistantPackageKnowledgeKind.INTEGRATION_KNOWLEDGE]
            ),
        )
