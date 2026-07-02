from types import SimpleNamespace

import pytest

from eneo.flows.flow_runtime_policy import (
    STEP_TIMEOUT_TASK_BUFFER_SECONDS,
    apply_flow_runtime_policy_patch,
    resolve_flow_runtime_policy,
    resolve_step_timeout_seconds,
    validate_flow_runtime_policy_object,
)
from eneo.main.exceptions import BadRequestException


def _settings(
    *,
    llm_timeout: int = 600,
    task_timeout: int = 3600,
    hard_ceiling: int = 3600,
) -> SimpleNamespace:
    return SimpleNamespace(
        flow_llm_request_timeout_seconds=llm_timeout,
        flow_task_timeout_seconds=task_timeout,
        flow_runtime_step_timeout_hard_ceiling_seconds=hard_ceiling,
    )


def test_resolve_runtime_policy_uses_deployment_defaults() -> None:
    policy = resolve_flow_runtime_policy(
        None,
        defaults=_settings(llm_timeout=900, task_timeout=2000, hard_ceiling=3000),
    )

    assert policy.default_step_timeout_seconds == 900
    assert policy.max_step_timeout_seconds == 2000 - STEP_TIMEOUT_TASK_BUFFER_SECONDS
    assert policy.hard_ceiling_seconds == 2000 - STEP_TIMEOUT_TASK_BUFFER_SECONDS


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
        defaults=_settings(llm_timeout=700, task_timeout=1800, hard_ceiling=3600),
    )

    assert policy.default_step_timeout_seconds == 700
    assert policy.max_step_timeout_seconds == 1800 - STEP_TIMEOUT_TASK_BUFFER_SECONDS


def test_resolve_runtime_policy_ignores_version_only_storage_envelope() -> None:
    policy = resolve_flow_runtime_policy(
        {"runtime_policy": {"version": 1}},
        defaults=_settings(llm_timeout=700, task_timeout=1800, hard_ceiling=3600),
    )

    assert policy.default_step_timeout_seconds == 700
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
            defaults=_settings(task_timeout=3600, hard_ceiling=3600),
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
