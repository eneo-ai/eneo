"""Derived result-quality guidance for AI Builder plan proposal.

The contract is a computed view over PlanningState, not a persisted state
branch. It gives the proposal prompt concrete output obligations for the
resolved user outcome so richer clarification changes plan quality.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from eneo.flows.ai_builder.planning_state import PlanningState

ResultObligation = Literal[
    "summary",
    "key_facts",
    "decisions",
    "actions",
    "owners",
    "deadlines",
    "open_questions",
    "risks",
    "deviations",
    "comparison_basis",
    "recommendations",
    "missing_information_policy",
]
ResultOutputFieldRole = Literal[
    "decisions",
    "actions",
    "owners",
    "deadlines",
    "open_questions",
]

RESULT_OBLIGATION_SIGNAL_ID = "result_obligation"
RESULT_OBLIGATION_VALUES: tuple[ResultObligation, ...] = (
    "summary",
    "key_facts",
    "decisions",
    "actions",
    "owners",
    "deadlines",
    "open_questions",
    "risks",
    "deviations",
    "comparison_basis",
    "recommendations",
    "missing_information_policy",
)


@dataclass(frozen=True, slots=True)
class ResultOutputFieldRequirement:
    role: ResultOutputFieldRole
    canonical_name: str
    accepted_names: frozenset[str]


@dataclass(frozen=True, slots=True)
class ResultContract:
    terminal_output: str | None
    post_processing_goal: str | None
    secondary_obligations: tuple[ResultObligation, ...] = ()
    required_sections: tuple[str, ...] = ()
    result_policies: tuple[str, ...] = ()
    required_output_fields: tuple[ResultOutputFieldRequirement, ...] = ()

    @property
    def required_output_field_roles(self) -> tuple[ResultOutputFieldRole, ...]:
        return tuple(field.role for field in self.required_output_fields)


# Accepted names are matched as exact FOLDED equality (fold_result_field_name)
# — never substring containment, which misreads names like "transaction_id"
# as roles. The vocabulary covers the product's own Swedish remediation words
# (with diacritics folded) and the compound shapes explicit nested schemas
# use for action items.
_ACTION_FOLLOWUP_OUTPUT_FIELDS: tuple[ResultOutputFieldRequirement, ...] = (
    ResultOutputFieldRequirement(
        role="decisions",
        canonical_name="decisions",
        accepted_names=frozenset({"decision", "decisions", "beslut"}),
    ),
    ResultOutputFieldRequirement(
        role="actions",
        canonical_name="actions",
        accepted_names=frozenset(
            {
                "action",
                "actions",
                "action_items",
                "next_steps",
                "nasta_steg",
                "atgard",
                "atgarder",
            }
        ),
    ),
    ResultOutputFieldRequirement(
        role="owners",
        canonical_name="owners",
        accepted_names=frozenset(
            {
                "owner",
                "owners",
                "named_owner",
                "responsible",
                "ansvarig",
                "ansvariga",
            }
        ),
    ),
    ResultOutputFieldRequirement(
        role="deadlines",
        canonical_name="deadlines",
        accepted_names=frozenset(
            {"deadline", "deadlines", "due_date", "stated_due_date"}
        ),
    ),
    ResultOutputFieldRequirement(
        role="open_questions",
        canonical_name="open_questions",
        accepted_names=frozenset({"open_questions", "oppna_fragor"}),
    ),
)


_GOAL_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "stop_after_primary_operation": (),
    "summarize_or_overview": (
        "Brief summary",
        "Key points",
    ),
    "extract_key_information": (
        "Extracted key information",
        "Missing or unspecified values",
    ),
    "structure_key_information": (
        "Clear sections",
        "Structured source-grounded notes",
    ),
    "action_followup": (
        "Decisions",
        "Next steps or actions",
        "Owners",
        "Deadlines",
        "Open questions",
    ),
    "decision_support": (
        "Decision context",
        "Options or recommendations",
        "Trade-offs and risks",
        "Recommended next step",
    ),
    "risk_or_issue_review": (
        "Risks, issues, or deviations",
        "Evidence and uncertainty",
        "Recommended follow-up",
    ),
    "compare_or_validate": (
        "Comparison or validation basis",
        "Matches, gaps, or deviations",
        "Actionable conclusion",
    ),
}

_GOAL_POLICIES: dict[str, tuple[str, ...]] = {
    "stop_after_primary_operation": (
        "Stop after the primary operation unless the user explicitly asked for downstream semantic work.",
        "Keep the result source-faithful; do not add summary, recommendations, or analysis.",
    ),
    "summarize_or_overview": (
        "Summarize only what is grounded in the source material.",
        "Call out important missing context instead of inventing details.",
    ),
    "extract_key_information": (
        "Extract only values supported by the source material.",
        "Use explicit missing-value markers when a requested value is absent.",
    ),
    "structure_key_information": (
        "Structure the material without adding unsupported facts.",
        "Preserve source uncertainty and missing information in the final structure.",
    ),
    "action_followup": (
        "Mark missing owners, deadlines, and responsibilities as unspecified; do not invent them.",
        "Keep decisions, actions, owners, deadlines, and open questions distinct.",
    ),
    "decision_support": (
        "Ground recommendations in the source material and separate evidence from judgment.",
        "Surface assumptions and uncertainty that affect the recommended next step.",
    ),
    "risk_or_issue_review": (
        "Separate explicit source evidence from inferred risk.",
        "Do not invent risks; mark uncertainty and missing evidence clearly.",
    ),
    "compare_or_validate": (
        "Compare only against provided reference material, rules, schemas, or checklists.",
        "If the reference material is missing, make that blocker explicit instead of fabricating a comparison.",
    ),
}

_OBLIGATION_POLICIES: dict[ResultObligation, tuple[str, ...]] = {
    "summary": (
        "Include a concise summary when it is explicitly requested, grounded only in the source material.",
    ),
    "key_facts": (
        "Keep key facts distinct from interpretation and mark missing source facts as unspecified.",
    ),
    "decisions": (
        "Keep decisions distinct from recommendations, actions, and open questions.",
    ),
    "actions": (
        "Keep recommended actions separate from observations, risks, and source facts.",
    ),
    "owners": (
        "Mark missing owners as unspecified instead of inventing responsible people or teams.",
    ),
    "deadlines": ("Mark missing deadlines as unspecified instead of inventing dates.",),
    "open_questions": (
        "Preserve open questions separately from decisions and recommended actions.",
    ),
    "risks": (
        "Separate explicit source evidence from inferred risk.",
        "Identify risks only when they are grounded in the source material or supplied rules.",
    ),
    "deviations": (
        "Report deviations against the provided reference material, rules, schemas, or checklist.",
    ),
    "comparison_basis": (
        "State the comparison basis before drawing conclusions from matches, gaps, or deviations.",
    ),
    "recommendations": (
        "Ground recommendations in the source material and separate evidence from judgment.",
    ),
    "missing_information_policy": (
        "Call out missing information explicitly instead of filling gaps with unsupported assumptions.",
    ),
}


def derive_result_contract(planning_state: PlanningState) -> ResultContract | None:
    terminal_output = _slot_value(planning_state, "terminal_output")
    post_processing_goal = _slot_value(planning_state, "post_processing_goal")
    secondary_obligations = _secondary_obligations(planning_state)

    required_sections = _GOAL_REQUIRED_SECTIONS.get(post_processing_goal or "", ())
    required_output_fields = (
        _ACTION_FOLLOWUP_OUTPUT_FIELDS
        if post_processing_goal == "action_followup"
        else ()
    )
    result_policies = _dedupe_policies(
        (
            *_GOAL_POLICIES.get(post_processing_goal or "", ()),
            *(
                policy
                for obligation in secondary_obligations
                for policy in _OBLIGATION_POLICIES.get(obligation, ())
            ),
            *_terminal_output_policies(
                terminal_output=terminal_output,
                post_processing_goal=post_processing_goal,
            ),
        )
    )

    if (
        terminal_output is None
        and post_processing_goal is None
        and not secondary_obligations
    ):
        return None

    return ResultContract(
        terminal_output=terminal_output,
        post_processing_goal=post_processing_goal,
        secondary_obligations=secondary_obligations,
        required_sections=required_sections,
        result_policies=result_policies,
        required_output_fields=required_output_fields,
    )


_FIELD_NAME_SEPARATOR_RE = re.compile(r"[^0-9a-z]+")


def fold_result_field_name(name: str) -> str:
    """Fold a schema field name for role matching.

    Case, diacritics, and separator style must not decide whether a role is
    recognized: proposals name fields in natural Swedish ("åtgärder",
    "öppna frågor") while the accepted vocabulary is stored ASCII-folded.
    """

    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return _FIELD_NAME_SEPARATOR_RE.sub("_", stripped.casefold()).strip("_")


def _requirement_accepts_folded_names(
    requirement: ResultOutputFieldRequirement,
    folded_names: set[str],
) -> bool:
    folded_accepted = {
        fold_result_field_name(name) for name in requirement.accepted_names
    }
    return bool(folded_accepted & folded_names)


def resolve_result_output_field_roles(
    contract: ResultContract,
    field_names: set[str],
) -> frozenset[ResultOutputFieldRole]:
    folded_names = {fold_result_field_name(name) for name in field_names}
    return frozenset(
        requirement.role
        for requirement in contract.required_output_fields
        if _requirement_accepts_folded_names(requirement, folded_names)
    )


_REQUIREMENT_BY_CANONICAL_NAME: dict[str, ResultOutputFieldRequirement] = {
    requirement.canonical_name: requirement
    for requirement in _ACTION_FOLLOWUP_OUTPUT_FIELDS
}


def structured_field_names_satisfy_result_field(
    field_names: set[str],
    canonical_name: str,
) -> bool:
    """True when an already-declared field covers a required contract field.

    Assembly completion uses this to avoid appending a canonical duplicate
    next to an equivalent field the proposal already carries.
    """

    folded_names = {fold_result_field_name(name) for name in field_names}
    requirement = _REQUIREMENT_BY_CANONICAL_NAME.get(canonical_name)
    if requirement is not None:
        return _requirement_accepts_folded_names(requirement, folded_names)
    return fold_result_field_name(canonical_name) in folded_names


def render_result_contract_prompt_block(contract: ResultContract | None) -> str | None:
    if contract is None:
        return None

    lines: list[str] = []
    if contract.terminal_output is not None:
        lines.append(f"- terminal_output: {contract.terminal_output}")
    if contract.post_processing_goal is not None:
        lines.append(f"- post_processing_goal: {contract.post_processing_goal}")
    if contract.secondary_obligations:
        lines.append("- secondary_obligations:")
        lines.extend(
            f"  - {obligation}" for obligation in contract.secondary_obligations
        )
    if contract.required_sections:
        lines.append("- required_sections:")
        lines.extend(f"  - {section}" for section in contract.required_sections)
    if contract.result_policies:
        lines.append("- result_policies:")
        lines.extend(f"  - {policy}" for policy in contract.result_policies)

    return "\n".join(lines)


def _slot_value(planning_state: PlanningState, slot_name: str) -> str | None:
    slot = planning_state.resolved_slots.get(slot_name)
    return slot.value if slot is not None else None


def _secondary_obligations(
    planning_state: PlanningState,
) -> tuple[ResultObligation, ...]:
    values: set[ResultObligation] = set()
    legal_values = set(RESULT_OBLIGATION_VALUES)
    for signal in planning_state.signals:
        if signal.question_id != RESULT_OBLIGATION_SIGNAL_ID:
            continue
        if signal.value in legal_values:
            values.add(signal.value)
    return tuple(
        obligation for obligation in RESULT_OBLIGATION_VALUES if obligation in values
    )


_WHITESPACE_RE = re.compile(r"\s+")


def _dedupe_policies(policies: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for policy in policies:
        normalized = _WHITESPACE_RE.sub(" ", policy.casefold()).strip()
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(policy)
    return tuple(deduped)


def _terminal_output_policies(
    *,
    terminal_output: str | None,
    post_processing_goal: str | None,
) -> tuple[str, ...]:
    if terminal_output == "structured_json":
        return (
            "Use the requested schema or fields as the output contract.",
            "Use null or unspecified placeholders for missing source values; do not add extra keys unless requested.",
        )
    if terminal_output in {
        "pdf_document",
        "docx_document",
    } and post_processing_goal not in {None, "stop_after_primary_operation"}:
        # The proposal task owns renderer topology. The result contract repeats
        # only the outcome-scoped obligation: semantic sections must survive
        # through final PDF/DOCX rendering.
        return (
            "Prepare the complete semantic content before the final document-rendering step.",
            "The final document step should render completed content, not invent new analysis.",
        )
    return ()


__all__ = [
    "RESULT_OBLIGATION_SIGNAL_ID",
    "RESULT_OBLIGATION_VALUES",
    "ResultObligation",
    "ResultContract",
    "ResultOutputFieldRequirement",
    "ResultOutputFieldRole",
    "derive_result_contract",
    "fold_result_field_name",
    "render_result_contract_prompt_block",
    "resolve_result_output_field_roles",
    "structured_field_names_satisfy_result_field",
]
