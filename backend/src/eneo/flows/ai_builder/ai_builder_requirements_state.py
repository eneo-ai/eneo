from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from eneo.flows.ai_builder.ai_builder_conversation_metadata import (
    RequirementsConfirmationMetadata,
    requirements_confirmation_from_metadata,
    requirements_summary_from_metadata,
    tool_calls_from_message,
)
from eneo.flows.ai_builder.ai_builder_domain_models import (
    ConversationMessage,
)
from eneo.flows.ai_builder.ai_builder_event_models import (
    RequirementsDisclosureContent,
    RequirementsSummaryPayload,
)
from eneo.flows.ai_builder.ai_builder_tool_names import (
    PROPOSE_FLOW_TOOL_NAME,
)


def _normalize_requirement_text(text: str) -> str:
    return " ".join(text.strip().casefold().replace(".", " ").replace(":", " ").split())


DEFAULT_REQUIREMENTS_SUMMARY_SV = (
    "Jag har tillräckligt med information för att ta fram ett förslag "
    "till flödesplan. Granska sammanfattningen innan planen byggs."
)
DEFAULT_REQUIREMENTS_SUMMARY_EN = (
    "I have enough information to draft a flow plan. Review this summary "
    "before the plan is built."
)
DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_SV = "Primär indata vid körning behöver granskas."
DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_EN = "Primary runtime input needs review."
DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_SV = "Huvudsakligt slutresultat behöver granskas."
DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_EN = "Primary final output needs review."
DEFAULT_PLAN_FOLLOWS_REQUIREMENTS_SV = (
    "Planen ska följa kraven och underlaget i konversationen."
)
DEFAULT_PLAN_FOLLOWS_REQUIREMENTS_EN = (
    "The plan should follow the requirements and source material in the conversation."
)
DEFAULT_USER_REVIEWS_PLAN_SV = (
    "Användaren ska kunna granska och ändra planen innan den tillämpas."
)
DEFAULT_USER_REVIEWS_PLAN_EN = (
    "The user can review and change the plan before it is applied."
)

_BOILERPLATE_REQUIREMENT_TEXTS = frozenset(
    _normalize_requirement_text(text)
    for text in (
        DEFAULT_REQUIREMENTS_SUMMARY_SV,
        DEFAULT_REQUIREMENTS_SUMMARY_EN,
        DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_SV,
        DEFAULT_RUNTIME_INPUT_NEEDS_REVIEW_EN,
        DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_SV,
        DEFAULT_FINAL_OUTPUT_NEEDS_REVIEW_EN,
        DEFAULT_PLAN_FOLLOWS_REQUIREMENTS_SV,
        DEFAULT_PLAN_FOLLOWS_REQUIREMENTS_EN,
        DEFAULT_USER_REVIEWS_PLAN_SV,
        DEFAULT_USER_REVIEWS_PLAN_EN,
    )
)


@dataclass(frozen=True)
class RequirementsState:
    latest_summary: RequirementsSummaryPayload | None = None
    latest_version: str | None = None
    confirmed_version: str | None = None

    @property
    def confirmed(self) -> bool:
        return (
            self.latest_summary is not None
            and self.latest_version is not None
            and self.confirmed_version == self.latest_version
        )

    @property
    def confirmed_requirements_version(self) -> str | None:
        """The version the user attested to, when it is still the latest one."""

        return self.latest_version if self.confirmed else None


def content_free_confirmation(
    message: ConversationMessage,
) -> RequirementsConfirmationMetadata | None:
    """The confirmation this message carries, when it only confirms.

    Confirming is a content-free structured action. "Yes, but make it informal"
    is a change request wearing a confirmation, and honouring it would build a
    plan from a disclosure that never described what the user just asked for,
    so text beside a confirmation makes the message an ordinary one.
    """

    content = message.content if isinstance(message.content, str) else ""
    if content.strip():
        return None
    return requirements_confirmation_from_metadata(message.metadata)


def build_requirements_version(content: RequirementsDisclosureContent) -> str:
    """Hash the disclosure record the user is shown, unclipped.

    Identity is taken from the typed record, not from the prose: display
    clips long evidence values so a summary stays readable, and two different
    values that clip to the same 80 characters must still be two different
    disclosures.
    """

    serialized = json.dumps(
        content.model_dump(
            mode="json",
            include=set(RequirementsDisclosureContent.model_fields),
        ),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def is_boilerplate_requirement_text(text: str) -> bool:
    normalized = _normalize_requirement_text(text)
    return normalized in _BOILERPLATE_REQUIREMENT_TEXTS


def user_relevant_requirement_text(text: str) -> str | None:
    stripped = text.strip()
    if not stripped or is_boilerplate_requirement_text(stripped):
        return None
    return stripped


def user_relevant_requirement_notes(notes: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        relevant
        for note in notes
        if (relevant := user_relevant_requirement_text(note)) is not None
    )


def resolve_requirements_state(
    conversation: list[ConversationMessage],
) -> RequirementsState:
    latest_summary: RequirementsSummaryPayload | None = None
    latest_version: str | None = None
    latest_summary_index: int | None = None

    for index, message in enumerate(conversation):
        if message.role not in ("tool", "assistant"):
            continue
        persisted_summary = requirements_summary_from_metadata(message.metadata)
        if persisted_summary is None:
            continue
        # The stored version names the disclosure the user was shown. It is
        # not recomputed here: the version hashes the unclipped disclosure
        # record, and the persisted payload carries only the clipped prose.
        latest_summary = persisted_summary
        latest_version = persisted_summary.requirements_version
        latest_summary_index = index

    if latest_summary is None or latest_version is None or latest_summary_index is None:
        return RequirementsState()

    confirmed_version: str | None = None
    has_plan_after_confirmation = False
    for message in conversation[latest_summary_index + 1 :]:
        if message.role != "user":
            if _is_plan_proposal_message(message):
                has_plan_after_confirmation = True
            continue

        confirmation = content_free_confirmation(message)
        if confirmation is not None:
            # A confirmation names exactly one disclosure. Anything else is a
            # confirmation of something the user never saw.
            confirmed_version = (
                latest_version
                if confirmation.requirements_version == latest_version
                else None
            )
            continue

        # After a plan was proposed, preserve requirements unless the user
        # explicitly wants to restart discovery (mentions "ändra krav",
        # "change requirements", "börja om", "start over").
        if has_plan_after_confirmation and confirmed_version is not None:
            content = message.content if isinstance(message.content, str) else ""
            if not _is_requirements_invalidation(content.casefold()):
                continue  # Keep requirements confirmed for revision requests

        confirmed_version = None

    return RequirementsState(
        latest_summary=latest_summary,
        latest_version=latest_version,
        confirmed_version=confirmed_version,
    )


def latest_confirmed_requirements(
    conversation: list[ConversationMessage],
) -> RequirementsSummaryPayload | None:
    state = resolve_requirements_state(conversation)
    return state.latest_summary if state.confirmed else None


def render_confirmed_requirements_system_prompt_block(
    summary: RequirementsSummaryPayload,
) -> str:
    lines = ["## Bekräftade krav"]
    if relevant_summary := user_relevant_requirement_text(summary.summary):
        lines.extend(["", relevant_summary])
    lines.extend(["", "### Nyckelbeslut"])
    for decision in summary.key_decisions:
        lines.append(f"- {decision.topic}: {decision.decision}")

    lines.extend(
        [
            "",
            "### Indata",
        ]
    )
    if input_description := user_relevant_requirement_text(summary.input_description):
        lines.append(input_description)
    else:
        lines.append("-")
    lines.extend(["", "### Utdata"])
    if output_description := user_relevant_requirement_text(summary.output_description):
        lines.append(output_description)
    else:
        lines.append("-")

    manual_setup_notes = user_relevant_requirement_notes(summary.manual_setup_notes)
    if manual_setup_notes:
        lines.extend(["", "### Manuell uppsättning"])
        lines.extend(f"- {note}" for note in manual_setup_notes)

    lines.extend(
        [
            "",
            "Bygg vidare på dessa bekräftade krav. Om användaren ändrar något måste du först uppdatera kraven och få en ny bekräftelse innan du föreslår en plan.",
        ]
    )
    return "\n".join(lines)


def render_confirmed_requirements_proposal_prompt_block(
    summary: RequirementsSummaryPayload | None,
) -> str:
    if summary is None:
        return "- none"

    lines: list[str] = []
    for key, value in (
        ("summary", summary.summary),
        ("input_description", summary.input_description),
        ("output_description", summary.output_description),
    ):
        if relevant_value := user_relevant_requirement_text(value):
            lines.append(f"- {key}: {relevant_value}")

    if summary.key_decisions:
        lines.append("- key_decisions:")
        lines.extend(
            f"  - {decision.topic}: {decision.decision}"
            for decision in summary.key_decisions
        )

    relevant_assumptions = user_relevant_requirement_notes(summary.assumptions)
    if relevant_assumptions:
        lines.append("- assumptions:")
        lines.extend(f"  - {assumption}" for assumption in relevant_assumptions)

    return "\n".join(lines) if lines else "- none"


def _is_requirements_invalidation(text: str) -> bool:
    """Check if the user explicitly wants to restart/change requirements."""
    invalidation_phrases = (
        "ändra krav",
        "change requirements",
        "börja om",
        "start over",
        "nya krav",
        "new requirements",
        "restart",
        "starta om",
        "omformulera krav",
    )
    return any(phrase in text for phrase in invalidation_phrases)


def _is_plan_proposal_message(message: ConversationMessage) -> bool:
    return message.role == "assistant" and any(
        tool_call.name == PROPOSE_FLOW_TOOL_NAME
        for tool_call in tool_calls_from_message(message)
    )
