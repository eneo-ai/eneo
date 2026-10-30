from __future__ import annotations

import pytest

from eneo.flows.domain.rag_evidence_policy import (
    DEFAULT_MAX_RECORDED_PASSAGE_BYTES,
    DEFAULT_MAX_RECORDED_PASSAGE_BYTES_PER_STEP,
    DEFAULT_MAX_RECORDED_PASSAGES_PER_SOURCE,
    DEFAULT_MAX_SOURCES_WITH_RECORDED_PASSAGES,
    FlowRagEvidencePolicy,
    apply_flow_rag_evidence_policy_patch,
    resolve_flow_rag_evidence_policy,
    validate_flow_rag_evidence_policy_object,
)
from eneo.main.exceptions import BadRequestException


def test_unset_policy_resolves_to_the_safe_defaults() -> None:
    assert resolve_flow_rag_evidence_policy(None) == FlowRagEvidencePolicy(
        version=1,
        max_sources_with_recorded_passages=DEFAULT_MAX_SOURCES_WITH_RECORDED_PASSAGES,
        max_recorded_passages_per_source=DEFAULT_MAX_RECORDED_PASSAGES_PER_SOURCE,
        max_recorded_passage_bytes=DEFAULT_MAX_RECORDED_PASSAGE_BYTES,
        max_recorded_passage_bytes_per_step=(
            DEFAULT_MAX_RECORDED_PASSAGE_BYTES_PER_STEP
        ),
    )


def test_configured_policy_replaces_only_the_fields_it_sets() -> None:
    policy = resolve_flow_rag_evidence_policy(
        {
            "rag_evidence": {
                "version": 1,
                "max_sources_with_recorded_passages": 60,
                "max_recorded_passage_bytes": 8192,
            }
        }
    )

    assert policy.max_sources_with_recorded_passages == 60
    assert policy.max_recorded_passage_bytes == 8192
    assert policy.max_recorded_passages_per_source == (
        DEFAULT_MAX_RECORDED_PASSAGES_PER_SOURCE
    )


@pytest.mark.parametrize(
    "stored",
    [
        None,
        {},
        {"rag_evidence": None},
        {"rag_evidence": "not-an-object"},
        {"rag_evidence": {"version": 2}},
        {"rag_evidence": {"max_recorded_passage_bytes": 0}},
        {"rag_evidence": {"max_recorded_passage_bytes": 10_000_000}},
        {"rag_evidence": {"max_sources_with_recorded_passages": True}},
        {"rag_evidence": {"unknown_field": 1}},
    ],
)
def test_unusable_stored_policy_falls_back_to_the_defaults(
    stored: dict[str, object] | None,
) -> None:
    assert resolve_flow_rag_evidence_policy(stored) == FlowRagEvidencePolicy()


@pytest.mark.parametrize(
    "payload",
    [
        "not-an-object",
        {"version": 0},
        {"version": 2},
        {"version": "1"},
        {"version": True},
        {"unknown": 1},
        {"max_sources_with_recorded_passages": 0},
        {"max_sources_with_recorded_passages": -1},
        {"max_sources_with_recorded_passages": 501},
        {"max_recorded_passages_per_source": 1.5},
        {"max_recorded_passages_per_source": 51},
        {"max_recorded_passage_bytes": "4096"},
        {"max_recorded_passage_bytes": 65_537},
        {"max_recorded_passage_bytes_per_step": False},
        {"max_recorded_passage_bytes_per_step": 4_194_305},
    ],
)
def test_validate_policy_fails_closed(payload: object) -> None:
    with pytest.raises(BadRequestException):
        validate_flow_rag_evidence_policy_object(payload)


def test_patch_preserves_omitted_fields_and_unrelated_settings() -> None:
    updated = apply_flow_rag_evidence_policy_patch(
        {
            "input_limits": {"max_files_per_run": 10},
            "rag_evidence": {
                "version": 1,
                "max_sources_with_recorded_passages": 30,
                "max_recorded_passage_bytes": 2048,
            },
        },
        max_recorded_passage_bytes=8192,
    )

    assert updated == {
        "input_limits": {"max_files_per_run": 10},
        "rag_evidence": {
            "version": 1,
            "max_sources_with_recorded_passages": 30,
            "max_recorded_passage_bytes": 8192,
        },
    }


def test_patch_rejects_a_value_above_its_ceiling() -> None:
    with pytest.raises(BadRequestException):
        apply_flow_rag_evidence_policy_patch(
            None,
            max_recorded_passage_bytes=1_000_000,
        )


def test_patch_removal_deletes_the_empty_policy_envelope() -> None:
    updated = apply_flow_rag_evidence_policy_patch(
        {
            "input_limits": {"max_files_per_run": 10},
            "rag_evidence": {
                "version": 1,
                "max_sources_with_recorded_passages": 30,
            },
        },
        remove_keys={"max_sources_with_recorded_passages"},
    )

    assert updated == {"input_limits": {"max_files_per_run": 10}}


def test_patch_rejects_an_unknown_removal_key() -> None:
    with pytest.raises(BadRequestException):
        apply_flow_rag_evidence_policy_patch(None, remove_keys={"version"})
