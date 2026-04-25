"""Tests for server-owned architecture commit finalization."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intric.flows.ai_builder.ai_builder_architecture_commit import (
    architecture_commit_hash,
    canonical_architecture_commit_payload,
    finalize_architecture_commit,
)
from intric.flows.ai_builder.planning_state import (
    AggregationIntent,
    ArchitectureCommitDraft,
    StepTriple,
)


def _draft(
    *,
    chosen_patterns: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    aggregation_intent: AggregationIntent = "linear",
) -> ArchitectureCommitDraft:
    return ArchitectureCommitDraft(
        tuples_chain=[
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=chosen_patterns or ["summarize_text"],
        required_capabilities=required_capabilities
        if required_capabilities is not None
        else ["input_text", "output_mode_pass_through"],
        aggregation_intent=aggregation_intent,
    )


def test_finalize_adds_server_owned_hash_and_timestamp() -> None:
    now = datetime(2026, 4, 24, 12, 30, tzinfo=timezone.utc)
    draft = _draft()

    commit = finalize_architecture_commit(draft, now=lambda: now)

    assert commit.architecture_hash == architecture_commit_hash(draft)
    assert commit.committed_at == now
    assert canonical_architecture_commit_payload(commit) == (
        canonical_architecture_commit_payload(draft)
    )


def test_hash_is_stable_for_unordered_semantic_sets() -> None:
    first = _draft(
        chosen_patterns=["summarize_text", "document_to_structured_report"],
        required_capabilities=["output_mode_pass_through", "input_text"],
    )
    second = _draft(
        chosen_patterns=["document_to_structured_report", "summarize_text"],
        required_capabilities=["input_text", "output_mode_pass_through"],
    )

    assert architecture_commit_hash(first) == architecture_commit_hash(second)


def test_hash_changes_when_aggregation_intent_changes() -> None:
    linear = _draft(aggregation_intent="linear")
    aggregate = _draft(aggregation_intent="aggregate")

    assert architecture_commit_hash(linear) != architecture_commit_hash(aggregate)


def test_finalize_normalizes_naive_clock_to_utc() -> None:
    naive = datetime(2026, 4, 24, 12, 30)

    commit = finalize_architecture_commit(_draft(), now=lambda: naive)

    assert commit.committed_at.tzinfo == timezone.utc


def test_architecture_commit_allows_one_compiler_chain_plus_semantic_patterns() -> None:
    draft = _draft(
        chosen_patterns=["multi_step_quality_chain", "form_field_runtime_inputs"]
    )

    assert draft.chosen_patterns == [
        "multi_step_quality_chain",
        "form_field_runtime_inputs",
    ]


def test_architecture_commit_rejects_multiple_compiler_chain_patterns() -> None:
    with pytest.raises(ValueError, match="at most one compiler-backed"):
        _draft(
            chosen_patterns=[
                "multi_step_quality_chain",
                "audio_to_artifact_report",
            ]
        )
