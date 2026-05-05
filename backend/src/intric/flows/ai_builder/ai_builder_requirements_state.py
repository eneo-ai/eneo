from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    RequirementsSummaryPayload,
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


def build_requirements_version(payload: RequirementsSummaryPayload) -> str:
    canonical_payload = payload.model_copy(
        update={"requirements_version": None}, deep=True
    )
    serialized = json.dumps(
        canonical_payload.model_dump(mode="json"),
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
        if message.role == "assistant" and isinstance(message.tool_calls, list):
            for tool_call in message.tool_calls:
                if tool_call.get("name") != "confirm_requirements":
                    continue
                arguments = tool_call.get("arguments")
                if not isinstance(arguments, dict):
                    continue
                try:
                    payload = RequirementsSummaryPayload.model_validate(arguments)
                except Exception:
                    continue
                latest_summary = payload
                latest_version = build_requirements_version(payload)
                latest_summary_index = index

        metadata = message.metadata if isinstance(message.metadata, dict) else None
        if metadata is None or message.role not in ("tool", "assistant"):
            continue
        summary_data = metadata.get("requirements_summary")
        version = metadata.get("requirements_version")
        if not isinstance(summary_data, dict):
            continue
        try:
            latest_summary = RequirementsSummaryPayload.model_validate(summary_data)
        except Exception:
            continue
        computed_version = build_requirements_version(latest_summary)
        if isinstance(version, str) and version != computed_version:
            continue
        latest_version = computed_version
        latest_summary_index = index

    if latest_summary is None or latest_version is None or latest_summary_index is None:
        return RequirementsState()

    confirmed_version: str | None = None
    has_plan_after_confirmation = False
    for message in conversation[latest_summary_index + 1 :]:
        if message.role != "user":
            # Track if a plan was proposed after confirmation (tool message
            # from a stored plan submission). This means any subsequent user message is
            # a revision request, not a requirements change.
            if message.role == "tool" and isinstance(message.content, str):
                if "Plan:" in message.content:
                    has_plan_after_confirmation = True
            continue

        metadata = message.metadata if isinstance(message.metadata, dict) else None
        if (
            isinstance(metadata, dict)
            and metadata.get("requirements_confirmed") is True
        ):
            confirmed_metadata_version = metadata.get("requirements_version")
            # Compatibility bridge for draft sessions persisted before
            # requirements_version was added. Delete after all pre-2026-05-03
            # AI Builder draft sessions have expired or been migrated.
            if confirmed_metadata_version in (None, latest_version):
                confirmed_version = latest_version
                continue
            confirmed_version = None
            continue

        # After a plan was proposed, preserve requirements unless the user
        # explicitly wants to restart discovery (mentions "ändra krav",
        # "change requirements", "börja om", "start over").
        if has_plan_after_confirmation and confirmed_version is not None:
            content = message.content if isinstance(message.content, str) else ""
            lowered = content.casefold()
            if not _is_requirements_invalidation(lowered):
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


def build_confirmed_requirements_prompt_block(
    conversation: list[ConversationMessage],
) -> str | None:
    summary = latest_confirmed_requirements(conversation)
    if summary is None:
        return None

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
