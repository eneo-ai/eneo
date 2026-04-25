"""Commit-preservation invariant used across the orchestrator.

The architecture commit is the pinned contract between the planner's
discovery phase and downstream persistence. Any code that transforms a
planner response after the commit lands — the repair helper, the
post-commit invariance check in the dispatcher, the materialization
bridge before it writes a draft flow — must verify the transform did
not silently drift the commit.

Persisted-commit preservation uses full canonical-form equality via
`model_dump(mode="json")`. LLM-facing draft preservation is structural:
the model may re-emit the semantic body, but server-owned fields
(`architecture_hash`, `committed_at`) are never model-authored and are
therefore ignored for draft-vs-pinned comparison.

Callers that need a structured rejection rather than an exception
(e.g. the repair helper, which surfaces drift as a `RejectionReason`
with code `repair_attempted_commit_drift`) catch `CommitDriftError`
and translate. The helper itself stays exception-based so it fails
loud by default on every unchecked call site.
"""

from __future__ import annotations

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    canonical_architecture_commit_payload,
)
from intric.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ArchitectureCommitDraft,
)


class CommitDriftError(ValueError):
    """The architecture commit was mutated or dropped after it was pinned."""


def assert_architecture_commit_unchanged(
    *,
    before: ArchitectureCommit | None,
    after: ArchitectureCommit | None,
) -> None:
    """Raise `CommitDriftError` if `after` does not preserve `before`.

    Transition matrix (atomic — callers compose policy on top):
      - `before=None, after=any`: no raise (initial-commit path).
      - `before=set, after=None`: raise (commit silently dropped).
      - `before=set, after` with different `architecture_hash`: raise.
      - `before=set, after` with matching hash but divergent body
        (`tuples_chain` / `chosen_patterns` / `required_capabilities` /
        `committed_at`): raise — a persisted commit with matching hash
        but divergent body is corrupt state, not preservation.
      - `before=set, after` byte-identical: no raise.

    Caller composition: the evaluator's `_check_commit_preservation`
    and the repair helper's `_detect_commit_drift` implement
    preservation-by-absence on top of this strict contract — they
    short-circuit on `after is None` before invoking this helper
    because the planner-protocol teaches the model to populate
    `planning_state_delta.architecture_commit` only on
    `commit_architecture` turns. The `after=None` raise path stays
    in the helper as a defensive default for any future caller that
    needs strict preservation (so forgetting to short-circuit fails
    loud rather than silently accepting a dropped commit).
    """
    if before is None:
        return
    if after is None:
        raise CommitDriftError(
            "architecture_commit was dropped; the committed architecture is "
            "pinned and must be preserved "
            f"(prior architecture_hash={before.architecture_hash})"
        )
    if after.architecture_hash != before.architecture_hash:
        raise CommitDriftError(
            "architecture_hash changed from "
            f"{before.architecture_hash} to {after.architecture_hash}; "
            "the committed architecture is pinned and must be preserved"
        )
    if before.model_dump(mode="json") != after.model_dump(mode="json"):
        raise CommitDriftError(
            f"architecture_hash={before.architecture_hash} was preserved but "
            "the commit body was mutated (tuples_chain / chosen_patterns / "
            "required_capabilities / committed_at). A matching hash on a "
            "different persisted body is corrupt state, not preservation"
        )


def assert_architecture_commit_draft_matches_pinned(
    *,
    before: ArchitectureCommit | None,
    after: ArchitectureCommitDraft | None,
) -> None:
    """Raise when an LLM-facing commit draft drifts from a pinned commit.

    Unlike `assert_architecture_commit_unchanged`, this helper compares
    only semantic structure because the LLM-facing draft has no
    server-owned `architecture_hash` or `committed_at` fields.
    """
    if before is None or after is None:
        return
    if canonical_architecture_commit_payload(before) != (
        canonical_architecture_commit_payload(after)
    ):
        raise CommitDriftError(
            "architecture_commit draft mutated the pinned committed "
            "architecture (tuples_chain / chosen_patterns / "
            "required_capabilities). The LLM may omit architecture_commit "
            "after commit, but must not re-author a different semantic body"
        )


__all__ = [
    "CommitDriftError",
    "assert_architecture_commit_draft_matches_pinned",
    "assert_architecture_commit_unchanged",
]
