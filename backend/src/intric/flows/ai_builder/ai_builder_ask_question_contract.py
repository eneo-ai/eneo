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
    """Render target IDs for prompts and diagnostics."""
    ordered = tuple(sorted(set(targets)))
    if not ordered:
        return "(none)"
    return ", ".join(f"`{target}`" for target in ordered)


def render_ask_question_vocabulary_block() -> str:
    """Render the LLM-facing identifier contract for `ask_question`."""
    return (
        "## Ask-question vocabulary\n\n"
        "When `planner_action.kind` is `ask_question`, "
        "`payload.question_id` and `payload.slot_name` are server-owned "
        "identifiers. Emit both as one of these canonical slot IDs:\n\n"
        f"{_canonical_target_bullets()}\n\n"
        "Do not invent narrower domain-specific IDs. If the user needs a "
        "specific case type, department, role, language, date, reference "
        "number, or similar runtime value, keep that specificity in "
        "`payload.prompt` and use `runtime_metadata_fields` as the "
        "identifier target."
    )


def _canonical_target_bullets() -> str:
    return "\n".join(f"- `{target}`" for target in canonical_ask_question_targets())


__all__ = [
    "allowed_ask_question_targets",
    "canonical_ask_question_targets",
    "format_ask_question_targets",
    "render_ask_question_vocabulary_block",
]
