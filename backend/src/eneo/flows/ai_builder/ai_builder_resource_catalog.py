from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict

from eneo.flows.assistant_authoring_snapshot import (
    AssistantAuthoringResourceRef,
    AssistantAuthoringSnapshot,
)
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotAllocator,
    ResourceSlotKind,
    ResourceSlotRef,
)

ResourceKind = Literal["knowledge_base", "model"]

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
RESOURCE_DESCRIPTION_MAX_CHARS = 240


class AIBuilderAvailableModelResource(TypedDict):
    id: str
    ref: str
    name: str
    display_name: str
    provider: str


class AIBuilderAvailableKnowledgeBaseResource(TypedDict):
    id: str
    ref: str
    name: str
    display_name: str
    description: str


class AssistantSnapshotResourceUnavailableError(ValueError):
    def __init__(self, *, kind: ResourceKind, local_ref: str) -> None:
        self.kind = kind
        self.local_ref = local_ref
        super().__init__(
            f"Assistant snapshot references an unavailable {kind} resource."
        )


@dataclass(frozen=True, slots=True)
class AIBuilderResourceReferenceEntry:
    ref: str
    display_name: str
    description: str = ""
    parent_ref: str | None = None

    def prompt_fields(
        self,
        *,
        ref_label: str,
        include_parent_ref: bool = False,
    ) -> str:
        fields = [f"{ref_label}=`{self.ref}`"]
        if include_parent_ref and self.parent_ref is not None:
            fields.append(f"server_ref=`{self.parent_ref}`")
        fields.append(f"name=`{self.display_name}`")
        rendered = " | ".join(fields)
        if self.description:
            rendered += f" - {self.description}"
        return rendered


@dataclass(frozen=True, slots=True)
class AIBuilderResourceReferenceMaterial:
    models: tuple[AIBuilderResourceReferenceEntry, ...]
    knowledge_bases: tuple[AIBuilderResourceReferenceEntry, ...]


@dataclass(frozen=True)
class AIBuilderResourceCatalogEntry:
    local_ref: str
    name: str
    display_name: str
    aliases: tuple[str, ...]
    kind: ResourceKind
    slot_ref: ResourceSlotRef
    local_binding: LocalResourceBinding | None
    description: str = ""
    provider: str = ""
    parent_ref: str | None = None

    @property
    def authoring_ref(self) -> str:
        return self.slot_ref.ref

    @property
    def option_label(self) -> str:
        return f"{self.display_name} [{self.authoring_ref}]"


@dataclass(frozen=True)
class AIBuilderResourceResolutionIssue:
    kind: ResourceKind
    code: str
    provided_value: str
    location: str
    valid_options: tuple[str, ...]


@dataclass(frozen=True)
class AIBuilderResourceCatalog:
    models: tuple[AIBuilderResourceCatalogEntry, ...]
    knowledge_bases: tuple[AIBuilderResourceCatalogEntry, ...]
    _model_alias_index: dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]
    _kb_alias_index: dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]
    _model_local_ref_index: dict[str, AIBuilderResourceCatalogEntry]
    _kb_local_ref_index: dict[str, AIBuilderResourceCatalogEntry]

    @property
    def model_refs(self) -> set[str]:
        return {entry.authoring_ref for entry in self.models}

    @property
    def knowledge_base_refs(self) -> set[str]:
        return {entry.authoring_ref for entry in self.knowledge_bases}

    def small_ref_enum_for_kind(
        self,
        kind: ResourceKind,
        *,
        limit: int = 15,
    ) -> list[str] | None:
        refs = {entry.authoring_ref for entry in self._entries_for_kind(kind)}
        if not refs or len(refs) > limit:
            return None
        return sorted(refs)

    def resolve(
        self,
        *,
        kind: ResourceKind,
        value: str,
        location: str,
    ) -> tuple[str | None, AIBuilderResourceResolutionIssue | None]:
        normalized = _normalize_alias(value)
        alias_index = self._alias_index_for_kind(kind)
        entries: tuple[AIBuilderResourceCatalogEntry, ...] = alias_index.get(
            normalized,
            tuple(),
        )
        if not entries:
            return None, AIBuilderResourceResolutionIssue(
                kind=kind,
                code=_issue_code(kind=kind, prefix="unknown"),
                provided_value=value,
                location=location,
                valid_options=tuple(
                    entry.option_label for entry in self._entries_for_kind(kind)
                ),
            )
        if len(entries) > 1:
            return None, AIBuilderResourceResolutionIssue(
                kind=kind,
                code=_issue_code(kind=kind, prefix="ambiguous"),
                provided_value=value,
                location=location,
                valid_options=tuple(entry.option_label for entry in entries),
            )
        resolved_entry = next(iter(entries), None)
        if resolved_entry is None:
            return None, AIBuilderResourceResolutionIssue(
                kind=kind,
                code=_issue_code(kind=kind, prefix="unknown"),
                provided_value=value,
                location=location,
                valid_options=tuple(
                    entry.option_label for entry in self._entries_for_kind(kind)
                ),
            )
        return resolved_entry.authoring_ref, None

    def entry_for_ref(
        self,
        *,
        kind: ResourceKind,
        ref: str,
    ) -> AIBuilderResourceCatalogEntry | None:
        return next(
            (
                entry
                for entry in self._entries_for_kind(kind)
                if entry.authoring_ref == ref
            ),
            None,
        )

    def entry_for_local_ref(
        self,
        *,
        kind: ResourceKind,
        local_ref: str,
    ) -> AIBuilderResourceCatalogEntry | None:
        return self._local_ref_index_for_kind(kind).get(local_ref.strip())

    def assistant_spec_from_snapshot(
        self,
        snapshot: AssistantAuthoringSnapshot,
    ) -> AssistantSpec:
        return AssistantSpec(
            instructions=snapshot.instructions,
            model_ref=(
                self._authoring_ref_for_snapshot_resource(
                    kind="model",
                    resource=snapshot.model,
                )
                if snapshot.model is not None
                else None
            ),
            knowledge_refs=self._authoring_refs_for_snapshot_resources(
                kind="knowledge_base",
                resources=snapshot.knowledge_refs,
            ),
        )

    def refs_mentioned_in_text(
        self,
        *,
        kind: ResourceKind,
        text: str,
        allowed_refs: Iterable[str] | None = None,
    ) -> frozenset[str]:
        """Return catalog refs whose aliases are explicitly present in text.

        This is a resource-name matcher, not workflow inference. It lets AI
        Builder recover from small-model omissions of canonical resource refs.
        """

        haystack = _normalize_alias(text)
        if not haystack:
            return frozenset()
        allowed = set(allowed_refs) if allowed_refs is not None else None
        mention_spans: list[tuple[int, int, AIBuilderResourceCatalogEntry]] = []
        for entry in self._entries_for_kind(kind):
            if allowed is not None and entry.authoring_ref not in allowed:
                continue
            mention_spans.extend(
                _entry_alias_mention_spans(entry=entry, normalized_text=haystack)
            )
        matched: set[str] = set()
        for _, _, entry in _without_nested_alias_prefix_mentions(mention_spans):
            matched.add(entry.authoring_ref)
        return frozenset(matched)

    def _alias_index_for_kind(
        self,
        kind: ResourceKind,
    ) -> dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]:
        if kind == "knowledge_base":
            return self._kb_alias_index
        return self._model_alias_index

    def _local_ref_index_for_kind(
        self,
        kind: ResourceKind,
    ) -> dict[str, AIBuilderResourceCatalogEntry]:
        if kind == "knowledge_base":
            return self._kb_local_ref_index
        return self._model_local_ref_index

    def _entries_for_kind(
        self,
        kind: ResourceKind,
    ) -> tuple[AIBuilderResourceCatalogEntry, ...]:
        if kind == "knowledge_base":
            return self.knowledge_bases
        return self.models

    def _authoring_ref_for_snapshot_resource(
        self,
        *,
        kind: ResourceKind,
        resource: AssistantAuthoringResourceRef,
    ) -> str:
        entry = self.entry_for_local_ref(kind=kind, local_ref=resource.local_ref)
        if entry is None:
            raise AssistantSnapshotResourceUnavailableError(
                kind=kind,
                local_ref=resource.local_ref,
            )
        return entry.authoring_ref

    def _authoring_refs_for_snapshot_resources(
        self,
        *,
        kind: ResourceKind,
        resources: tuple[AssistantAuthoringResourceRef, ...],
    ) -> list[str]:
        refs: list[str] = []
        for resource in resources:
            ref = self._authoring_ref_for_snapshot_resource(
                kind=kind,
                resource=resource,
            )
            if ref not in refs:
                refs.append(ref)
        return refs


def build_ai_builder_resource_catalog(
    *,
    available_models: Sequence[AIBuilderAvailableModelResource] | None,
    available_kbs: Sequence[AIBuilderAvailableKnowledgeBaseResource] | None,
    prior_bindings: Iterable[LocalResourceBinding] = (),
) -> AIBuilderResourceCatalog:
    allocator = ResourceSlotAllocator(prior_bindings=prior_bindings)
    models = tuple(_build_model_entries(available_models or [], allocator=allocator))
    knowledge_bases = tuple(
        _build_knowledge_base_entries(available_kbs or [], allocator=allocator)
    )
    return AIBuilderResourceCatalog(
        models=models,
        knowledge_bases=knowledge_bases,
        _model_alias_index=_build_alias_index(models),
        _kb_alias_index=_build_alias_index(knowledge_bases),
        _model_local_ref_index=_build_local_ref_index(models),
        _kb_local_ref_index=_build_local_ref_index(knowledge_bases),
    )


def build_ai_builder_resource_reference_material(
    *,
    catalog: AIBuilderResourceCatalog,
) -> AIBuilderResourceReferenceMaterial:
    return AIBuilderResourceReferenceMaterial(
        models=tuple(_resource_reference_entry(entry) for entry in catalog.models),
        knowledge_bases=tuple(
            _resource_reference_entry(entry) for entry in catalog.knowledge_bases
        ),
    )


@dataclass(frozen=True, slots=True)
class RenderedResourceReferences:
    models: str
    knowledge_bases: str


def render_resource_reference_block(
    material: AIBuilderResourceReferenceMaterial,
) -> RenderedResourceReferences:
    """Render prompt-visible resource reference bullet lines from typed material.

    Phases share the per-kind bullet formatting and add their own headings/copy.
    """
    return RenderedResourceReferences(
        models="\n".join(
            f"- {entry.prompt_fields(ref_label='ref')}" for entry in material.models
        ),
        knowledge_bases="\n".join(
            f"- {entry.prompt_fields(ref_label='ref')}"
            for entry in material.knowledge_bases
        ),
    )


def canonicalize_flow_spec_resources(
    spec: FlowDraftSpecCore,
    *,
    catalog: AIBuilderResourceCatalog,
) -> tuple[FlowDraftSpecCore, list[AIBuilderResourceResolutionIssue]]:
    issues: list[AIBuilderResourceResolutionIssue] = []
    updated_steps: list[StepSpec] = []
    changed = False
    for step in spec.steps:
        assistant_spec, assistant_issues = canonicalize_assistant_spec_resources(
            step.assistant_spec,
            catalog=catalog,
            location_prefix=f"step '{step.plan_step_ref}'",
        )
        issues.extend(assistant_issues)
        if assistant_spec != step.assistant_spec:
            changed = True
            updated_steps.append(
                step.model_copy(update={"assistant_spec": assistant_spec})
            )
        else:
            updated_steps.append(step)
    if not changed:
        return spec, issues
    return spec.model_copy(update={"steps": updated_steps}), issues


def collect_flow_spec_resource_bindings(
    spec: FlowDraftSpecCore,
    *,
    catalog: AIBuilderResourceCatalog,
) -> tuple[LocalResourceBinding, ...]:
    bindings_by_slot: dict[tuple[ResourceSlotKind, str], LocalResourceBinding] = {}
    for step in spec.steps:
        assistant_spec = step.assistant_spec
        if assistant_spec.model_ref is not None:
            _collect_binding_for_ref(
                bindings_by_slot=bindings_by_slot,
                catalog=catalog,
                kind="model",
                ref=assistant_spec.model_ref,
            )
        for ref in assistant_spec.knowledge_refs:
            _collect_binding_for_ref(
                bindings_by_slot=bindings_by_slot,
                catalog=catalog,
                kind="knowledge_base",
                ref=ref,
            )
    return tuple(bindings_by_slot.values())


def canonicalize_assistant_spec_resources(
    assistant_spec: AssistantSpec,
    *,
    catalog: AIBuilderResourceCatalog,
    location_prefix: str,
) -> tuple[AssistantSpec, list[AIBuilderResourceResolutionIssue]]:
    issues: list[AIBuilderResourceResolutionIssue] = []
    updated_model_ref = assistant_spec.model_ref
    if assistant_spec.model_ref is not None:
        updated_model_ref, issue = catalog.resolve(
            kind="model",
            value=assistant_spec.model_ref,
            location=f"{location_prefix}.assistant_spec.model_ref",
        )
        if issue is not None:
            issues.append(issue)

    updated_knowledge_refs: list[str] = []
    for index, reference in enumerate(assistant_spec.knowledge_refs):
        resolved, issue = catalog.resolve(
            kind="knowledge_base",
            value=reference,
            location=f"{location_prefix}.assistant_spec.knowledge_refs[{index}]",
        )
        if issue is not None:
            issues.append(issue)
            continue
        if resolved is not None and resolved not in updated_knowledge_refs:
            updated_knowledge_refs.append(resolved)

    if (
        updated_model_ref == assistant_spec.model_ref
        and updated_knowledge_refs == assistant_spec.knowledge_refs
    ):
        return assistant_spec, issues

    return (
        assistant_spec.model_copy(
            update={
                "model_ref": updated_model_ref,
                "knowledge_refs": updated_knowledge_refs,
            }
        ),
        issues,
    )


def _collect_binding_for_ref(
    *,
    bindings_by_slot: dict[tuple[ResourceSlotKind, str], LocalResourceBinding],
    catalog: AIBuilderResourceCatalog,
    kind: ResourceKind,
    ref: str,
) -> None:
    entry = catalog.entry_for_ref(kind=kind, ref=ref)
    if entry is None or entry.local_binding is None:
        return
    slot_ref = entry.local_binding.slot_ref
    bindings_by_slot.setdefault((slot_ref.kind, slot_ref.slot), entry.local_binding)


def _build_local_ref_index(
    entries: Iterable[AIBuilderResourceCatalogEntry],
) -> dict[str, AIBuilderResourceCatalogEntry]:
    return {entry.local_ref: entry for entry in entries}


def format_resource_resolution_feedback(
    issues: list[AIBuilderResourceResolutionIssue],
) -> str:
    lines: list[str] = []
    for issue in issues:
        resource_label = _resource_label(issue.kind)
        if issue.code.startswith("ambiguous_"):
            lines.append(
                f"Ambiguous {resource_label} reference '{issue.provided_value}' at {issue.location}. "
                f"Use the canonical ref. Matching options: {', '.join(issue.valid_options)}."
            )
        else:
            lines.append(
                f"Unknown {resource_label} reference '{issue.provided_value}' at {issue.location}. "
                f"Use one of the canonical refs: {', '.join(issue.valid_options)}."
            )
    return "\n".join(lines)


def _resource_label(kind: ResourceKind) -> str:
    if kind == "knowledge_base":
        return "knowledge base"
    return "model"


def _issue_code(*, kind: ResourceKind, prefix: Literal["ambiguous", "unknown"]) -> str:
    suffix = {
        "knowledge_base": "kb",
        "model": "model",
    }[kind]
    return f"{prefix}_{suffix}_ref"


def _build_model_entries(
    items: Sequence[AIBuilderAvailableModelResource],
    *,
    allocator: ResourceSlotAllocator,
) -> list[AIBuilderResourceCatalogEntry]:
    entries: list[AIBuilderResourceCatalogEntry] = []
    for item in items:
        ref = item["ref"].strip()
        if not ref:
            continue
        raw_name = item["name"].strip()
        display_name = item["display_name"].strip() or raw_name or ref
        name = raw_name or display_name
        slot_ref, local_binding = allocator.allocate(
            slot_kind=_slot_kind_for_resource_kind("model"),
            local_kind=_local_kind_for_resource_kind("model"),
            local_ref=ref,
            display_name=display_name,
        )
        aliases = tuple(
            dict.fromkeys(
                filter(
                    None,
                    [
                        _normalize_alias(slot_ref.ref),
                        _normalize_alias(display_name),
                    ],
                )
            )
        )
        entries.append(
            AIBuilderResourceCatalogEntry(
                local_ref=ref,
                name=name,
                display_name=display_name,
                aliases=aliases,
                kind="model",
                slot_ref=slot_ref,
                local_binding=local_binding,
                provider=item["provider"].strip(),
            )
        )
    return entries


def _build_knowledge_base_entries(
    items: Sequence[AIBuilderAvailableKnowledgeBaseResource],
    *,
    allocator: ResourceSlotAllocator,
) -> list[AIBuilderResourceCatalogEntry]:
    entries: list[AIBuilderResourceCatalogEntry] = []
    for item in items:
        ref = item["ref"].strip()
        if not ref:
            continue
        raw_name = item["name"].strip()
        display_name = item["display_name"].strip() or raw_name or ref
        name = raw_name or display_name
        slot_ref, local_binding = allocator.allocate(
            slot_kind=_slot_kind_for_resource_kind("knowledge_base"),
            local_kind=_local_kind_for_resource_kind("knowledge_base"),
            local_ref=ref,
            display_name=display_name,
        )
        aliases = tuple(
            dict.fromkeys(
                filter(
                    None,
                    [
                        _normalize_alias(slot_ref.ref),
                        _normalize_alias(display_name),
                    ],
                )
            )
        )
        entries.append(
            AIBuilderResourceCatalogEntry(
                local_ref=ref,
                name=name,
                display_name=display_name,
                aliases=aliases,
                kind="knowledge_base",
                slot_ref=slot_ref,
                local_binding=local_binding,
                description=item["description"].strip(),
            )
        )
    return entries


def _resource_reference_entry(
    entry: AIBuilderResourceCatalogEntry,
) -> AIBuilderResourceReferenceEntry:
    return AIBuilderResourceReferenceEntry(
        ref=entry.authoring_ref,
        display_name=entry.display_name,
        description=_bounded_description(entry.description),
        parent_ref=entry.parent_ref,
    )


def _bounded_description(description: str) -> str:
    if len(description) <= RESOURCE_DESCRIPTION_MAX_CHARS:
        return description
    return description[: RESOURCE_DESCRIPTION_MAX_CHARS - 3].rstrip() + "..."


def _build_alias_index(
    entries: tuple[AIBuilderResourceCatalogEntry, ...],
) -> dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]:
    alias_index: dict[str, list[AIBuilderResourceCatalogEntry]] = {}
    for entry in entries:
        for alias in entry.aliases:
            alias_index.setdefault(alias, []).append(entry)
    return {alias: tuple(values) for alias, values in alias_index.items()}


def _slot_kind_for_resource_kind(kind: ResourceKind) -> ResourceSlotKind:
    if kind == "knowledge_base":
        return ResourceSlotKind.KNOWLEDGE
    return ResourceSlotKind.MODEL


def _local_kind_for_resource_kind(kind: ResourceKind) -> LocalResourceKind:
    if kind == "knowledge_base":
        return LocalResourceKind.COLLECTION
    return LocalResourceKind.COMPLETION_MODEL


def _normalize_alias(value: str) -> str:
    stripped = value.strip().casefold()
    collapsed = _NON_ALNUM_RE.sub("-", stripped).strip("-")
    return collapsed or stripped


def _entry_alias_mention_spans(
    *,
    entry: AIBuilderResourceCatalogEntry,
    normalized_text: str,
) -> list[tuple[int, int, AIBuilderResourceCatalogEntry]]:
    bounded_text = f"-{normalized_text}-"
    spans: list[tuple[int, int, AIBuilderResourceCatalogEntry]] = []
    for alias in entry.aliases:
        if not alias:
            continue
        needle = f"-{alias}-"
        start = 0
        while True:
            index = bounded_text.find(needle, start)
            if index < 0:
                break
            spans.append((index, index + len(needle), entry))
            start = index + 1
    return spans


def _without_nested_alias_prefix_mentions(
    mentions: list[tuple[int, int, AIBuilderResourceCatalogEntry]],
) -> list[tuple[int, int, AIBuilderResourceCatalogEntry]]:
    return [
        mention
        for mention in mentions
        if not _has_longer_covering_alias_mention(mention, mentions)
    ]


def _has_longer_covering_alias_mention(
    mention: tuple[int, int, AIBuilderResourceCatalogEntry],
    mentions: list[tuple[int, int, AIBuilderResourceCatalogEntry]],
) -> bool:
    start, end, entry = mention
    length = end - start
    return any(
        other_entry.authoring_ref != entry.authoring_ref
        and other_start <= start
        and end <= other_end
        and other_end - other_start > length
        for other_start, other_end, other_entry in mentions
    )
