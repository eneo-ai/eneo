"""Server-owned finalization for AI Builder architecture commits."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ArchitectureCommitDraft,
)


def canonical_architecture_commit_payload(
    commit: ArchitectureCommitDraft,
) -> dict[str, Any]:
    """Return the semantic commit payload used for hashing and comparison.

    `tuples_chain` order is significant because it defines the
    architecture envelope from primary input toward terminal output.
    It is not required to match the eventual implementation step count.
    `chosen_patterns` and `required_capabilities` are sets in practice,
    so they are sorted to make semantically identical drafts hash
    identically even when the model emits a different list order.
    """
    return {
        "tuples_chain": [
            triple.model_dump(mode="json") for triple in commit.tuples_chain
        ],
        "chosen_patterns": sorted(commit.chosen_patterns),
        "required_capabilities": sorted(commit.required_capabilities),
        "aggregation_intent": commit.aggregation_intent,
    }


def architecture_commit_hash(commit: ArchitectureCommitDraft) -> str:
    """Compute the deterministic semantic hash for an architecture draft."""
    serialized = json.dumps(
        canonical_architecture_commit_payload(commit),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def finalize_architecture_commit(
    draft: ArchitectureCommitDraft,
    *,
    now: Callable[[], datetime] | None = None,
) -> ArchitectureCommit:
    """Add server-owned metadata and return a persisted commit model."""
    timestamp = (now or _utc_now)()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    payload = canonical_architecture_commit_payload(draft)
    return ArchitectureCommit.model_validate(
        {
            **payload,
            "committed_at": timestamp,
            "architecture_hash": architecture_commit_hash(draft),
        }
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


__all__ = [
    "architecture_commit_hash",
    "canonical_architecture_commit_payload",
    "finalize_architecture_commit",
]
