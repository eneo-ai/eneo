"""Contract tests for AI Builder architecture commit draft invariants.

The helper provides one source of truth for comparing a model-facing
`ArchitectureCommitDraft` with the pinned server-owned `ArchitectureCommit`.
The model never authors `architecture_hash` or `committed_at`, so comparison
uses only the semantic body.

Raises `CommitDriftError` (a `ValueError` subclass) so callers can
catch drift specifically. The exception message names the drifted
field(s) for telemetry and debugging.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from eneo.flows.ai_builder.ai_builder_commit_invariance import (
    CommitDriftError,
    architecture_commit_draft_matches_pinned,
    assert_architecture_commit_draft_matches_pinned,
)
from eneo.flows.ai_builder.planning_state import (
    ArchitectureCommit,
    ArchitectureCommitDraft,
    StepTriple,
)


def _make_commit(
    *,
    tuples_chain: list[StepTriple] | None = None,
    chosen_patterns: list[str] | None = None,
    required_capabilities: list[str] | None = None,
) -> ArchitectureCommit:
    return ArchitectureCommit(
        tuples_chain=tuples_chain
        if tuples_chain is not None
        else [
            StepTriple(
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            )
        ],
        chosen_patterns=chosen_patterns
        if chosen_patterns is not None
        else ["summarize_text"],
        required_capabilities=required_capabilities
        if required_capabilities is not None
        else ["input_text", "output_mode_pass_through"],
        committed_at=datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash="a" * 64,
    )


class TestDraftPreservation:
    def test_matching_semantic_draft_returns_true(self) -> None:
        prior = _make_commit(
            required_capabilities=["output_mode_pass_through", "input_text"],
            chosen_patterns=["summarize_text"],
        )
        draft = ArchitectureCommitDraft(
            tuples_chain=prior.tuples_chain,
            chosen_patterns=["summarize_text"],
            required_capabilities=["input_text", "output_mode_pass_through"],
        )

        assert architecture_commit_draft_matches_pinned(
            before=prior,
            after=draft,
        )

    def test_different_semantic_draft_returns_false(self) -> None:
        prior = _make_commit()
        draft = ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="text",
                    output_type="json",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=prior.chosen_patterns,
            required_capabilities=prior.required_capabilities,
        )

        assert not architecture_commit_draft_matches_pinned(
            before=prior,
            after=draft,
        )

    def test_missing_prior_or_draft_returns_true(self) -> None:
        prior = _make_commit()

        assert architecture_commit_draft_matches_pinned(before=None, after=None)
        assert architecture_commit_draft_matches_pinned(before=prior, after=None)

    def test_matching_semantic_draft_preserves_pinned_commit(self) -> None:
        prior = _make_commit(
            required_capabilities=["output_mode_pass_through", "input_text"],
            chosen_patterns=["summarize_text"],
        )
        draft = ArchitectureCommitDraft(
            tuples_chain=prior.tuples_chain,
            chosen_patterns=["summarize_text"],
            required_capabilities=["input_text", "output_mode_pass_through"],
        )

        assert_architecture_commit_draft_matches_pinned(before=prior, after=draft)

    def test_draft_omission_is_allowed_for_preservation_by_absence(self) -> None:
        prior = _make_commit()
        assert_architecture_commit_draft_matches_pinned(before=prior, after=None)

    def test_different_semantic_draft_raises(self) -> None:
        prior = _make_commit()
        draft = ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="text",
                    output_type="json",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=prior.chosen_patterns,
            required_capabilities=prior.required_capabilities,
        )

        with pytest.raises(CommitDriftError) as excinfo:
            assert_architecture_commit_draft_matches_pinned(before=prior, after=draft)

        assert "semantic body" in str(excinfo.value)

    def test_commit_drift_error_is_value_error(self) -> None:
        prior = _make_commit()
        draft = ArchitectureCommitDraft(
            tuples_chain=[
                StepTriple(
                    input_type="text",
                    output_type="json",
                    output_mode="pass_through",
                )
            ],
            chosen_patterns=prior.chosen_patterns,
            required_capabilities=prior.required_capabilities,
        )

        with pytest.raises(ValueError):
            assert_architecture_commit_draft_matches_pinned(before=prior, after=draft)


class TestPublicSurface:
    def test_expected_symbols_exported(self) -> None:
        from eneo.flows.ai_builder import ai_builder_commit_invariance as module

        for symbol in (
            "architecture_commit_draft_matches_pinned",
            "assert_architecture_commit_draft_matches_pinned",
            "CommitDriftError",
        ):
            assert hasattr(module, symbol), (
                f"{symbol} must be exported from ai_builder_commit_invariance"
            )
