from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Literal, TypeAlias
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    computed_field,
    field_validator,
    model_validator,
)

RESOURCE_SLOT_PATTERN = r"^[a-z][a-z0-9]*(-[a-z0-9]+)*$"
UUID_SHAPED_RESOURCE_REF_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)

_NON_SLOT_CHAR_RE = re.compile(r"[^a-z0-9]+")
_SLOT_RE = re.compile(RESOURCE_SLOT_PATTERN)
_UUID_SHAPED_RE = re.compile(UUID_SHAPED_RESOURCE_REF_PATTERN, re.IGNORECASE)


class ResourceSlotKind(str, Enum):
    MODEL = "model"
    KNOWLEDGE = "knowledge"
    MCP_SERVER = "mcp_server"
    MCP_TOOL = "mcp_tool"
    TEMPLATE_ASSET = "template_asset"


class LocalResourceKind(str, Enum):
    COMPLETION_MODEL = "completion_model"
    TRANSCRIPTION_MODEL = "transcription_model"
    COLLECTION = "collection"
    WEBSITE = "website"
    INTEGRATION_KNOWLEDGE = "integration_knowledge"
    MCP_SERVER = "mcp_server"
    MCP_TOOL = "mcp_tool"
    TEMPLATE_ASSET = "template_asset"


class FlowResourceBindingSource(str, Enum):
    AI_BUILDER = "ai_builder"
    PACKAGE_IMPORT = "package_import"
    MANUAL_ADMIN = "manual_admin"


class FlowResourceBindingResolutionReason(str, Enum):
    DUPLICATE_SLOT_BINDING = "duplicate_slot_binding"
    INVALID_SLOT_REF = "invalid_slot_ref"
    WRONG_SLOT_KIND = "wrong_slot_kind"
    UNRESOLVED_SLOT_BINDING = "unresolved_slot_binding"
    DISALLOWED_LOCAL_KIND = "disallowed_local_kind"


class FlowResourceBindingResolutionError(ValueError):
    def __init__(
        self,
        *,
        reason: FlowResourceBindingResolutionReason,
        resource_ref: str,
        expected_slot_kind: ResourceSlotKind,
        actual_slot_kind: ResourceSlotKind | None = None,
        local_kind: LocalResourceKind | None = None,
    ) -> None:
        self.reason = reason
        self.resource_ref = resource_ref
        self.expected_slot_kind = expected_slot_kind
        self.actual_slot_kind = actual_slot_kind
        self.local_kind = local_kind
        super().__init__(self._message())

    def _message(self) -> str:
        if self.reason is FlowResourceBindingResolutionReason.DUPLICATE_SLOT_BINDING:
            return f"Duplicate resource binding for slot '{self.resource_ref}'."
        if self.reason is FlowResourceBindingResolutionReason.INVALID_SLOT_REF:
            return f"Invalid resource slot ref '{self.resource_ref}'."
        if self.reason is FlowResourceBindingResolutionReason.WRONG_SLOT_KIND:
            return (
                f"Resource slot ref '{self.resource_ref}' does not match expected "
                f"{self.expected_slot_kind.value} slot."
            )
        if self.reason is FlowResourceBindingResolutionReason.DISALLOWED_LOCAL_KIND:
            return (
                f"Resource binding for slot '{self.resource_ref}' uses unsupported "
                f"local resource kind '{self.local_kind.value if self.local_kind else ''}'."
            )
        return f"Resource slot ref '{self.resource_ref}' has no local binding."

    def context(self) -> dict[str, str]:
        context: dict[str, str] = {
            "reason": self.reason.value,
            "slot_ref": self.resource_ref,
            "expected_kind": self.expected_slot_kind.value,
        }
        if self.actual_slot_kind is not None:
            context["actual_kind"] = self.actual_slot_kind.value
        if self.local_kind is not None:
            context["local_kind"] = self.local_kind.value
        return context


_LOCAL_KINDS_BY_SLOT_KIND: dict[ResourceSlotKind, frozenset[LocalResourceKind]] = {
    ResourceSlotKind.MODEL: frozenset(
        {
            LocalResourceKind.COMPLETION_MODEL,
            LocalResourceKind.TRANSCRIPTION_MODEL,
        }
    ),
    ResourceSlotKind.KNOWLEDGE: frozenset(
        {
            LocalResourceKind.COLLECTION,
            LocalResourceKind.WEBSITE,
            LocalResourceKind.INTEGRATION_KNOWLEDGE,
        }
    ),
    ResourceSlotKind.MCP_SERVER: frozenset({LocalResourceKind.MCP_SERVER}),
    ResourceSlotKind.MCP_TOOL: frozenset({LocalResourceKind.MCP_TOOL}),
    ResourceSlotKind.TEMPLATE_ASSET: frozenset({LocalResourceKind.TEMPLATE_ASSET}),
}
RESOURCE_SLOT_LOCAL_KIND_PAIRS = tuple(
    (slot_kind.value, local_kind.value)
    for slot_kind, local_kinds in _LOCAL_KINDS_BY_SLOT_KIND.items()
    for local_kind in sorted(local_kinds, key=lambda item: item.value)
)
FLOW_RESOURCE_BINDING_SOURCE_VALUES = tuple(
    source.value for source in FlowResourceBindingSource
)
KnowledgeAssistantUpdateField: TypeAlias = Literal[
    "groups",
    "websites",
    "integration_knowledge_ids",
]
_KNOWLEDGE_ASSISTANT_UPDATE_FIELD_BY_LOCAL_KIND: dict[
    LocalResourceKind,
    KnowledgeAssistantUpdateField,
] = {
    LocalResourceKind.COLLECTION: "groups",
    LocalResourceKind.WEBSITE: "websites",
    LocalResourceKind.INTEGRATION_KNOWLEDGE: "integration_knowledge_ids",
}


class ResourceSlotRef(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: ResourceSlotKind
    slot: str
    label: str

    @computed_field
    @property
    def ref(self) -> str:
        return f"{self.kind.value}.{self.slot}"

    @field_validator("slot")
    @classmethod
    def validate_slot(cls, value: str) -> str:
        if not _SLOT_RE.fullmatch(value):
            raise ValueError(
                "Resource slot must be lowercase kebab-case starting with a letter."
            )
        if is_uuid_shaped_resource_ref(value):
            raise ValueError("Resource slot must not be a UUID-shaped local ref.")
        return value

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Resource slot label must not be empty.")
        return normalized


class LocalResourceBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    slot_ref: ResourceSlotRef
    local_kind: LocalResourceKind
    local_id: UUID

    @model_validator(mode="after")
    def validate_local_kind_matches_slot(self) -> "LocalResourceBinding":
        allowed = _LOCAL_KINDS_BY_SLOT_KIND[self.slot_ref.kind]
        if self.local_kind not in allowed:
            raise ValueError(
                f"{self.local_kind.value} cannot satisfy {self.slot_ref.kind.value} slot."
            )
        return self


def is_uuid_shaped_resource_ref(value: str) -> bool:
    return bool(_UUID_SHAPED_RE.fullmatch(value.strip()))


def index_local_resource_bindings(
    bindings: Iterable[LocalResourceBinding],
) -> dict[str, LocalResourceBinding]:
    bindings_by_ref: dict[str, LocalResourceBinding] = {}
    for binding in bindings:
        slot_ref = binding.slot_ref.ref
        if slot_ref in bindings_by_ref:
            raise FlowResourceBindingResolutionError(
                reason=FlowResourceBindingResolutionReason.DUPLICATE_SLOT_BINDING,
                resource_ref=slot_ref,
                expected_slot_kind=binding.slot_ref.kind,
                actual_slot_kind=binding.slot_ref.kind,
                local_kind=binding.local_kind,
            )
        bindings_by_ref[slot_ref] = binding
    return bindings_by_ref


def local_resource_kinds_for_slot_kind(
    slot_kind: ResourceSlotKind,
) -> frozenset[LocalResourceKind]:
    return _LOCAL_KINDS_BY_SLOT_KIND[slot_kind]


def assistant_update_field_for_knowledge_local_kind(
    local_kind: LocalResourceKind,
) -> KnowledgeAssistantUpdateField:
    try:
        return _KNOWLEDGE_ASSISTANT_UPDATE_FIELD_BY_LOCAL_KIND[local_kind]
    except KeyError as exc:
        raise ValueError(
            f"{local_kind.value} cannot be applied as assistant knowledge."
        ) from exc


class ResourceSlotAllocator:
    """Allocates stable authoring slots for visible local resources.

    A single prior slot for a local resource keeps its slot stable across
    catalog rebuilds. Multiple prior slots for the same local resource are
    treated as ambiguous package history, so allocation falls back to the
    visible resource label unless one prior slot exactly matches that label.
    """

    def __init__(
        self,
        *,
        prior_bindings: Iterable[LocalResourceBinding] = (),
    ) -> None:
        self._used_slots_by_kind: dict[ResourceSlotKind, set[str]] = {
            slot_kind: set() for slot_kind in ResourceSlotKind
        }
        self._prior_slots_by_target: dict[
            tuple[LocalResourceKind, UUID], list[ResourceSlotRef]
        ] = {}
        self._current_slots_by_target: dict[
            tuple[LocalResourceKind, UUID], ResourceSlotRef
        ] = {}
        binding_tuple = tuple(prior_bindings)
        index_local_resource_bindings(binding_tuple)
        for binding in binding_tuple:
            # Reserve stale ambiguous slots too; reusing a prior slot name for
            # a different collapsed role would make package diffs misleading.
            self._used_slots_by_kind[binding.slot_ref.kind].add(binding.slot_ref.slot)
            target_key = (binding.local_kind, binding.local_id)
            self._prior_slots_by_target.setdefault(target_key, []).append(
                binding.slot_ref
            )

    def allocate(
        self,
        *,
        slot_kind: ResourceSlotKind,
        local_kind: LocalResourceKind,
        local_ref: str,
        display_name: str,
    ) -> tuple[ResourceSlotRef, LocalResourceBinding | None]:
        local_id = _parse_uuid(local_ref)
        prior_slot_ref = None
        if local_id is not None:
            target_key = (local_kind, local_id)
            current_slot_ref = self._current_slots_by_target.get(target_key)
            if current_slot_ref is not None:
                return (
                    current_slot_ref,
                    LocalResourceBinding(
                        slot_ref=current_slot_ref,
                        local_kind=local_kind,
                        local_id=local_id,
                    ),
                )
            prior_slot_ref = self._prior_slot_for_target(
                target_key=target_key,
                slot_kind=slot_kind,
                display_name=display_name,
            )
        label = display_name.strip()
        if prior_slot_ref is not None:
            if prior_slot_ref.kind is not slot_kind:
                raise FlowResourceBindingResolutionError(
                    reason=FlowResourceBindingResolutionReason.WRONG_SLOT_KIND,
                    resource_ref=prior_slot_ref.ref,
                    expected_slot_kind=slot_kind,
                    actual_slot_kind=prior_slot_ref.kind,
                    local_kind=local_kind,
                )
            slot_ref = ResourceSlotRef(
                kind=slot_kind,
                slot=prior_slot_ref.slot,
                label=label or prior_slot_ref.label,
            )
        else:
            label = label or f"{slot_kind.value} {local_ref.strip()[:8]}"
            slot_ref = ResourceSlotRef(
                kind=slot_kind,
                slot=unique_resource_slot(
                    label,
                    used_slots=self._used_slots_by_kind[slot_kind],
                ),
                label=label,
            )

        if local_id is None:
            return slot_ref, None
        self._current_slots_by_target[(local_kind, local_id)] = slot_ref
        return (
            slot_ref,
            LocalResourceBinding(
                slot_ref=slot_ref,
                local_kind=local_kind,
                local_id=local_id,
            ),
        )

    def _prior_slot_for_target(
        self,
        *,
        target_key: tuple[LocalResourceKind, UUID],
        slot_kind: ResourceSlotKind,
        display_name: str,
    ) -> ResourceSlotRef | None:
        prior_slots = self._prior_slots_by_target.get(target_key)
        if prior_slots is None:
            return None
        if len(prior_slots) == 1:
            return prior_slots[0]

        normalized_slot = _normalize_resource_slot(display_name)
        matches = [
            slot_ref
            for slot_ref in prior_slots
            if slot_ref.kind is slot_kind and slot_ref.slot == normalized_slot
        ]
        if len(matches) == 1:
            return matches[0]
        return None


def resolve_local_resource_ref(
    resource_ref: str,
    *,
    expected_slot_kind: ResourceSlotKind,
    bindings_by_slot_ref: Mapping[str, LocalResourceBinding],
    allowed_local_kinds: frozenset[LocalResourceKind],
) -> UUID:
    invalid_allowed_kinds = (
        allowed_local_kinds - _LOCAL_KINDS_BY_SLOT_KIND[expected_slot_kind]
    )
    if invalid_allowed_kinds:
        invalid_values = ", ".join(
            sorted(local_kind.value for local_kind in invalid_allowed_kinds)
        )
        raise ValueError(
            f"{expected_slot_kind.value} slot resolver received incompatible "
            f"allowed local resource kinds: {invalid_values}."
        )

    normalized_ref = resource_ref.strip()
    actual_slot_kind = _parse_resource_slot_kind(normalized_ref)
    if actual_slot_kind is None:
        raise FlowResourceBindingResolutionError(
            reason=FlowResourceBindingResolutionReason.INVALID_SLOT_REF,
            resource_ref=normalized_ref,
            expected_slot_kind=expected_slot_kind,
        )
    if actual_slot_kind is not expected_slot_kind:
        raise FlowResourceBindingResolutionError(
            reason=FlowResourceBindingResolutionReason.WRONG_SLOT_KIND,
            resource_ref=normalized_ref,
            expected_slot_kind=expected_slot_kind,
            actual_slot_kind=actual_slot_kind,
        )

    binding = bindings_by_slot_ref.get(normalized_ref)
    if binding is None:
        raise FlowResourceBindingResolutionError(
            reason=FlowResourceBindingResolutionReason.UNRESOLVED_SLOT_BINDING,
            resource_ref=normalized_ref,
            expected_slot_kind=expected_slot_kind,
            actual_slot_kind=actual_slot_kind,
        )
    if binding.local_kind not in allowed_local_kinds:
        raise FlowResourceBindingResolutionError(
            reason=FlowResourceBindingResolutionReason.DISALLOWED_LOCAL_KIND,
            resource_ref=normalized_ref,
            expected_slot_kind=expected_slot_kind,
            actual_slot_kind=actual_slot_kind,
            local_kind=binding.local_kind,
        )
    return binding.local_id


def unique_resource_slot(
    label: str,
    *,
    used_slots: set[str] | None = None,
) -> str:
    base = _normalize_resource_slot(label)
    if used_slots is None:
        return base

    candidate = base
    suffix = 2
    # Catalog resource counts are small; preserving deterministic suffixes is
    # more important than replacing this bounded collision loop with extra state.
    while candidate in used_slots:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_slots.add(candidate)
    return candidate


def _parse_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _normalize_resource_slot(label: str) -> str:
    normalized = _NON_SLOT_CHAR_RE.sub("-", label.strip().casefold()).strip("-")
    if not normalized:
        normalized = "resource"
    if normalized[0].isdigit():
        normalized = f"resource-{normalized}"
    return normalized


def _parse_resource_slot_kind(value: str) -> ResourceSlotKind | None:
    raw_kind, separator, raw_slot = value.partition(".")
    if not separator:
        return None
    try:
        slot_kind = ResourceSlotKind(raw_kind)
    except ValueError:
        return None
    if not _SLOT_RE.fullmatch(raw_slot):
        return None
    if is_uuid_shaped_resource_ref(raw_slot):
        return None
    return slot_kind
