"""Conversation-spec alignment invariants consulted by the quality critic.

Each `CriticInvariant` is a self-contained triplet of
`(id, description, evidence, remediation)`. The quality critic loops over
`CRITIC_INVARIANTS`, evaluates each `evidence` callable against a pre-built
`CriticContext`, and returns the `remediation` message for every invariant
that fires. This removes ad-hoc substring checks from the critic body —
each invariant owns its own evidence logic and Swedish prose.

Layering: this module imports AI Builder types (`FlowDraftSpecCore`,
`OutputIntentResolution`, `PlannerPatternSignals`). The Flow Capability
Manifest stays engine-truth-only and does not learn about conversation
signals; those live here with the rest of the AI Builder layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from intric.flows.ai_builder.ai_builder_framework_policy import (
    OutputIntentResolution,
)
from intric.flows.ai_builder.ai_builder_models import (
    FlowDraftSpecCore,
    OutputType,
)
from intric.flows.ai_builder.ai_builder_planner_pattern_signals import (
    PlannerPatternSignals,
)

if TYPE_CHECKING:
    from intric.flows.domain.flow import Flow


@dataclass(frozen=True, slots=True)
class CriticContext:
    """Pre-computed view of conversation + spec + flow used by every invariant.

    The critic builds the context once per call, then hands it to each
    `CriticInvariant.evidence` — invariants never re-parse the raw
    conversation.
    """

    spec: FlowDraftSpecCore
    flow: "Flow | None"
    answer_signals: dict[str, set[str]]
    text: str
    requirements_text: str
    signal_text: str
    planner_patterns: PlannerPatternSignals
    output_intent: OutputIntentResolution


CriticCheck = Callable[[CriticContext], bool]


@dataclass(frozen=True, slots=True)
class CriticInvariant:
    """Conversation-spec alignment invariant.

    `evidence(context)` returns True when the invariant is violated and the
    critic should surface `remediation` to the planner.
    """

    id: str
    description: str
    evidence: CriticCheck
    remediation: str


def _pdf_terminal_alignment_evidence(context: CriticContext) -> bool:
    if context.output_intent.terminal_output != "pdf_document":
        return False
    if not context.spec.steps:
        return False
    return context.spec.steps[-1].output_type != OutputType.PDF


_PDF_TERMINAL_OUTPUT_ALIGNMENT = CriticInvariant(
    id="pdf_terminal_output_alignment",
    description=(
        "When the user explicitly picks PDF as the final artefact, the terminal "
        "step must produce `output_type=PDF`."
    ),
    evidence=_pdf_terminal_alignment_evidence,
    remediation=(
        "Användaren har valt PDF som slutartefakt men sista steget producerar inte PDF. "
        "Justera slutstegets output_type så att det matchar användarens val."
    ),
)


CRITIC_INVARIANTS: tuple[CriticInvariant, ...] = (_PDF_TERMINAL_OUTPUT_ALIGNMENT,)


def render_critic_issues(context: CriticContext) -> list[str]:
    """Evaluate every invariant against `context` and collect the firing
    remediations in registration order.
    """
    return [inv.remediation for inv in CRITIC_INVARIANTS if inv.evidence(context)]
