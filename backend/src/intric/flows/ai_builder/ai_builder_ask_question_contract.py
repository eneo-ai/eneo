"""Server-owned contract for planner-authored `ask_question` actions.

The planner may author the user-facing prompt text, but it must not
invent identifier vocabulary. Question identifiers are architectural
slot names owned by the server/catalog; narrower domain concepts belong
inside `payload.prompt`, not in `payload.question_id` or
`payload.slot_name`.
"""

from __future__ import annotations

from collections.abc import Iterable

from intric.flows.ai_builder.ai_builder_slot_vocabulary import (
    KNOWN_REQUIREMENT_SLOT_NAMES,
)


def canonical_ask_question_targets() -> tuple[str, ...]:
    """Return the full v2 `ask_question` identifier vocabulary."""
    return tuple(sorted(KNOWN_REQUIREMENT_SLOT_NAMES))


def allowed_ask_question_targets(
    *,
    unresolved_architectural_choices: Iterable[str],
    required_slot_names: Iterable[str],
) -> tuple[str, ...]:
    """Return the per-turn target set the evaluator accepts."""
    return tuple(
        sorted(set(unresolved_architectural_choices) | set(required_slot_names))
    )


def format_ask_question_targets(targets: Iterable[str]) -> str:
    """Render target IDs for diagnostics."""
    ordered = tuple(dict.fromkeys(targets))
    if not ordered:
        return "(none)"
    return ", ".join(f"`{target}`" for target in ordered)


__all__ = [
    "allowed_ask_question_targets",
    "canonical_ask_question_targets",
    "format_ask_question_targets",
]
