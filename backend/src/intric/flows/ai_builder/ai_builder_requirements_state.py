from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from intric.flows.ai_builder.ai_builder_models import (
    ConversationMessage,
    RequirementsSummaryPayload,
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
    canonical_payload = payload.model_copy(update={"requirements_version": None}, deep=True)
    serialized = json.dumps(
        canonical_payload.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def resolve_requirements_state(
    conversation: list[ConversationMessage],
) -> RequirementsState:
    latest_summary: RequirementsSummaryPayload | None = None
    latest_version: str | None = None
    latest_summary_index: int | None = None

    for index, message in enumerate(conversation):
        if message.role == "assistant" and isinstance(message.tool_calls, list):
            for tool_call in message.tool_calls:
                if not isinstance(tool_call, dict) or tool_call.get("name") != "confirm_requirements":
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
        if message.role != "tool" or metadata is None:
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
            and metadata.get("requirements_version") == latest_version
        ):
            confirmed_version = latest_version
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

    lines = [
        "## Bekräftade krav",
        "",
        summary.summary,
        "",
        "### Nyckelbeslut",
    ]
    for decision in summary.key_decisions:
        lines.append(f"- {decision.topic}: {decision.decision}")

    lines.extend(
        [
            "",
            "### Indata",
            summary.input_description,
            "",
            "### Utdata",
            summary.output_description,
        ]
    )

    if summary.manual_setup_notes:
        lines.extend(["", "### Manuell uppsättning"])
        lines.extend(f"- {note}" for note in summary.manual_setup_notes)

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
