"""Contract tests for `assert_architecture_commit_unchanged`.

The helper is extracted from the repair helper's inline drift detector
so multiple call sites — repair, dispatcher post-commit check, and the
materialization bridge — share one source of truth for "is this the
same commit".

Enforced invariants (five-state transition matrix):

- `prior=None, after=None` → no raise (nothing to preserve).
- `prior=None, after=set` → no raise (initial-commit path).
- `prior=set, after=None` → raises (commit silently dropped).
- `prior=set, after` with different `architecture_hash` → raises.
- `prior=set, after` byte-identical → no raise.

The critical subtlety: `architecture_hash` equality alone is
insufficient. The planner supplies the hash; the server does not
recompute it. A matching hash on a divergent body
(`tuples_chain` / `chosen_patterns` / `required_capabilities` /
`committed_at`) is hash forgery, not preservation. The helper
compares full canonical `model_dump(mode="json")` output after the
hash check.

Raises `CommitDriftError` (a `ValueError` subclass) so callers can
catch drift specifically. The exception message names the drifted
field(s) for telemetry and debugging.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from intric.flows.ai_builder.ai_builder_commit_invariance import (
    CommitDriftError,
    assert_architecture_commit_unchanged,
)
from intric.flows.ai_builder.planning_state import ArchitectureCommit, StepTriple


def _make_commit(
    *,
    architecture_hash: str = "a" * 64,
    tuples_chain: list[StepTriple] | None = None,
    chosen_patterns: list[str] | None = None,
    required_capabilities: list[str] | None = None,
    committed_at: datetime | None = None,
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
        committed_at=committed_at
        if committed_at is not None
        else datetime(2026, 4, 23, tzinfo=timezone.utc),
        architecture_hash=architecture_hash,
    )


class TestNoDrift:
    def test_both_none_does_not_raise(self) -> None:
        assert_architecture_commit_unchanged(before=None, after=None)

    def test_prior_none_after_set_does_not_raise(self) -> None:
        after = _make_commit()
        assert_architecture_commit_unchanged(before=None, after=after)

    def test_byte_identical_commits_do_not_raise(self) -> None:
        commit = _make_commit()
        same_commit = _make_commit()
        assert_architecture_commit_unchanged(before=commit, after=same_commit)


class TestDrift:
    def test_dropped_commit_after_prior_raises(self) -> None:
        prior = _make_commit(architecture_hash="a" * 64)
        with pytest.raises(CommitDriftError) as excinfo:
            assert_architecture_commit_unchanged(before=prior, after=None)
        assert "dropped" in str(excinfo.value).lower()
        assert "a" * 64 in str(excinfo.value)

    def test_changed_hash_raises(self) -> None:
        prior = _make_commit(architecture_hash="a" * 64)
        after = _make_commit(architecture_hash="b" * 64)
        with pytest.raises(CommitDriftError) as excinfo:
            assert_architecture_commit_unchanged(before=prior, after=after)
        message = str(excinfo.value).lower()
        assert "architecture_hash" in message
        assert "a" * 64 in str(excinfo.value)
        assert "b" * 64 in str(excinfo.value)

    def test_matching_hash_with_mutated_tuples_chain_raises(self) -> None:
        """Hash forgery: planner kept the hash but changed the chain."""
        prior = _make_commit(architecture_hash="c" * 64)
        after = _make_commit(
            architecture_hash="c" * 64,
            tuples_chain=[
                StepTriple(
                    input_type="document",
                    output_type="json",
                    output_mode="template_fill",
                )
            ],
        )
        with pytest.raises(CommitDriftError) as excinfo:
            assert_architecture_commit_unchanged(before=prior, after=after)
        message = str(excinfo.value).lower()
        assert "mutated" in message or "body" in message
        assert "c" * 64 in str(excinfo.value)

    def test_matching_hash_with_mutated_chosen_patterns_raises(self) -> None:
        prior = _make_commit(architecture_hash="d" * 64)
        after = _make_commit(
            architecture_hash="d" * 64,
            chosen_patterns=["document_to_structured_report"],
        )
        with pytest.raises(CommitDriftError):
            assert_architecture_commit_unchanged(before=prior, after=after)

    def test_matching_hash_with_mutated_required_capabilities_raises(self) -> None:
        prior = _make_commit(architecture_hash="e" * 64)
        after = _make_commit(
            architecture_hash="e" * 64,
            required_capabilities=["input_document", "output_mode_structured"],
        )
        with pytest.raises(CommitDriftError):
            assert_architecture_commit_unchanged(before=prior, after=after)

    def test_matching_hash_with_mutated_committed_at_raises(self) -> None:
        prior = _make_commit(architecture_hash="f" * 64)
        after = _make_commit(
            architecture_hash="f" * 64,
            committed_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        )
        with pytest.raises(CommitDriftError):
            assert_architecture_commit_unchanged(before=prior, after=after)


class TestExceptionType:
    def test_commit_drift_error_is_value_error(self) -> None:
        """Callers that want a broad catch can still use ValueError."""
        prior = _make_commit(architecture_hash="a" * 64)
        with pytest.raises(ValueError):
            assert_architecture_commit_unchanged(before=prior, after=None)


class TestPublicSurface:
    def test_expected_symbols_exported(self) -> None:
        from intric.flows.ai_builder import ai_builder_commit_invariance as module

        for symbol in ("assert_architecture_commit_unchanged", "CommitDriftError"):
            assert hasattr(module, symbol), (
                f"{symbol} must be exported from ai_builder_commit_invariance"
            )
