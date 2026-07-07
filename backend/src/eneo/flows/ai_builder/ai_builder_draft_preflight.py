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
    def passed(self) -> bool:
        return not self.issues

    @property
    def architecture_issues(self) -> tuple[CriticIssue, ...]:
        return tuple(issue for issue in self.issues if issue.kind == "architecture")

    @property
    def semantic_issues(self) -> tuple[CriticIssue, ...]:
        return tuple(issue for issue in self.issues if issue.kind == "semantic")

    @property
    def blocks_materialization(self) -> bool:
        return bool(self.architecture_issues)

    @property
    def can_retry(self) -> bool:
        """A draft with only semantic issues can be re-attempted by the planner;
        an architecture violation is handled through the hard error path."""
        return not self.architecture_issues

    @property
    def critic_invariant_ids(self) -> tuple[str, ...]:
        return tuple(issue.id for issue in self.issues)

    @property
    def critic_invariant_id(self) -> str | None:
        return self.critic_invariant_ids[0] if self.critic_invariant_ids else None


def run_draft_preflight(context: CriticContext) -> PreflightResult:
    """Evaluate the critic once and wrap its issues as a typed preflight verdict."""
    return PreflightResult(issues=evaluate_critic_invariants(context))
