from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_edit_models import (
    FlowEditDraft,
    StepEditOperation,
)
from intric.flows.ai_builder.ai_builder_mcp_resources import (
    AIBuilderMCPServerResource,
    normalize_ai_builder_mcp_resources,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft

ResourceKind = Literal["knowledge_base", "mcp_server", "mcp_tool", "model"]

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
RESOURCE_DESCRIPTION_MAX_CHARS = 240


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
    mcp_servers: tuple[AIBuilderResourceReferenceEntry, ...]
    mcp_tools: tuple[AIBuilderResourceReferenceEntry, ...]
    selected_mcp_servers: tuple[AIBuilderResourceReferenceEntry, ...]
    selected_mcp_tools: tuple[AIBuilderResourceReferenceEntry, ...]


@dataclass(frozen=True)
class AIBuilderResourceCatalogEntry:
    ref: str
    display_name: str
    aliases: tuple[str, ...]
    kind: ResourceKind
    description: str = ""
    parent_ref: str | None = None

    @property
    def option_label(self) -> str:
        return f"{self.display_name} [{self.ref}]"


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
    mcp_servers: tuple[AIBuilderResourceCatalogEntry, ...]
    mcp_tools: tuple[AIBuilderResourceCatalogEntry, ...]
    _model_alias_index: dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]
    _kb_alias_index: dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]
    _mcp_server_alias_index: dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]
    _mcp_tool_alias_index: dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]

    @property
    def model_refs(self) -> set[str]:
        return {entry.ref for entry in self.models}

    @property
    def knowledge_base_refs(self) -> set[str]:
        return {entry.ref for entry in self.knowledge_bases}

    @property
    def mcp_server_refs(self) -> set[str]:
        return {entry.ref for entry in self.mcp_servers}

    @property
    def mcp_tool_refs(self) -> set[str]:
        return {entry.ref for entry in self.mcp_tools}

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
        return resolved_entry.ref, None

    def entry_for_ref(
        self,
        *,
        kind: ResourceKind,
        ref: str,
    ) -> AIBuilderResourceCatalogEntry | None:
        return next(
            (entry for entry in self._entries_for_kind(kind) if entry.ref == ref),
            None,
        )

    def mcp_tool_refs_for_server(self, server_ref: str) -> list[str]:
        return [entry.ref for entry in self.mcp_tools if entry.parent_ref == server_ref]

    def refs_mentioned_in_text(
        self,
        *,
        kind: ResourceKind,
        text: str,
        allowed_refs: Iterable[str] | None = None,
    ) -> frozenset[str]:
        """Return catalog refs whose aliases are explicitly present in text.

        This is a resource-name matcher, not workflow inference. It lets AI
        Builder recover from small-model omissions such as naming "Time MCP" in
        a semantic step but forgetting to repeat the canonical ref field.
        """

        haystack = _normalize_alias(text)
        if not haystack:
            return frozenset()
        allowed = set(allowed_refs) if allowed_refs is not None else None
        matched: set[str] = set()
        for entry in self._entries_for_kind(kind):
            if allowed is not None and entry.ref not in allowed:
                continue
            if _entry_alias_is_mentioned(entry=entry, normalized_text=haystack):
                matched.add(entry.ref)
        return frozenset(matched)

    def _alias_index_for_kind(
        self,
        kind: ResourceKind,
    ) -> dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]:
        if kind == "knowledge_base":
            return self._kb_alias_index
        if kind == "mcp_server":
            return self._mcp_server_alias_index
        if kind == "mcp_tool":
            return self._mcp_tool_alias_index
        return self._model_alias_index

    def _entries_for_kind(
        self,
        kind: ResourceKind,
    ) -> tuple[AIBuilderResourceCatalogEntry, ...]:
        if kind == "knowledge_base":
            return self.knowledge_bases
        if kind == "mcp_server":
            return self.mcp_servers
        if kind == "mcp_tool":
            return self.mcp_tools
        return self.models


def build_ai_builder_resource_catalog(
    *,
    available_models: Sequence[Mapping[str, Any]] | None,
    available_kbs: Sequence[Mapping[str, Any]] | None,
    available_mcps: Iterable[Mapping[str, Any]] | None = None,
) -> AIBuilderResourceCatalog:
    models = tuple(_build_entries(available_models or [], kind="model"))
    knowledge_bases = tuple(_build_entries(available_kbs or [], kind="knowledge_base"))
    normalized_mcps = normalize_ai_builder_mcp_resources(available_mcps)
    mcp_servers = tuple(_build_entries(normalized_mcps, kind="mcp_server"))
    mcp_tools = tuple(_build_mcp_tool_entries(normalized_mcps))
    return AIBuilderResourceCatalog(
        models=models,
        knowledge_bases=knowledge_bases,
        mcp_servers=mcp_servers,
        mcp_tools=mcp_tools,
        _model_alias_index=_build_alias_index(models),
        _kb_alias_index=_build_alias_index(knowledge_bases),
        _mcp_server_alias_index=_build_alias_index(mcp_servers),
        _mcp_tool_alias_index=_build_alias_index(mcp_tools),
    )


def build_ai_builder_resource_reference_material(
    *,
    catalog: AIBuilderResourceCatalog,
    selected_mcp_server_refs: Iterable[str] | None = None,
) -> AIBuilderResourceReferenceMaterial:
    selected_servers = set(selected_mcp_server_refs or ())
    return AIBuilderResourceReferenceMaterial(
        models=tuple(_resource_reference_entry(entry) for entry in catalog.models),
        knowledge_bases=tuple(
            _resource_reference_entry(entry) for entry in catalog.knowledge_bases
        ),
        mcp_servers=tuple(
            _resource_reference_entry(entry) for entry in catalog.mcp_servers
        ),
        mcp_tools=tuple(
            _resource_reference_entry(entry) for entry in catalog.mcp_tools
        ),
        selected_mcp_servers=tuple(
            _resource_reference_entry(entry)
            for entry in catalog.mcp_servers
            if entry.ref in selected_servers
        ),
        selected_mcp_tools=tuple(
            _resource_reference_entry(entry)
            for entry in catalog.mcp_tools
            if entry.parent_ref in selected_servers
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


def canonicalize_edit_draft_resources(
    draft: FlowEditDraft,
    *,
    catalog: AIBuilderResourceCatalog,
) -> tuple[FlowEditDraft, list[AIBuilderResourceResolutionIssue]]:
    issues: list[AIBuilderResourceResolutionIssue] = []
    operations: list[StepEditOperation] = []
    changed = False
    for index, operation in enumerate(draft.operations):
        operation_location = f"operation {index + 1}"
        updated = operation
        if operation.add_payload is not None:
            assistant_spec, assistant_issues = canonicalize_assistant_spec_resources(
                AssistantSpec(
                    instructions=operation.add_payload.instructions or "",
                    model_ref=operation.add_payload.model_ref,
                    knowledge_refs=list(operation.add_payload.knowledge_refs),
                    mcp_server_refs=list(operation.add_payload.mcp_server_refs),
                    mcp_tool_refs=list(operation.add_payload.mcp_tool_refs),
                ),
                catalog=catalog,
                location_prefix=f"{operation_location} add_payload",
            )
            issues.extend(assistant_issues)
            if (
                assistant_spec.model_ref != operation.add_payload.model_ref
                or assistant_spec.knowledge_refs != operation.add_payload.knowledge_refs
                or assistant_spec.mcp_server_refs
                != operation.add_payload.mcp_server_refs
                or assistant_spec.mcp_tool_refs != operation.add_payload.mcp_tool_refs
            ):
                changed = True
                updated = updated.model_copy(
                    update={
                        "add_payload": operation.add_payload.model_copy(
                            update={
                                "model_ref": assistant_spec.model_ref,
                                "knowledge_refs": assistant_spec.knowledge_refs,
                                "mcp_server_refs": assistant_spec.mcp_server_refs,
                                "mcp_tool_refs": assistant_spec.mcp_tool_refs,
                            }
                        ),
                    }
                )
        if updated.patch is not None and updated.patch.assistant_spec is not None:
            assistant_spec, assistant_issues = canonicalize_assistant_spec_resources(
                updated.patch.assistant_spec,
                catalog=catalog,
                location_prefix=f"{operation_location} patch",
            )
            issues.extend(assistant_issues)
            if assistant_spec != updated.patch.assistant_spec:
                changed = True
                updated = updated.model_copy(
                    update={
                        "patch": updated.patch.model_copy(
                            update={"assistant_spec": assistant_spec}
                        ),
                    }
                )
        operations.append(updated)
    if not changed:
        return draft, issues
    return draft.model_copy(update={"operations": operations}), issues


def canonicalize_create_draft_resources(
    draft: FlowCreateDraft,
    *,
    catalog: AIBuilderResourceCatalog,
) -> tuple[FlowCreateDraft, list[AIBuilderResourceResolutionIssue]]:
    issues: list[AIBuilderResourceResolutionIssue] = []
    updated_steps: list[NewStepDraft] = []
    changed = False
    for index, step in enumerate(draft.steps):
        assistant_spec, assistant_issues = canonicalize_assistant_spec_resources(
            AssistantSpec(
                instructions=step.instructions or "",
                model_ref=step.model_ref,
                knowledge_refs=list(step.knowledge_refs),
                mcp_server_refs=list(step.mcp_server_refs),
                mcp_tool_refs=list(step.mcp_tool_refs),
            ),
            catalog=catalog,
            location_prefix=f"steps[{index}]",
        )
        issues.extend(assistant_issues)
        if (
            assistant_spec.model_ref != step.model_ref
            or assistant_spec.knowledge_refs != step.knowledge_refs
            or assistant_spec.mcp_server_refs != step.mcp_server_refs
            or assistant_spec.mcp_tool_refs != step.mcp_tool_refs
        ):
            changed = True
            updated_steps.append(
                step.model_copy(
                    update={
                        "model_ref": assistant_spec.model_ref,
                        "knowledge_refs": assistant_spec.knowledge_refs,
                        "mcp_server_refs": assistant_spec.mcp_server_refs,
                        "mcp_tool_refs": assistant_spec.mcp_tool_refs,
                    }
                )
            )
        else:
            updated_steps.append(step)

    if not changed:
        return draft, issues
    return draft.model_copy(update={"steps": updated_steps}), issues


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

    updated_mcp_server_refs: list[str] = []
    for index, reference in enumerate(assistant_spec.mcp_server_refs):
        resolved, issue = catalog.resolve(
            kind="mcp_server",
            value=reference,
            location=f"{location_prefix}.assistant_spec.mcp_server_refs[{index}]",
        )
        if issue is not None:
            issues.append(issue)
            continue
        if resolved is not None and resolved not in updated_mcp_server_refs:
            updated_mcp_server_refs.append(resolved)

    explicitly_selected_mcp_server_refs = list(updated_mcp_server_refs)
    updated_mcp_tool_refs: list[str] = []
    for index, reference in enumerate(assistant_spec.mcp_tool_refs):
        resolved, issue = catalog.resolve(
            kind="mcp_tool",
            value=reference,
            location=f"{location_prefix}.assistant_spec.mcp_tool_refs[{index}]",
        )
        if issue is not None:
            issues.append(issue)
            continue
        if resolved is None or resolved in updated_mcp_tool_refs:
            continue
        updated_mcp_tool_refs.append(resolved)
        tool_entry = catalog.entry_for_ref(kind="mcp_tool", ref=resolved)
        if (
            tool_entry is not None
            and tool_entry.parent_ref is not None
            and tool_entry.parent_ref not in updated_mcp_server_refs
        ):
            updated_mcp_server_refs.append(tool_entry.parent_ref)

    expanded_mcp_tool_refs = list(updated_mcp_tool_refs)
    for server_ref in explicitly_selected_mcp_server_refs:
        for tool_ref in catalog.mcp_tool_refs_for_server(server_ref):
            if tool_ref not in expanded_mcp_tool_refs:
                expanded_mcp_tool_refs.append(tool_ref)

    if (
        updated_model_ref == assistant_spec.model_ref
        and updated_knowledge_refs == assistant_spec.knowledge_refs
        and updated_mcp_server_refs == assistant_spec.mcp_server_refs
        and expanded_mcp_tool_refs == assistant_spec.mcp_tool_refs
    ):
        return assistant_spec, issues

    return (
        assistant_spec.model_copy(
            update={
                "model_ref": updated_model_ref,
                "knowledge_refs": updated_knowledge_refs,
                "mcp_server_refs": updated_mcp_server_refs,
                "mcp_tool_refs": expanded_mcp_tool_refs,
            }
        ),
        issues,
    )


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
    if kind == "mcp_server":
        return "MCP server"
    if kind == "mcp_tool":
        return "MCP tool"
    return "model"


def _issue_code(*, kind: ResourceKind, prefix: Literal["ambiguous", "unknown"]) -> str:
    suffix = {
        "knowledge_base": "kb",
        "mcp_server": "mcp_server",
        "mcp_tool": "mcp_tool",
        "model": "model",
    }[kind]
    return f"{prefix}_{suffix}_ref"


def _build_entries(
    items: Sequence[Mapping[str, Any]],
    *,
    kind: ResourceKind,
) -> list[AIBuilderResourceCatalogEntry]:
    entries: list[AIBuilderResourceCatalogEntry] = []
    for item in items:
        ref = str(item.get("ref", item.get("id", ""))).strip()
        if not ref:
            continue
        display_name = (
            str(item.get("display_name", item.get("name", ref))).strip() or ref
        )
        aliases = tuple(
            dict.fromkeys(
                filter(
                    None,
                    [
                        _normalize_alias(ref),
                        _normalize_alias(display_name),
                    ],
                )
            )
        )
        entries.append(
            AIBuilderResourceCatalogEntry(
                ref=ref,
                display_name=display_name,
                aliases=aliases,
                kind=kind,
                description=str(item.get("description", "")).strip(),
            )
        )
    return entries


def _resource_reference_entry(
    entry: AIBuilderResourceCatalogEntry,
) -> AIBuilderResourceReferenceEntry:
    return AIBuilderResourceReferenceEntry(
        ref=entry.ref,
        display_name=entry.display_name,
        description=_bounded_description(entry.description),
        parent_ref=entry.parent_ref,
    )


def _bounded_description(description: str) -> str:
    if len(description) <= RESOURCE_DESCRIPTION_MAX_CHARS:
        return description
    return description[: RESOURCE_DESCRIPTION_MAX_CHARS - 3].rstrip() + "..."


def _build_mcp_tool_entries(
    available_mcps: list[AIBuilderMCPServerResource],
) -> list[AIBuilderResourceCatalogEntry]:
    entries: list[AIBuilderResourceCatalogEntry] = []
    for server in available_mcps:
        server_ref = server["ref"]
        if not server_ref:
            continue
        server_name = server["display_name"] or server["name"] or server_ref
        for tool in server["tools"]:
            ref = tool["ref"]
            if not ref:
                continue
            display_name = tool["display_name"] or tool["name"] or ref
            aliases = tuple(
                dict.fromkeys(
                    filter(
                        None,
                        [
                            _normalize_alias(ref),
                            _normalize_alias(display_name),
                            _normalize_alias(f"{server_name} {display_name}"),
                        ],
                    )
                )
            )
            entries.append(
                AIBuilderResourceCatalogEntry(
                    ref=ref,
                    display_name=f"{server_name}: {display_name}",
                    aliases=aliases,
                    kind="mcp_tool",
                    description=tool["description"],
                    parent_ref=server_ref,
                )
            )
    return entries


def _build_alias_index(
    entries: tuple[AIBuilderResourceCatalogEntry, ...],
) -> dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]:
    alias_index: dict[str, list[AIBuilderResourceCatalogEntry]] = {}
    for entry in entries:
        for alias in entry.aliases:
            alias_index.setdefault(alias, []).append(entry)
    return {alias: tuple(values) for alias, values in alias_index.items()}


def _normalize_alias(value: str) -> str:
    stripped = value.strip().casefold()
    collapsed = _NON_ALNUM_RE.sub("-", stripped).strip("-")
    return collapsed or stripped


def _entry_alias_is_mentioned(
    *,
    entry: AIBuilderResourceCatalogEntry,
    normalized_text: str,
) -> bool:
    bounded_text = f"-{normalized_text}-"
    for alias in entry.aliases:
        if not alias:
            continue
        if f"-{alias}-" in bounded_text:
            return True
    return False
