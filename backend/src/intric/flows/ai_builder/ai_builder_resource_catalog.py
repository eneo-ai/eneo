from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from intric.flows.ai_builder.ai_builder_create_models import FlowCreateDraft
from intric.flows.ai_builder.ai_builder_edit_models import (
    FlowEditDraft,
    StepEditOperation,
)
from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    FlowDraftSpecCore,
    StepSpec,
)
from intric.flows.ai_builder.ai_builder_new_step_models import NewStepDraft

ResourceKind = Literal["knowledge_base", "model"]

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class AIBuilderResourceCatalogEntry:
    ref: str
    display_name: str
    aliases: tuple[str, ...]
    kind: ResourceKind

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
    _model_alias_index: dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]
    _kb_alias_index: dict[str, tuple[AIBuilderResourceCatalogEntry, ...]]

    @property
    def model_refs(self) -> set[str]:
        return {entry.ref for entry in self.models}

    @property
    def knowledge_base_refs(self) -> set[str]:
        return {entry.ref for entry in self.knowledge_bases}

    def resolve(
        self,
        *,
        kind: ResourceKind,
        value: str,
        location: str,
    ) -> tuple[str | None, AIBuilderResourceResolutionIssue | None]:
        normalized = _normalize_alias(value)
        alias_index = (
            self._kb_alias_index
            if kind == "knowledge_base"
            else self._model_alias_index
        )
        entries: tuple[AIBuilderResourceCatalogEntry, ...] = alias_index.get(
            normalized,
            tuple(),
        )
        if not entries:
            return None, AIBuilderResourceResolutionIssue(
                kind=kind,
                code="unknown_kb_ref"
                if kind == "knowledge_base"
                else "unknown_model_ref",
                provided_value=value,
                location=location,
                valid_options=tuple(
                    entry.option_label
                    for entry in (
                        self.knowledge_bases
                        if kind == "knowledge_base"
                        else self.models
                    )
                ),
            )
        if len(entries) > 1:
            return None, AIBuilderResourceResolutionIssue(
                kind=kind,
                code="ambiguous_kb_ref"
                if kind == "knowledge_base"
                else "ambiguous_model_ref",
                provided_value=value,
                location=location,
                valid_options=tuple(entry.option_label for entry in entries),
            )
        resolved_entry = next(iter(entries), None)
        if resolved_entry is None:
            return None, AIBuilderResourceResolutionIssue(
                kind=kind,
                code="unknown_kb_ref"
                if kind == "knowledge_base"
                else "unknown_model_ref",
                provided_value=value,
                location=location,
                valid_options=tuple(
                    entry.option_label
                    for entry in (
                        self.knowledge_bases
                        if kind == "knowledge_base"
                        else self.models
                    )
                ),
            )
        return resolved_entry.ref, None


def build_ai_builder_resource_catalog(
    *,
    available_models: list[dict[str, Any]] | None,
    available_kbs: list[dict[str, Any]] | None,
) -> AIBuilderResourceCatalog:
    models = tuple(_build_entries(available_models or [], kind="model"))
    knowledge_bases = tuple(_build_entries(available_kbs or [], kind="knowledge_base"))
    return AIBuilderResourceCatalog(
        models=models,
        knowledge_bases=knowledge_bases,
        _model_alias_index=_build_alias_index(models),
        _kb_alias_index=_build_alias_index(knowledge_bases),
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
                ),
                catalog=catalog,
                location_prefix=f"{operation_location} add_payload",
            )
            issues.extend(assistant_issues)
            if (
                assistant_spec.model_ref != operation.add_payload.model_ref
                or assistant_spec.knowledge_refs != operation.add_payload.knowledge_refs
            ):
                changed = True
                updated = updated.model_copy(
                    update={
                        "add_payload": operation.add_payload.model_copy(
                            update={
                                "model_ref": assistant_spec.model_ref,
                                "knowledge_refs": assistant_spec.knowledge_refs,
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
            ),
            catalog=catalog,
            location_prefix=f"steps[{index}]",
        )
        issues.extend(assistant_issues)
        if (
            assistant_spec.model_ref != step.model_ref
            or assistant_spec.knowledge_refs != step.knowledge_refs
        ):
            changed = True
            updated_steps.append(
                step.model_copy(
                    update={
                        "model_ref": assistant_spec.model_ref,
                        "knowledge_refs": assistant_spec.knowledge_refs,
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


def format_resource_resolution_feedback(
    issues: list[AIBuilderResourceResolutionIssue],
) -> str:
    lines: list[str] = []
    for issue in issues:
        resource_label = "knowledge base" if issue.kind == "knowledge_base" else "model"
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


def _build_entries(
    items: list[dict[str, Any]],
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
