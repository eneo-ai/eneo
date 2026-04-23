"""Commit-preservation invariant used across the orchestrator.

The architecture commit is the pinned contract between the planner's
discovery phase and downstream persistence. Any code that transforms a
planner response after the commit lands — the repair helper, the
post-commit invariance check in the dispatcher, the materialization
bridge before it writes a draft flow — must verify the transform did
not silently drift the commit.

`architecture_hash` equality alone is NOT sufficient. The planner
supplies the hash as part of its JSON product; the server never
recomputes it against the commit body. A matching hash on a divergent
body (`tuples_chain` / `chosen_patterns` / `required_capabilities` /
`committed_at`) is hash forgery, not preservation. The enforceable
invariant is full canonical-form equality via `model_dump(mode="json")`.

Callers that need a structured rejection rather than an exception
(e.g. the repair helper, which surfaces drift as a `RejectionReason`
with code `repair_attempted_commit_drift`) catch `CommitDriftError`
and translate. The helper itself stays exception-based so it fails
loud by default on every unchecked call site.
"""

from __future__ import annotations

from intric.flows.ai_builder.planning_state import ArchitectureCommit


class CommitDriftError(ValueError):
    """The architecture commit was mutated or dropped after it was pinned."""


def assert_architecture_commit_unchanged(
    *,
    before: ArchitectureCommit | None,
    after: ArchitectureCommit | None,
) -> None:
    """Raise `CommitDriftError` if `after` does not preserve `before`.

    Transition matrix:
      - `before=None, after=any`: no raise (initial-commit path).
      - `before=set, after=None`: raise (commit silently dropped).
      - `before=set, after` with different `architecture_hash`: raise.
      - `before=set, after` with matching hash but divergent body
        (`tuples_chain` / `chosen_patterns` / `required_capabilities` /
        `committed_at`): raise — the server does not rebind the
        planner-supplied hash to the body, so a matching hash on a
        different body is forgery, not preservation.
      - `before=set, after` byte-identical: no raise.
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
            "required_capabilities / committed_at). The server does not "
            "rebind the planner-supplied hash; a matching hash on a "
            "different body is drift, not preservation"
        )


__all__ = [
    "CommitDriftError",
    "assert_architecture_commit_unchanged",
]
