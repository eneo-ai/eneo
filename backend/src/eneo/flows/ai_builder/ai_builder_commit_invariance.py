"""Semantic architecture-commit invariants for AI Builder authoring.

The architecture commit is the pinned contract between the planner's
discovery phase and downstream persistence. Boundaries that transform
planner state after the commit lands can use this helper to fail loudly when
the semantic architecture drifts outside an explicit revision path.

LLM-facing draft preservation is structural: the model may re-emit the
semantic body, but server-owned fields (`architecture_hash`, `committed_at`)
are never model-authored and are therefore ignored for draft-vs-pinned
comparison.

Callers that need a structured rejection rather than an exception catch
`CommitDriftError` and translate it at their own boundary. The helper
itself stays exception-based so it fails loud by default on every
unchecked call site.
"""

from __future__ import annotations

from eneo.flows.ai_builder.ai_builder_architecture_commit import (
    canonical_architecture_commit_payload,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ArchitectureCommitDraft,
)


class CommitDriftError(ValueError):
    """The architecture commit was mutated or dropped after it was pinned."""


def assert_architecture_commit_draft_matches_pinned(
    *,
    before: ArchitectureCommit | None,
    after: ArchitectureCommitDraft | None,
) -> None:
    """Raise when an LLM-facing commit draft drifts from a pinned commit.

    The helper compares only semantic structure because the LLM-facing draft
    has no server-owned `architecture_hash` or `committed_at` fields.
    """
    if before is None or after is None:
        return
    if not architecture_commit_draft_matches_pinned(before=before, after=after):
        raise CommitDriftError(
            "architecture_commit draft mutated the pinned committed "
            "architecture (tuples_chain / chosen_patterns / "
            "required_capabilities). The LLM may omit architecture_commit "
            "after commit, but must not re-author a different semantic body"
        )


def architecture_commit_draft_matches_pinned(
    *,
    before: ArchitectureCommit | None,
    after: ArchitectureCommitDraft | None,
) -> bool:
    if before is None or after is None:
        return True
    return canonical_architecture_commit_payload(before) == (
        canonical_architecture_commit_payload(after)
    )


__all__ = [
    "architecture_commit_draft_matches_pinned",
    "CommitDriftError",
    "assert_architecture_commit_draft_matches_pinned",
]
