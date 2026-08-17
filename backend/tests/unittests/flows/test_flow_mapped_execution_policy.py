from __future__ import annotations

import pytest

from eneo.flows.domain.mapped_execution_policy import (
    FlowMappedExecutionPolicy,
    apply_flow_mapped_execution_policy_patch,
    effective_mapped_cardinality,
    max_mapped_items_per_step,
    resolve_flow_mapped_execution_policy,
    validate_flow_mapped_execution_policy_object,
)
from eneo.main.exceptions import BadRequestException


def test_resolve_mapped_policy_without_deployment_default_is_unset() -> None:
    assert resolve_flow_mapped_execution_policy(
        None, default_max_provider_calls=None
    ) == FlowMappedExecutionPolicy(
        version=1,
        max_provider_calls_per_mapped_step=None,
        max_estimated_input_tokens_per_mapped_step=None,
    )


def test_resolver_owns_the_deployment_default_for_every_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Callers that pass no default (Builder context, worker runtime) must get
    the configured deployment fallback from the resolver itself."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        "eneo.flows.domain.mapped_execution_policy.get_settings",
        lambda: SimpleNamespace(flow_mapped_step_max_provider_calls_default=42),
    )

    policy = resolve_flow_mapped_execution_policy(None)

    assert policy.max_provider_calls_per_mapped_step == 42


def test_max_mapped_items_reserves_the_fallback_call() -> None:
    def policy(calls: int | None) -> FlowMappedExecutionPolicy:
        return FlowMappedExecutionPolicy(max_provider_calls_per_mapped_step=calls)

    assert max_mapped_items_per_step(policy(None)) is None
    # Enabled ceilings are validated to be >= 2, so the item bound is >= 1.
    assert max_mapped_items_per_step(policy(2)) == 1
    assert max_mapped_items_per_step(policy(100)) == 99


@pytest.mark.parametrize(
    "envelope",
    [None, "corrupt", 7, ["mapped"], {"version": 99}, {"unknown": 1}],
)
def test_resolve_corrupt_envelope_fails_closed(envelope: object) -> None:
    policy = resolve_flow_mapped_execution_policy(
        {"mapped_execution": envelope},
        default_max_provider_calls=100,
    )

    assert policy.max_provider_calls_per_mapped_step is None
    assert policy.max_estimated_input_tokens_per_mapped_step is None


def test_proposed_item_ceiling_is_never_rejected_solely_by_the_fallback() -> None:
    """The item ceiling derived from the call ceiling must pass runtime
    admission even when the native-JSON fallback call is possible."""
    from eneo.flows.runtime.step_handlers.mapped_outputs import (
        mapped_admission_payload,
    )

    policy = FlowMappedExecutionPolicy(max_provider_calls_per_mapped_step=100)
    items = max_mapped_items_per_step(policy)
    assert items == 99

    payload = mapped_admission_payload(
        execution_mode="per_source_reader",
        estimates=[1] * items,
        native_json_fallback_possible=True,
        policy=policy,
    )

    assert payload is not None


def test_policy_object_rejects_an_enabled_ceiling_below_the_minimum() -> None:
    with pytest.raises(ValueError):
        FlowMappedExecutionPolicy(max_provider_calls_per_mapped_step=1)
    with pytest.raises(ValueError):
        FlowMappedExecutionPolicy(max_estimated_input_tokens_per_mapped_step=0)


def test_resolver_ignores_a_deployment_default_below_the_minimum() -> None:
    policy = resolve_flow_mapped_execution_policy(None, default_max_provider_calls=1)

    assert policy.max_provider_calls_per_mapped_step is None


def test_source_reports_invalid_for_corrupt_storage() -> None:
    from eneo.flows.domain.mapped_execution_policy import mapped_call_ceiling_source

    assert mapped_call_ceiling_source({"mapped_execution": None}) == "invalid"
    assert (
        mapped_call_ceiling_source({"mapped_execution": {"version": 99}}) == "invalid"
    )
    assert mapped_call_ceiling_source(None) == "deployment_default"


def test_resolve_unset_policy_inherits_deployment_default() -> None:
    policy = resolve_flow_mapped_execution_policy(None, default_max_provider_calls=100)

    assert policy.max_provider_calls_per_mapped_step == 100
    assert policy.max_estimated_input_tokens_per_mapped_step is None


def test_resolve_organization_value_wins_over_deployment_default() -> None:
    policy = resolve_flow_mapped_execution_policy(
        {"mapped_execution": {"version": 1, "max_provider_calls_per_mapped_step": 7}},
        default_max_provider_calls=100,
    )

    assert policy.max_provider_calls_per_mapped_step == 7


def test_resolve_explicit_disable_blocks_beneath_deployment_default() -> None:
    policy = resolve_flow_mapped_execution_policy(
        {
            "mapped_execution": {
                "version": 1,
                "max_provider_calls_per_mapped_step": None,
            }
        },
        default_max_provider_calls=100,
    )

    assert policy.max_provider_calls_per_mapped_step is None


def test_validate_accepts_explicit_null_call_ceiling() -> None:
    validated = validate_flow_mapped_execution_policy_object(
        {"version": 1, "max_provider_calls_per_mapped_step": None}
    )

    assert validated["max_provider_calls_per_mapped_step"] is None


def test_patch_disable_stores_explicit_null_that_survives_resolution() -> None:
    updated = apply_flow_mapped_execution_policy_patch(
        {"mapped_execution": {"version": 1, "max_provider_calls_per_mapped_step": 5}},
        disable_max_provider_calls=True,
    )

    assert updated == {
        "mapped_execution": {
            "version": 1,
            "max_provider_calls_per_mapped_step": None,
        }
    }
    policy = resolve_flow_mapped_execution_policy(
        updated, default_max_provider_calls=100
    )
    assert policy.max_provider_calls_per_mapped_step is None


def test_patch_reenable_after_disable_restores_organization_value() -> None:
    disabled = apply_flow_mapped_execution_policy_patch(
        None, disable_max_provider_calls=True
    )
    reenabled = apply_flow_mapped_execution_policy_patch(
        disabled, max_provider_calls_per_mapped_step=40
    )

    policy = resolve_flow_mapped_execution_policy(
        reenabled, default_max_provider_calls=100
    )
    assert policy.max_provider_calls_per_mapped_step == 40


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
        {"max_provider_calls_per_mapped_step": 1},
        {"max_estimated_input_tokens_per_mapped_step": None},
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
