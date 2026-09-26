"""Deterministic preflight over a parsed AI-builder draft.

Evaluates the existing critic once and exposes the resulting issues as a typed
verdict the proposal pipeline acts on before persisting. Semantic issues are
retryable quality feedback; architecture issues are materialization-blocking
only for mechanics the critic still owns, mostly edit-mode protection around an
existing flow.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from eneo.flows.ai_builder.ai_builder_critic_invariants import (
    evaluate_critic_invariants,
)

if TYPE_CHECKING:
    from eneo.flows.ai_builder.ai_builder_critic_invariants import (
        CriticContext,
        CriticIssue,
    )


@dataclass(frozen=True, slots=True)
class PreflightResult:
    """Typed verdict over a draft's critic issues, evaluated once.

    ``issues`` is the single source of truth; every other accessor is derived
    so the verdict cannot drift out of sync with the issues it came from.
    """

    issues: tuple[CriticIssue, ...]

    @property
    def semantic_issues(self) -> tuple[CriticIssue, ...]:
        return tuple(issue for issue in self.issues if issue.kind == "semantic")


def run_draft_preflight(context: CriticContext) -> PreflightResult:
    """Evaluate the critic once and wrap its issues as a typed preflight verdict."""
    return PreflightResult(issues=evaluate_critic_invariants(context))
