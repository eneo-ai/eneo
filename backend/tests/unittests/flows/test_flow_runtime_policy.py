from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from eneo.flows import flow_runtime_policy as policy_module
from eneo.flows.flow_runtime_policy import (
    STEP_TIMEOUT_TASK_BUFFER_SECONDS,
    apply_flow_runtime_policy_patch,
    resolve_flow_runtime_policy,
    resolve_step_timeout_seconds,
    validate_flow_runtime_policy_object,
    warn_when_run_capacity_exceeds_executor_slots,
)
from eneo.main.exceptions import BadRequestException


def _settings(
    *,
    task_timeout: int = 3600,
    run_capacity: int | None = 4,
    executor_slots: int = 4,
) -> SimpleNamespace:
    """`run_capacity=None` models the variable being unset."""
    return SimpleNamespace(
        task_execution_timeout_seconds=task_timeout,
        task_execution_max_jobs=executor_slots,
        flow_max_concurrent_runs_per_tenant=4 if run_capacity is None else run_capacity,
        model_fields_set=(
            set() if run_capacity is None else {"flow_max_concurrent_runs_per_tenant"}
        ),
    )


def test_resolve_runtime_policy_uses_deployment_defaults() -> None:
    policy = resolve_flow_runtime_policy(
        None,
        defaults=_settings(task_timeout=2000),
    )

    assert policy.default_step_timeout_seconds == 1940
    assert policy.max_step_timeout_seconds == 2000 - STEP_TIMEOUT_TASK_BUFFER_SECONDS
    assert policy.hard_ceiling_seconds == 2000 - STEP_TIMEOUT_TASK_BUFFER_SECONDS


def test_resolve_clamps_deployment_default_to_a_lower_tenant_maximum() -> None:
    """Clearing the tenant default while keeping a lower maximum must never
    resolve to default > max; the deployment default clamps to the maximum."""
    policy = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1, "max_step_timeout_seconds": 300}},
        defaults=_settings(),
    )

    assert policy.max_step_timeout_seconds == 300
    assert policy.default_step_timeout_seconds == 300


def test_apply_patch_preserves_unrelated_flow_settings() -> None:
    updated = apply_flow_runtime_policy_patch(
        {
            "input_limits": {"max_files_per_run": 10},
            "runtime_policy": {"default_step_timeout_seconds": 600},
        },
        max_step_timeout_seconds=1800,
        defaults=_settings(),
    )

    assert updated["input_limits"] == {"max_files_per_run": 10}
    assert updated["runtime_policy"] == {
        "version": 1,
        "default_step_timeout_seconds": 600,
        "max_step_timeout_seconds": 1800,
    }


def test_apply_patch_removes_runtime_policy_when_business_fields_are_cleared() -> None:
    updated = apply_flow_runtime_policy_patch(
        {
            "input_limits": {"max_files_per_run": 10},
            "runtime_policy": {
                "version": 1,
                "default_step_timeout_seconds": 600,
                "max_step_timeout_seconds": 1800,
            },
        },
        remove_keys={"default_step_timeout_seconds", "max_step_timeout_seconds"},
        defaults=_settings(),
    )

    assert updated == {"input_limits": {"max_files_per_run": 10}}


def test_runtime_policy_storage_version_accepts_legacy_missing_and_current() -> None:
    assert validate_flow_runtime_policy_object(
        {"default_step_timeout_seconds": 600},
        defaults=_settings(),
    ) == {"default_step_timeout_seconds": 600}
    assert validate_flow_runtime_policy_object(
        {"version": 1, "default_step_timeout_seconds": 600},
        defaults=_settings(),
    ) == {"version": 1, "default_step_timeout_seconds": 600}


@pytest.mark.parametrize("version", [0, 2, "1", True, 1.0])
def test_runtime_policy_storage_version_rejects_unsupported_values(
    version: object,
) -> None:
    with pytest.raises(BadRequestException) as exc_info:
        validate_flow_runtime_policy_object(
            {"version": version, "default_step_timeout_seconds": 600},
            defaults=_settings(),
        )

    assert exc_info.value.code == "flow_runtime_policy_version_unsupported"


def test_resolve_runtime_policy_ignores_unsupported_storage_version() -> None:
    policy = resolve_flow_runtime_policy(
        {
            "runtime_policy": {
                "version": 2,
                "default_step_timeout_seconds": 1200,
                "max_step_timeout_seconds": 2400,
            }
        },
        defaults=_settings(task_timeout=1800),
    )

    assert policy.default_step_timeout_seconds == 1740
    assert policy.max_step_timeout_seconds == 1800 - STEP_TIMEOUT_TASK_BUFFER_SECONDS


def test_resolve_runtime_policy_ignores_version_only_storage_envelope() -> None:
    policy = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1}},
        defaults=_settings(task_timeout=1800),
    )

    assert policy.default_step_timeout_seconds == 1740
    assert policy.max_step_timeout_seconds == 1800 - STEP_TIMEOUT_TASK_BUFFER_SECONDS


def test_apply_patch_restamps_version_when_business_fields_persist() -> None:
    updated = apply_flow_runtime_policy_patch(
        {
            "runtime_policy": {
                "version": 1,
                "default_step_timeout_seconds": 600,
            },
        },
        remove_keys={"version"},
        defaults=_settings(),
    )

    assert updated["runtime_policy"] == {
        "version": 1,
        "default_step_timeout_seconds": 600,
    }


def test_apply_patch_rejects_default_above_max() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        apply_flow_runtime_policy_patch(
            {},
            default_step_timeout_seconds=1200,
            max_step_timeout_seconds=900,
            defaults=_settings(),
        )

    assert exc_info.value.code == "default_timeout_exceeds_tenant_max"


def test_apply_patch_rejects_max_above_hard_ceiling() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        apply_flow_runtime_policy_patch(
            {},
            max_step_timeout_seconds=4000,
            defaults=_settings(task_timeout=3600),
        )

    assert exc_info.value.code == "tenant_max_exceeds_env_hard_ceiling"


def test_step_timeout_uses_policy_default_and_rejects_override_above_max() -> None:
    policy = resolve_flow_runtime_policy(
        {
            "runtime_policy": {
                "default_step_timeout_seconds": 800,
                "max_step_timeout_seconds": 1200,
            }
        },
        defaults=_settings(),
    )

    assert resolve_step_timeout_seconds(step_timeout_seconds=None, policy=policy) == 800

    with pytest.raises(BadRequestException) as exc_info:
        resolve_step_timeout_seconds(step_timeout_seconds=1500, policy=policy)

    assert exc_info.value.code == "flow_step_timeout_exceeds_tenant_max"


def test_invocation_ceiling_defines_the_effective_policy() -> None:
    from eneo.main.config import Settings

    defaults = Settings.model_construct(task_execution_timeout_seconds=14400)
    policy = resolve_flow_runtime_policy(None, defaults=defaults)
    assert policy.default_step_timeout_seconds == 14340
    assert policy.hard_ceiling_seconds == 14340
    assert (
        resolve_step_timeout_seconds(step_timeout_seconds=7200, policy=policy) == 7200
    )
    with pytest.raises(BadRequestException, match="deployment hard ceiling"):
        validate_flow_runtime_policy_object(
            {"max_step_timeout_seconds": 14400}, defaults=defaults
        )
    with pytest.raises(BadRequestException, match="exceeds max_step_timeout_seconds"):
        validate_flow_runtime_policy_object(
            {"default_step_timeout_seconds": 14400}, defaults=defaults
        )


# --- max_concurrent_runs: an admin value bounded by the server capacity ---

_NOT_A_POSITIVE_INT = [0, -1, True, False, "3", 3.0, 2.5, None, [], {}, [2]]


def test_run_capacity_defaults_to_the_executor_slots_and_keeps_an_explicit_env_value() -> (
    None
):
    unset = _settings(run_capacity=None, executor_slots=6)
    assert resolve_flow_runtime_policy(None, defaults=unset).max_concurrent_runs == 6

    explicit = _settings(run_capacity=3, executor_slots=6)
    policy = resolve_flow_runtime_policy(None, defaults=explicit)
    assert (policy.max_concurrent_runs, policy.max_concurrent_runs_capacity) == (3, 3)


def test_run_limit_defaults_to_the_server_capacity() -> None:
    for stored in (None, {}, {"runtime_policy": None}, {"runtime_policy": {}}):
        policy = resolve_flow_runtime_policy(stored, defaults=_settings(run_capacity=6))

        assert policy.max_concurrent_runs == 6
        assert policy.max_concurrent_runs_capacity == 6


def test_run_limit_uses_an_admin_value_below_the_capacity() -> None:
    policy = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1, "max_concurrent_runs": 2}},
        defaults=_settings(run_capacity=6),
    )

    assert policy.max_concurrent_runs == 2
    assert policy.max_concurrent_runs_capacity == 6


@pytest.mark.parametrize("stored", [*_NOT_A_POSITIVE_INT, 7, 10**9])
def test_run_limit_ignores_a_stored_value_that_is_not_a_valid_override(
    stored: object,
) -> None:
    policy = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1, "max_concurrent_runs": stored}},
        defaults=_settings(run_capacity=6),
    )

    assert policy.max_concurrent_runs == 6


def test_run_limit_follows_a_lowered_server_capacity() -> None:
    policy = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1, "max_concurrent_runs": 5}},
        defaults=_settings(run_capacity=3),
    )

    assert policy.max_concurrent_runs == 3


@pytest.mark.parametrize("capacity", [0, -2])
def test_a_non_positive_env_capacity_admits_no_run_and_no_override(
    capacity: int,
) -> None:
    policy = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1, "max_concurrent_runs": 1}},
        defaults=_settings(run_capacity=capacity),
    )
    assert policy.max_concurrent_runs == 0
    assert policy.max_concurrent_runs_capacity == 0

    with pytest.raises(BadRequestException) as exc_info:
        apply_flow_runtime_policy_patch(
            {}, max_concurrent_runs=1, defaults=_settings(run_capacity=capacity)
        )
    assert exc_info.value.code == "max_concurrent_runs_exceeds_server_capacity"


def test_patch_stores_an_override_below_the_capacity() -> None:
    updated = apply_flow_runtime_policy_patch(
        {"input_limits": {"max_files_per_run": 10}},
        max_concurrent_runs=2,
        defaults=_settings(run_capacity=6),
    )

    assert updated["runtime_policy"] == {"version": 1, "max_concurrent_runs": 2}
    assert updated["input_limits"] == {"max_files_per_run": 10}


def test_patch_equal_to_the_capacity_stores_no_override() -> None:
    updated = apply_flow_runtime_policy_patch(
        {
            "input_limits": {"max_files_per_run": 10},
            "runtime_policy": {"version": 1, "max_concurrent_runs": 2},
        },
        max_concurrent_runs=6,
        defaults=_settings(run_capacity=6),
    )

    assert updated == {"input_limits": {"max_files_per_run": 10}}


def test_patch_equal_to_the_capacity_keeps_the_other_overrides() -> None:
    updated = apply_flow_runtime_policy_patch(
        {"runtime_policy": {"version": 1, "default_step_timeout_seconds": 600}},
        max_concurrent_runs=6,
        defaults=_settings(run_capacity=6),
    )

    assert updated["runtime_policy"] == {
        "version": 1,
        "default_step_timeout_seconds": 600,
    }


def test_patch_remove_key_returns_to_the_capacity() -> None:
    updated = apply_flow_runtime_policy_patch(
        {"runtime_policy": {"version": 1, "max_concurrent_runs": 2}},
        remove_keys={"max_concurrent_runs"},
        defaults=_settings(run_capacity=6),
    )

    assert "runtime_policy" not in updated


def test_patch_above_the_capacity_is_refused_with_the_bound() -> None:
    with pytest.raises(BadRequestException) as exc_info:
        apply_flow_runtime_policy_patch(
            {}, max_concurrent_runs=7, defaults=_settings(run_capacity=6)
        )

    assert exc_info.value.code == "max_concurrent_runs_exceeds_server_capacity"
    assert exc_info.value.context == {
        "max_concurrent_runs": 7,
        "max_concurrent_runs_capacity": 6,
    }


@pytest.mark.parametrize("value", [v for v in _NOT_A_POSITIVE_INT if v is not None])
def test_patch_refuses_a_value_that_is_not_a_positive_integer(value: object) -> None:
    with pytest.raises(BadRequestException) as exc_info:
        apply_flow_runtime_policy_patch(
            {},
            max_concurrent_runs=value,
            defaults=_settings(),  # type: ignore[arg-type]
        )

    assert exc_info.value.code == "max_concurrent_runs_invalid"


@pytest.mark.parametrize("value", [v for v in _NOT_A_POSITIVE_INT if v is not None])
def test_stored_validation_refuses_a_value_that_is_not_a_positive_integer(
    value: object,
) -> None:
    with pytest.raises(BadRequestException) as exc_info:
        validate_flow_runtime_policy_object(
            {"version": 1, "max_concurrent_runs": value}, defaults=_settings()
        )

    assert exc_info.value.code == "max_concurrent_runs_invalid"


def test_stored_validation_keeps_settings_loadable_after_the_capacity_is_lowered() -> (
    None
):
    """The capacity is deployment state; a stored value above it must not make
    the settings row fail validation. Resolution clamps it instead."""
    stored = {"version": 1, "max_concurrent_runs": 9}

    assert (
        validate_flow_runtime_policy_object(stored, defaults=_settings(run_capacity=3))
        == stored
    )


@pytest.mark.parametrize(
    ("capacity", "slots", "warns"),
    [(5, 4, True), (4, 4, False), (2, 4, False), (0, 4, False)],
)
def test_warns_only_when_the_run_capacity_exceeds_the_executor_slots(
    monkeypatch: pytest.MonkeyPatch, capacity: int, slots: int, warns: bool
) -> None:
    warning = MagicMock()
    monkeypatch.setattr(policy_module.logger, "warning", warning)

    result = warn_when_run_capacity_exceeds_executor_slots(
        executor_slots=slots, defaults=_settings(run_capacity=capacity)
    )

    assert result is warns
    assert warning.called is warns


@pytest.mark.parametrize(
    "template", ["backend/.env.template", "docs/deployment/env_backend.template"]
)
def test_shipped_env_templates_leave_the_run_capacity_unset(template: str) -> None:
    """A copied template must not pin the capacity: with the variable unset the
    capacity follows TASK_EXECUTION_MAX_JOBS."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[4] / template
    if not path.exists():
        pytest.skip(f"{template} is not part of this checkout")
    active = [
        line
        for line in path.read_text().splitlines()
        if line.strip().startswith("FLOW_MAX_CONCURRENT_RUNS_PER_TENANT")
    ]

    assert active == []


def test_resolve_reports_the_stored_value_even_when_capacity_clamps_it() -> None:
    clamped = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1, "max_concurrent_runs": 6}},
        defaults=_settings(run_capacity=3),
    )
    below = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1, "max_concurrent_runs": 2}},
        defaults=_settings(run_capacity=3),
    )

    assert (clamped.max_concurrent_runs, clamped.max_concurrent_runs_override) == (3, 6)
    assert (below.max_concurrent_runs, below.max_concurrent_runs_override) == (2, 2)


@pytest.mark.parametrize("stored", [*_NOT_A_POSITIVE_INT, 7])
def test_resolve_reports_no_override_for_nothing_or_an_invalid_value(stored) -> None:
    assert (
        resolve_flow_runtime_policy(
            None, defaults=_settings()
        ).max_concurrent_runs_override
        is None
    )
    if stored == 7:
        return
    policy = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1, "max_concurrent_runs": stored}},
        defaults=_settings(),
    )
    assert policy.max_concurrent_runs_override is None
