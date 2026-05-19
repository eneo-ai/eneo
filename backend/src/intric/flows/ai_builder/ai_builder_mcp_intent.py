from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast

from intric.flows.ai_builder.ai_builder_models import (
    AssistantSpec,
    ConversationMessage,
    FlowDraftSpecCore,
)
from intric.flows.ai_builder.ai_builder_resource_catalog import (
    AIBuilderResourceCatalog,
    AIBuilderResourceCatalogEntry,
)

MCP_RESOURCE_SELECTION_QUESTION_ID = "mcp_resource_selection"
MCP_SELECTION_WITHOUT = "without_mcp"
MCP_SELECTION_USE_SERVER_PREFIX = "use_mcp_server:"

_MCP_NAME_BEFORE_MARKER_RE = re.compile(
    r"\b([a-z0-9åäöé][a-z0-9åäöé_-]*(?:\s+[a-z0-9åäöé][a-z0-9åäöé_-]*){0,2})\s+mcp\b",
    re.IGNORECASE,
)
_MCP_NAME_AFTER_MARKER_RE = re.compile(
    r"\bmcp\s+(?:för|for)\s+([a-z0-9åäöé][a-z0-9åäöé_-]*(?:\s+[a-z0-9åäöé][a-z0-9åäöé_-]*){0,2})",
    re.IGNORECASE,
)
_NO_MCP_EXTERNAL_VERB_RE = re.compile(
    r"\b(fetch(?:es|ing)?|retrieve(?:s|ing)?|call(?:s|ing)?|query(?:ing|ies)?|"
    r"send(?:s|ing)?|deliver(?:s|ing)?|post(?:s|ing)?|skicka|skickar|skickas|"
    r"leverera|levererar|posta|postar|"
    r"hämta|hämtar|hämtas|inhämta|inhämtar|anropa|anropar)\b",
    re.IGNORECASE,
)
_NO_MCP_EXTERNAL_CONTEXT_RE = re.compile(
    r"\b(live|realtime|real-time|current|external|extern(?:a|t)?|api|integration|"
    r"tool|tools|verktyg|realtid|aktuell(?:a|t)?|tid|time|tidsfunktion)\b",
    re.IGNORECASE,
)

# Generic glue and negation words around "MCP" are handled before resolving an
# explicit server name. This is grammar cleanup, not workflow/domain matching.
_MCP_NAME_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "använd",
        "använda",
        "att",
        "av",
        "de",
        "den",
        "det",
        "eller",
        "en",
        "ett",
        "for",
        "från",
        "i",
        "in",
        "med",
        "mcp",
        "no",
        "och",
        "om",
        "or",
        "protocol",
        "protocols",
        "protokoll",
        "på",
        "server",
        "servern",
        "servers",
        "som",
        "spec",
        "specification",
        "specifications",
        "specifikation",
        "specifikationer",
        "specs",
        "standard",
        "standarder",
        "standards",
        "the",
        "till",
        "to",
        "tool",
        "tools",
        "utan",
        "use",
        "using",
        "verktyg",
        "verktyget",
        "via",
        "with",
        "without",
        "ingen",
        "inget",
        "inga",
        "inte",
    }
)
_MCP_NAME_NEGATION_WORDS: frozenset[str] = frozenset(
    {"no", "without", "utan", "ingen", "inget", "inga", "inte"}
)
_MCP_GENERIC_MARKER_PRECEDERS: frozenset[str] = frozenset(
    {
        "common",
        "generic",
        "generell",
        "generella",
        "protocol",
        "protocols",
        "protokoll",
        "spec",
        "specification",
        "specifications",
        "specifikation",
        "specifikationer",
        "specs",
        "standard",
        "standarder",
        "standards",
        "vanlig",
        "vanliga",
    }
)

MCPReferenceIssueReason = Literal[
    "missing_selection",
    "unavailable_requested_server",
    "different_selected_server",
]


@dataclass(frozen=True, slots=True)
class NamedMCPReferenceIssue:
    """A step mentions a named MCP but cannot map it to the selected MCP refs."""

    requested_name: str
    name_candidates: tuple[str, ...]
    step_name: str
    step_ref: str
    reason: MCPReferenceIssueReason
    resolved_server_ref: str | None
    selected_server_refs: frozenset[str]

    @property
    def selected_any_mcp(self) -> bool:
        return bool(self.selected_server_refs)


def find_named_mcp_reference_issue(
    *,
    spec: FlowDraftSpecCore,
    catalog: AIBuilderResourceCatalog,
    signal_text: str,
) -> NamedMCPReferenceIssue | None:
    """Return the first explicit named-MCP mismatch in a compiled plan.

    The planner may describe a tool by name in natural language. This helper
    checks that such names resolve to enabled space MCP metadata and to
    selected server refs. Downstream steps may reference the named MCP in
    prose without carrying refs themselves when another step already uses
    the selected MCP. It deliberately does not infer domain semantics from
    arbitrary words; external-tool choice must stay catalog-owned.
    """

    global_name_groups = explicit_mcp_name_groups(signal_text)
    global_name_groups = global_name_groups if len(global_name_groups) == 1 else []
    plan_selected_server_refs = frozenset(
        selected_ref
        for step in spec.steps
        for selected_ref in selected_mcp_server_refs(catalog, step.assistant_spec)
    )

    for step in spec.steps:
        local_name_groups = explicit_mcp_name_groups(
            " ".join((step.name, step.assistant_spec.instructions))
        )
        if not local_name_groups:
            continue

        selected_server_refs = selected_mcp_server_refs(catalog, step.assistant_spec)
        for name_group in local_name_groups:
            issue = _reference_issue_for_name_group(
                catalog=catalog,
                name_group=name_group,
                selected_server_refs=selected_server_refs,
                step_name=step.name,
                step_ref=step.plan_step_ref,
                flag_unresolved=False,
            )
            if issue is not None:
                if (
                    issue.reason == "missing_selection"
                    and issue.resolved_server_ref in plan_selected_server_refs
                ):
                    continue
                return issue

    if global_name_groups:
        issue = _reference_issue_for_name_group(
            catalog=catalog,
            name_group=global_name_groups[0],
            selected_server_refs=plan_selected_server_refs,
            step_name="plan",
            step_ref="plan",
        )
        if issue is not None:
            return issue
    return None


def find_named_mcp_request_issue(
    *,
    catalog: AIBuilderResourceCatalog,
    signal_text: str,
) -> NamedMCPReferenceIssue | None:
    """Detect an explicit user request for an MCP resource.

    A named MCP in user text is a resource decision, not a drafting hint. The
    backend asks for a concrete selection before the model may attach MCP refs,
    even when the named server is already enabled in the space.
    """

    for name_group in explicit_mcp_name_groups(signal_text):
        for name in name_group:
            resolved_ref = _resolve_named_mcp_server(catalog, name)
            if resolved_ref is not None:
                return NamedMCPReferenceIssue(
                    requested_name=name_group[-1],
                    name_candidates=name_group,
                    step_name="conversation",
                    step_ref="conversation",
                    reason="missing_selection",
                    resolved_server_ref=resolved_ref,
                    selected_server_refs=frozenset(),
                )
        return NamedMCPReferenceIssue(
            requested_name=name_group[-1],
            name_candidates=name_group,
            step_name="conversation",
            step_ref="conversation",
            reason="unavailable_requested_server",
            resolved_server_ref=None,
            selected_server_refs=frozenset(),
        )
    return None


def find_unavailable_named_mcp_request(
    *,
    catalog: AIBuilderResourceCatalog,
    signal_text: str,
) -> NamedMCPReferenceIssue | None:
    """Detect a user-named MCP that is not among enabled space MCP metadata."""

    for name_group in explicit_mcp_name_groups(signal_text):
        if any(_resolve_named_mcp_server(catalog, name) for name in name_group):
            continue
        return NamedMCPReferenceIssue(
            requested_name=name_group[-1],
            name_candidates=name_group,
            step_name="conversation",
            step_ref="conversation",
            reason="unavailable_requested_server",
            resolved_server_ref=None,
            selected_server_refs=frozenset(),
        )
    return None


def find_mcp_usage_without_selection_issue(
    *,
    spec: FlowDraftSpecCore,
    catalog: AIBuilderResourceCatalog,
) -> NamedMCPReferenceIssue | None:
    """Return a clarification issue when a draft uses MCP before user approval."""

    for step in spec.steps:
        selected_server_refs = selected_mcp_server_refs(catalog, step.assistant_spec)
        if not selected_server_refs:
            continue
        resolved_ref = sorted(selected_server_refs)[0]
        entry = catalog.entry_for_ref(kind="mcp_server", ref=resolved_ref)
        requested_name = entry.display_name if entry is not None else "MCP"
        return NamedMCPReferenceIssue(
            requested_name=requested_name,
            name_candidates=(requested_name,),
            step_name=step.name,
            step_ref=step.plan_step_ref,
            reason="missing_selection",
            resolved_server_ref=resolved_ref,
            selected_server_refs=selected_server_refs,
        )
    return None


def mcp_resource_selection_values(
    conversation: list[ConversationMessage],
) -> frozenset[str]:
    """Return the latest still-current MCP-selection answer values."""

    answer = _latest_mcp_selection_answer(conversation)
    if answer is None:
        return frozenset()
    answer_index, values = answer
    if _has_later_explicit_mcp_request(conversation, after_index=answer_index):
        return frozenset()
    return values


def _latest_mcp_selection_answer(
    conversation: list[ConversationMessage],
) -> tuple[int, frozenset[str]] | None:
    for index in range(len(conversation) - 1, -1, -1):
        message = conversation[index]
        if message.role != "user":
            continue
        metadata = (
            cast(dict[str, object], message.metadata)
            if isinstance(message.metadata, dict)
            else None
        )
        raw_question_answer = metadata.get("question_answer") if metadata else None
        if not isinstance(raw_question_answer, dict):
            continue
        question_answer = cast(dict[str, object], raw_question_answer)
        if question_answer.get("question_id") != MCP_RESOURCE_SELECTION_QUESTION_ID:
            continue
        values: set[str] = set()
        selected_values = question_answer.get("selected_values")
        if isinstance(selected_values, list):
            values.update(
                str(value)
                for value in cast(list[object], selected_values)
                if value is not None
            )
        selected_value = question_answer.get("selected_value")
        if selected_value is not None:
            values.add(str(selected_value))
        custom_value = question_answer.get("custom_value")
        if isinstance(custom_value, str) and custom_value.strip():
            values.add(custom_value.strip())
        return index, frozenset(values)
    return None


def _has_later_explicit_mcp_request(
    conversation: list[ConversationMessage],
    *,
    after_index: int,
) -> bool:
    for message in conversation[after_index + 1 :]:
        if message.role == "user" and explicit_mcp_name_groups(message.content or ""):
            return True
    return False


def mcp_selection_answer_allows_planning(
    conversation: list[ConversationMessage],
) -> bool:
    """True when the latest MCP question answer should let planning continue."""

    values = mcp_resource_selection_values(conversation)
    return MCP_SELECTION_WITHOUT in values or bool(
        mcp_selected_server_refs_from_values(values)
    )


def mcp_selected_server_refs_from_values(
    values: set[str] | frozenset[str],
) -> frozenset[str]:
    return frozenset(
        value.removeprefix(MCP_SELECTION_USE_SERVER_PREFIX)
        for value in values
        if value.startswith(MCP_SELECTION_USE_SERVER_PREFIX)
        and value != MCP_SELECTION_USE_SERVER_PREFIX
    )


def mcp_selection_policy_feedback(
    *,
    conversation: list[ConversationMessage],
    spec: FlowDraftSpecCore,
    catalog: AIBuilderResourceCatalog,
) -> str | None:
    """Hard-enforce the latest MCP selection against compiled step refs."""

    values = mcp_resource_selection_values(conversation)
    if not values:
        return None

    usage = _mcp_usage_by_step(spec=spec, catalog=catalog)
    if MCP_SELECTION_WITHOUT in values:
        if not usage:
            if _claims_external_capability_without_mcp(spec):
                return (
                    "The user selected 'continue without MCP', but the plan still "
                    "claims it can fetch live/external data or deliver results to "
                    "an external system without a tool. Rewrite the plan so any "
                    "live, current, external, or outbound delivery dependency is "
                    "provided as runtime input, handled by an enabled integration, "
                    "or called out as unsupported."
                )
            return None
        return (
            "The user selected 'continue without MCP'. Remove all "
            "`mcp_server_refs` and `mcp_tool_refs` from every step and solve the "
            "flow with normal AI Builder capabilities."
        )

    allowed_server_refs = mcp_selected_server_refs_from_values(values)
    if not allowed_server_refs:
        return None

    if not usage:
        allowed_names = _server_names(catalog, allowed_server_refs)
        return (
            "The user selected MCP server(s) "
            f"{', '.join(allowed_names)}. Use one of the selected server's tools on "
            "the relevant step, or ask a new clarification question if the flow no "
            "longer needs MCP."
        )

    for step_name, used_server_refs in usage:
        unexpected_refs = used_server_refs - allowed_server_refs
        if unexpected_refs:
            unexpected_names = _server_names(catalog, unexpected_refs)
            allowed_names = _server_names(catalog, allowed_server_refs)
            return (
                f"Step '{step_name}' uses MCP server(s) "
                f"{', '.join(unexpected_names)}, but the user only selected "
                f"{', '.join(allowed_names)}. Remove the unselected MCP refs and use "
                "only the selected MCP server/tool refs."
            )
    return None


def selected_mcp_server_refs(
    catalog: AIBuilderResourceCatalog,
    assistant_spec: AssistantSpec,
) -> frozenset[str]:
    selected_refs: set[str] = set()
    for ref in assistant_spec.mcp_server_refs:
        entry = catalog.entry_for_ref(kind="mcp_server", ref=ref)
        if entry is not None:
            selected_refs.add(entry.authoring_ref)
    for ref in assistant_spec.mcp_tool_refs:
        entry = catalog.entry_for_ref(kind="mcp_tool", ref=ref)
        if entry is not None and entry.parent_ref is not None:
            selected_refs.add(entry.parent_ref)
    return frozenset(selected_refs)


def explicit_mcp_name_groups(text: str) -> list[tuple[str, ...]]:
    groups: list[tuple[str, ...]] = []
    for match in _MCP_NAME_BEFORE_MARKER_RE.finditer(text):
        _append_mcp_name_group(groups, match.group(1))
    if groups:
        return groups
    for match in _MCP_NAME_AFTER_MARKER_RE.finditer(text):
        _append_mcp_name_group(groups, match.group(1))
    return groups


def build_mcp_resource_selection_question(
    *,
    issue: NamedMCPReferenceIssue,
    catalog: AIBuilderResourceCatalog,
    language: Literal["sv", "en"] = "sv",
) -> tuple[dict[str, object], str]:
    """Build the same structured-question shape used by discovery follow-ups."""

    requested_name = _requested_display_name(issue, catalog)
    available_servers = list(catalog.mcp_servers)

    if language == "en":
        assistant_text = (
            "I need to confirm MCP usage before I build the plan. I can only use "
            "MCP servers that are enabled in this space."
        )
        if issue.reason == "missing_selection" and issue.resolved_server_ref:
            question = (
                f"{requested_name} is available in this space but is not selected "
                "for this flow yet. Should AI Builder use MCP tools?"
            )
        else:
            question = (
                f"{requested_name} is not available as a selected MCP resource in "
                "this space. How should the flow handle MCP tools?"
            )
        without_label = "Continue without MCP"
        without_description = (
            "Build the flow using normal AI Builder steps and no external MCP tools."
        )
        use_prefix = "Use"
        use_description_prefix = "Available in this space"
        no_description = "No description available."
        tools_label = "Tools"
    else:
        assistant_text = (
            "Jag behöver bekräfta MCP-användningen innan jag bygger planen. "
            "Jag kan bara använda MCP-servrar som är aktiverade i den här ytan."
        )
        if issue.reason == "missing_selection" and issue.resolved_server_ref:
            question = (
                f"{requested_name} finns i den här ytan men är inte valt för "
                "flödet än. Ska AI Builder använda MCP-verktyg?"
            )
        else:
            question = (
                f"{requested_name} finns inte som valt MCP-underlag i den här "
                "ytan. Hur vill du att flödet ska hantera MCP-verktyg?"
            )
        without_label = "Fortsätt utan MCP"
        without_description = (
            "Bygg flödet med vanliga AI Builder-steg och inga externa MCP-verktyg."
        )
        use_prefix = "Använd"
        use_description_prefix = "Tillgänglig i den här ytan"
        no_description = "Ingen beskrivning tillgänglig."
        tools_label = "Verktyg"

    options: list[dict[str, object]] = [
        {
            "id": "continue_without_mcp",
            "label": without_label,
            "description": without_description,
            "value": MCP_SELECTION_WITHOUT,
        }
    ]

    options.extend(
        {
            "id": f"use_mcp_server_{_safe_option_id(server.authoring_ref)}",
            "label": f"{use_prefix} {server.display_name}",
            "description": _server_option_description(
                server=server,
                catalog=catalog,
                prefix=use_description_prefix,
                fallback=no_description,
                tools_label=tools_label,
            ),
            "value": f"{MCP_SELECTION_USE_SERVER_PREFIX}{server.authoring_ref}",
        }
        for server in available_servers
    )

    return (
        {
            "question_id": MCP_RESOURCE_SELECTION_QUESTION_ID,
            "question": question,
            "options": options,
            "selection_mode": "single",
            "allow_custom": False,
            "requires_confirm": True,
        },
        assistant_text,
    )


def _reference_issue_for_name_group(
    *,
    catalog: AIBuilderResourceCatalog,
    name_group: tuple[str, ...],
    selected_server_refs: frozenset[str],
    step_name: str,
    step_ref: str,
    flag_unresolved: bool = True,
) -> NamedMCPReferenceIssue | None:
    for name in name_group:
        resolved_ref = _resolve_named_mcp_server(catalog, name)
        if resolved_ref is None:
            continue
        if not selected_server_refs:
            return NamedMCPReferenceIssue(
                requested_name=name_group[-1],
                name_candidates=name_group,
                step_name=step_name,
                step_ref=step_ref,
                reason="missing_selection",
                resolved_server_ref=resolved_ref,
                selected_server_refs=selected_server_refs,
            )
        if resolved_ref not in selected_server_refs:
            return NamedMCPReferenceIssue(
                requested_name=name_group[-1],
                name_candidates=name_group,
                step_name=step_name,
                step_ref=step_ref,
                reason="different_selected_server",
                resolved_server_ref=resolved_ref,
                selected_server_refs=selected_server_refs,
            )
        return None

    if not flag_unresolved:
        return None
    return NamedMCPReferenceIssue(
        requested_name=name_group[-1],
        name_candidates=name_group,
        step_name=step_name,
        step_ref=step_ref,
        reason="unavailable_requested_server",
        resolved_server_ref=None,
        selected_server_refs=selected_server_refs,
    )


def _append_mcp_name_group(groups: list[tuple[str, ...]], raw_name: str) -> None:
    raw_words = [word.casefold() for word in raw_name.strip().split()]
    if set(raw_words) & _MCP_NAME_NEGATION_WORDS:
        return
    if raw_words and raw_words[-1] in _MCP_GENERIC_MARKER_PRECEDERS:
        return
    candidates = tuple(_mcp_name_candidates(raw_name))
    if not candidates:
        return
    existing_groups = {tuple(name.casefold() for name in group) for group in groups}
    group_key = tuple(name.casefold() for name in candidates)
    if group_key not in existing_groups:
        groups.append(candidates)


def _mcp_name_candidates(raw_name: str) -> list[str]:
    words = [
        word
        for word in raw_name.strip().split()
        if word.casefold() not in _MCP_NAME_STOPWORDS
    ]
    return [" ".join(words[index:]) for index in range(len(words))]


def _resolve_named_mcp_server(
    catalog: AIBuilderResourceCatalog,
    name: str,
) -> str | None:
    candidates = [name, f"{name} MCP"]
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        resolved, issue = catalog.resolve(
            kind="mcp_server",
            value=candidate,
            location="explicit MCP name",
        )
        if issue is None:
            return resolved
    return None


def _requested_display_name(
    issue: NamedMCPReferenceIssue,
    catalog: AIBuilderResourceCatalog,
) -> str:
    if issue.resolved_server_ref is not None:
        entry = catalog.entry_for_ref(
            kind="mcp_server",
            ref=issue.resolved_server_ref,
        )
        if entry is not None:
            return entry.display_name
    if issue.requested_name.casefold().endswith("mcp"):
        return issue.requested_name
    return f"{issue.requested_name} MCP"


def _server_option_description(
    *,
    server: AIBuilderResourceCatalogEntry,
    catalog: AIBuilderResourceCatalog,
    prefix: str,
    fallback: str,
    tools_label: str,
) -> str:
    tool_names = [
        tool.display_name.split(": ", 1)[-1]
        for tool in catalog.mcp_tools
        if tool.parent_ref == server.authoring_ref
    ]
    tool_summary = ", ".join(tool_names[:3])
    if len(tool_names) > 3:
        tool_summary = f"{tool_summary}, +{len(tool_names) - 3}"
    details = server.description or fallback
    if tool_summary:
        return f"{prefix}. {details} {tools_label}: {tool_summary}."
    return f"{prefix}. {details}"


def _safe_option_id(value: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    return safe.strip("_") or "mcp"


def _mcp_usage_by_step(
    *,
    spec: FlowDraftSpecCore,
    catalog: AIBuilderResourceCatalog,
) -> list[tuple[str, frozenset[str]]]:
    usage: list[tuple[str, frozenset[str]]] = []
    for step in spec.steps:
        server_refs = selected_mcp_server_refs(catalog, step.assistant_spec)
        if server_refs:
            usage.append((step.name, server_refs))
    return usage


def _claims_external_capability_without_mcp(spec: FlowDraftSpecCore) -> bool:
    """Detect tool-like live-data claims after the user declined MCP usage.

    This guard is intentionally about Flow capabilities, not domain workflows:
    without MCP refs the builder may transform supplied input, but it must not
    invent a hidden live-data/API/tool capability.
    """

    for text in _spec_text_fragments(spec):
        if _NO_MCP_EXTERNAL_VERB_RE.search(text) and _NO_MCP_EXTERNAL_CONTEXT_RE.search(
            text
        ):
            return True
    return False


def _spec_text_fragments(spec: FlowDraftSpecCore) -> tuple[str, ...]:
    fragments: list[str] = [spec.flow_name, spec.flow_description]
    for step in spec.steps:
        fragments.append(step.name)
        fragments.append(step.assistant_spec.instructions)
    return tuple(fragment for fragment in fragments if fragment)


def _server_names(
    catalog: AIBuilderResourceCatalog,
    server_refs: frozenset[str],
) -> list[str]:
    names: list[str] = []
    for server_ref in sorted(server_refs):
        entry = catalog.entry_for_ref(kind="mcp_server", ref=server_ref)
        names.append(entry.display_name if entry is not None else server_ref)
    return names
