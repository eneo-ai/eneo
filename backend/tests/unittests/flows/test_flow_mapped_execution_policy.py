from __future__ import annotations

import pytest

from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    apply_flow_mapped_execution_policy_patch,
    effective_mapped_cardinality,
    resolve_flow_mapped_execution_policy,
    validate_flow_mapped_execution_policy_object,
)
from eneo.main.exceptions import BadRequestException


def test_resolve_mapped_policy_has_no_numeric_default() -> None:
    assert resolve_flow_mapped_execution_policy(None) == FlowMappedExecutionPolicy(
        version=1,
        max_provider_calls_per_mapped_step=None,
        max_estimated_input_tokens_per_mapped_step=None,
    )


def test_resolve_mapped_policy_reads_both_configured_ceilings() -> None:
    policy = resolve_flow_mapped_execution_policy(
        {
            "mapped_execution": {
                "version": 1,
                "max_provider_calls_per_mapped_step": 7,
                "max_estimated_input_tokens_per_mapped_step": 120_000,
            }
        }
    )

    assert policy.max_provider_calls_per_mapped_step == 7
    assert policy.max_estimated_input_tokens_per_mapped_step == 120_000


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 0},
        {"version": 2},
        {"version": "1"},
        {"version": True},
        {"unknown": 1},
        {"max_provider_calls_per_mapped_step": True},
        {"max_provider_calls_per_mapped_step": 0},
        {"max_provider_calls_per_mapped_step": -1},
        {"max_provider_calls_per_mapped_step": 1.5},
        {"max_estimated_input_tokens_per_mapped_step": False},
        {"max_estimated_input_tokens_per_mapped_step": 0},
        {"max_estimated_input_tokens_per_mapped_step": "100"},
    ],
)
def test_validate_mapped_policy_fails_closed(payload: object) -> None:
    with pytest.raises(BadRequestException):
        validate_flow_mapped_execution_policy_object(payload)


def test_patch_preserves_omitted_fields_and_unrelated_settings() -> None:
    updated = apply_flow_mapped_execution_policy_patch(
        {
            "input_limits": {"max_files_per_run": 10},
            "mapped_execution": {
                "version": 1,
                "max_provider_calls_per_mapped_step": 5,
                "max_estimated_input_tokens_per_mapped_step": 100_000,
            },
        },
        max_provider_calls_per_mapped_step=3,
    )

    assert updated == {
        "input_limits": {"max_files_per_run": 10},
        "mapped_execution": {
            "version": 1,
            "max_provider_calls_per_mapped_step": 3,
            "max_estimated_input_tokens_per_mapped_step": 100_000,
        },
    }


def test_patch_explicit_removal_deletes_empty_policy_envelope() -> None:
    updated = apply_flow_mapped_execution_policy_patch(
        {
            "input_limits": {"max_files_per_run": 10},
            "mapped_execution": {
                "version": 1,
                "max_provider_calls_per_mapped_step": 5,
            },
        },
        remove_keys={"max_provider_calls_per_mapped_step"},
    )

    assert updated == {"input_limits": {"max_files_per_run": 10}}


def test_effective_mapped_cardinality_uses_every_present_ceiling() -> None:
    assert (
        effective_mapped_cardinality(
            published_max=8,
            mapped_policy=FlowMappedExecutionPolicy(
                version=1,
                max_provider_calls_per_mapped_step=6,
                max_estimated_input_tokens_per_mapped_step=None,
            ),
            input_max_files=4,
        )
        == 4
    )
    assert (
        effective_mapped_cardinality(
            published_max=3,
            mapped_policy=FlowMappedExecutionPolicy(
                version=1,
                max_provider_calls_per_mapped_step=10,
                max_estimated_input_tokens_per_mapped_step=None,
            ),
        )
        == 3
    )


def test_effective_mapped_cardinality_requires_published_bound() -> None:
    with pytest.raises(BadRequestException):
        effective_mapped_cardinality(
            published_max=None,
            mapped_policy=resolve_flow_mapped_execution_policy(None),
        )
