"""Runtime deadline policy for flow LLM-backed steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, cast

from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

logger = get_logger(__name__)

FLOW_RUNTIME_POLICY_SETTINGS_KEY: Final[str] = "runtime_policy"
STEP_TIMEOUT_TASK_BUFFER_SECONDS: Final[int] = 60
MIN_TASK_EXECUTION_TIMEOUT_SECONDS: Final[int] = STEP_TIMEOUT_TASK_BUFFER_SECONDS + 5

FLOW_RUNTIME_POLICY_STORAGE_VERSION_KEY: Final[str] = "version"
FLOW_RUNTIME_POLICY_STORAGE_VERSION: Final[int] = 1
FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY: Final[str] = "default_step_timeout_seconds"
FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY: Final[str] = "max_step_timeout_seconds"
FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY: Final[str] = "max_concurrent_runs"
_RUN_CAPACITY_ENV_FIELD: Final[str] = "flow_max_concurrent_runs_per_tenant"
FLOW_RUNTIME_POLICY_BUSINESS_KEYS: Final[frozenset[str]] = frozenset(
    {
        FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY,
        FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY,
        FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY,
    }
)
FLOW_RUNTIME_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        FLOW_RUNTIME_POLICY_STORAGE_VERSION_KEY,
        *FLOW_RUNTIME_POLICY_BUSINESS_KEYS,
    }
)


@dataclass(frozen=True, slots=True)
class FlowRuntimePolicy:
    default_step_timeout_seconds: int
    max_step_timeout_seconds: int
    hard_ceiling_seconds: int
    max_concurrent_runs: int
    max_concurrent_runs_capacity: int
    # The admin's stored value, even when capacity clamps it; None when the
    # setting inherits the capacity.
    max_concurrent_runs_override: int | None = None


def flow_runtime_run_capacity(*, defaults: Any | None = None) -> int:
    """Server capacity for concurrent flow runs: the bound and default of the
    admin's "max concurrent flow runs".

    An operator who set FLOW_MAX_CONCURRENT_RUNS_PER_TENANT keeps that value;
    otherwise the capacity is the execution worker's slots, so the two numbers
    cannot drift apart by default. Zero is kept: a deployment that sets the
    variable to 0 admits no run, and no admin value can raise it.
    """
    settings = defaults or get_settings()
    if _RUN_CAPACITY_ENV_FIELD in getattr(settings, "model_fields_set", ()):
        return max(0, int(getattr(settings, _RUN_CAPACITY_ENV_FIELD)))
    return max(0, int(settings.task_execution_max_jobs))


def warn_when_run_capacity_exceeds_executor_slots(
    *, executor_slots: int, defaults: Any | None = None
) -> bool:
    """Log when admitted runs can outnumber the worker's executor slots.

    The run limit counts queued runs, so a capacity above the slots admits runs
    that then wait for a slot while their observation deadlines keep running.
    """
    capacity = flow_runtime_run_capacity(defaults=defaults)
    if capacity <= executor_slots:
        return False
    logger.warning(
        "FLOW_MAX_CONCURRENT_RUNS_PER_TENANT exceeds the execution worker slots; "
        "admitted runs beyond the slots wait in the queue",
        extra={
            "max_concurrent_runs_capacity": capacity,
            "task_execution_max_jobs": executor_slots,
        },
    )
    return True


def flow_runtime_step_timeout_hard_ceiling_seconds(
    *,
    defaults: Any | None = None,
) -> int:
    settings = defaults or get_settings()
    task_ceiling = (
        int(settings.task_execution_timeout_seconds) - STEP_TIMEOUT_TASK_BUFFER_SECONDS
    )
    return max(1, task_ceiling)


def default_flow_runtime_policy(*, defaults: Any | None = None) -> FlowRuntimePolicy:
    settings = defaults or get_settings()
    hard_ceiling = flow_runtime_step_timeout_hard_ceiling_seconds(defaults=settings)
    run_capacity = flow_runtime_run_capacity(defaults=settings)
    return FlowRuntimePolicy(
        default_step_timeout_seconds=hard_ceiling,
        max_step_timeout_seconds=hard_ceiling,
        hard_ceiling_seconds=hard_ceiling,
        max_concurrent_runs=run_capacity,
        max_concurrent_runs_capacity=run_capacity,
    )


def _extract_runtime_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}
    policy = tenant_flow_settings.get(FLOW_RUNTIME_POLICY_SETTINGS_KEY)
    if not isinstance(policy, dict):
        return {}
    policy_dict = cast(dict[str, Any], policy)
    if not _is_supported_storage_version(
        policy_dict.get(FLOW_RUNTIME_POLICY_STORAGE_VERSION_KEY)
    ):
        return {}
    return dict(policy_dict)


def _parse_positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(
            f"{field_name} must be an integer.",
            code=f"{field_name}_invalid",
        )
    if value < 1:
        raise BadRequestException(
            f"{field_name} must be greater than zero.",
            code=f"{field_name}_invalid",
        )
    return value


def validate_flow_runtime_policy_object(
    policy: Any,
    *,
    defaults: Any | None = None,
) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise BadRequestException(
            "flow_settings.runtime_policy must be an object",
            code="flow_runtime_policy_invalid",
        )

    policy_dict = cast(dict[str, Any], policy)
    for key in policy_dict:
        if key not in FLOW_RUNTIME_POLICY_KEYS:
            raise BadRequestException(
                f"Unsupported flow runtime policy field: {key}.",
                code="flow_runtime_policy_unknown_field",
            )
    _validate_storage_version(policy_dict.get(FLOW_RUNTIME_POLICY_STORAGE_VERSION_KEY))

    hard_ceiling = flow_runtime_step_timeout_hard_ceiling_seconds(defaults=defaults)
    parsed: dict[str, Any] = {}
    if FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY in policy_dict:
        parsed[FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY] = _parse_positive_int(
            policy_dict[FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY],
            FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY,
        )
    if FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY in policy_dict:
        parsed[FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY] = _parse_positive_int(
            policy_dict[FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY],
            FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY,
        )

    # Server capacity is deployment state, so it is not checked here: a stored
    # value above a later-lowered capacity must not make the settings row fail
    # validation. The write path refuses it and resolution clamps it.
    if FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY in policy_dict:
        parsed[FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY] = _parse_positive_int(
            policy_dict[FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY],
            FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY,
        )

    max_timeout = parsed.get(FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY)
    if isinstance(max_timeout, int) and max_timeout > hard_ceiling:
        raise BadRequestException(
            "max_step_timeout_seconds exceeds the deployment hard ceiling.",
            code="tenant_max_exceeds_env_hard_ceiling",
            context={
                "max_step_timeout_seconds": max_timeout,
                "hard_ceiling_seconds": hard_ceiling,
            },
        )

    default_timeout = parsed.get(FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY)
    effective_max = max_timeout if isinstance(max_timeout, int) else hard_ceiling
    if isinstance(default_timeout, int) and default_timeout > effective_max:
        raise BadRequestException(
            "default_step_timeout_seconds exceeds max_step_timeout_seconds.",
            code="default_timeout_exceeds_tenant_max",
            context={
                "default_step_timeout_seconds": default_timeout,
                "max_step_timeout_seconds": effective_max,
            },
        )
    return policy_dict


def resolve_flow_runtime_policy(
    tenant_flow_settings: dict[str, Any] | None,
    *,
    defaults: Any | None = None,
) -> FlowRuntimePolicy:
    base = default_flow_runtime_policy(defaults=defaults)
    overrides = _extract_runtime_policy(tenant_flow_settings)
    if not overrides:
        return base

    run_limit = base.max_concurrent_runs
    run_override: int | None = None
    if FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY in overrides:
        try:
            run_override = _parse_positive_int(
                overrides[FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY],
                FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY,
            )
            # A stored value above a lowered capacity clamps silently: this runs
            # on every admission, poll and GET.
            run_limit = min(run_override, base.max_concurrent_runs_capacity)
        except BadRequestException:
            logger.warning(
                "Ignoring invalid stored max concurrent flow runs",
                extra={"value": overrides.get(FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY)},
            )

    default_timeout = base.default_step_timeout_seconds
    max_timeout = base.max_step_timeout_seconds
    if FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY in overrides:
        try:
            parsed_max = _parse_positive_int(
                overrides[FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY],
                FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY,
            )
            if parsed_max <= base.hard_ceiling_seconds:
                max_timeout = parsed_max
            else:
                logger.warning(
                    "Ignoring invalid tenant flow runtime max timeout override",
                    extra={
                        "value": parsed_max,
                        "hard_ceiling_seconds": base.hard_ceiling_seconds,
                    },
                )
        except BadRequestException:
            logger.warning(
                "Ignoring invalid tenant flow runtime max timeout override",
                extra={"value": overrides.get(FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY)},
            )

    if FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY in overrides:
        try:
            parsed_default = _parse_positive_int(
                overrides[FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY],
                FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY,
            )
            if parsed_default <= max_timeout:
                default_timeout = parsed_default
            else:
                logger.warning(
                    "Ignoring invalid tenant flow runtime default timeout override",
                    extra={
                        "value": parsed_default,
                        "max_step_timeout_seconds": max_timeout,
                    },
                )
        except BadRequestException:
            logger.warning(
                "Ignoring invalid tenant flow runtime default timeout override",
                extra={"value": overrides.get(FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY)},
            )

    # The resolved policy must always satisfy default <= max, even when a
    # stored maximum undercuts the deployment default (e.g. the tenant default
    # was cleared while a lower maximum stayed configured).
    if default_timeout > max_timeout:
        logger.warning(
            "Clamping flow runtime default timeout to the resolved maximum",
            extra={
                "default_step_timeout_seconds": default_timeout,
                "max_step_timeout_seconds": max_timeout,
            },
        )
        default_timeout = max_timeout

    return FlowRuntimePolicy(
        default_step_timeout_seconds=default_timeout,
        max_step_timeout_seconds=max_timeout,
        hard_ceiling_seconds=base.hard_ceiling_seconds,
        max_concurrent_runs=run_limit,
        max_concurrent_runs_capacity=base.max_concurrent_runs_capacity,
        max_concurrent_runs_override=run_override,
    )


def apply_flow_runtime_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    default_step_timeout_seconds: int | None = None,
    max_step_timeout_seconds: int | None = None,
    max_concurrent_runs: int | None = None,
    remove_keys: set[str] | None = None,
    defaults: Any | None = None,
) -> dict[str, Any]:
    result = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    next_policy = _extract_runtime_policy(result)

    if default_step_timeout_seconds is not None:
        next_policy[FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY] = _parse_positive_int(
            default_step_timeout_seconds,
            FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY,
        )
    if max_step_timeout_seconds is not None:
        next_policy[FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY] = _parse_positive_int(
            max_step_timeout_seconds,
            FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY,
        )

    if max_concurrent_runs is not None:
        run_capacity = flow_runtime_run_capacity(defaults=defaults)
        requested = _parse_positive_int(
            max_concurrent_runs, FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY
        )
        if requested > run_capacity:
            raise BadRequestException(
                "max_concurrent_runs exceeds the server capacity.",
                code="max_concurrent_runs_exceeds_server_capacity",
                context={
                    "max_concurrent_runs": requested,
                    "max_concurrent_runs_capacity": run_capacity,
                },
            )
        # Equal to the capacity is the inherited value: storing it would pin the
        # setting to today's capacity after the operator changes it.
        if requested == run_capacity:
            next_policy.pop(FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY, None)
        else:
            next_policy[FLOW_RUNTIME_MAX_CONCURRENT_RUNS_KEY] = requested

    for key in remove_keys or ():
        if key not in FLOW_RUNTIME_POLICY_KEYS:
            raise BadRequestException(
                f"Unsupported flow runtime policy field: {key}.",
                code="flow_runtime_policy_unknown_field",
            )
        next_policy.pop(key, None)

    has_business_fields = any(
        key in next_policy for key in FLOW_RUNTIME_POLICY_BUSINESS_KEYS
    )
    if has_business_fields:
        next_policy[FLOW_RUNTIME_POLICY_STORAGE_VERSION_KEY] = (
            FLOW_RUNTIME_POLICY_STORAGE_VERSION
        )

    validate_flow_runtime_policy_object(next_policy, defaults=defaults)
    if has_business_fields:
        result[FLOW_RUNTIME_POLICY_SETTINGS_KEY] = next_policy
    else:
        result.pop(FLOW_RUNTIME_POLICY_SETTINGS_KEY, None)
    return result


def resolve_step_timeout_seconds(
    *,
    step_timeout_seconds: int | None,
    policy: FlowRuntimePolicy,
) -> int:
    if step_timeout_seconds is None:
        return policy.default_step_timeout_seconds
    parsed = _parse_positive_int(step_timeout_seconds, "timeout_seconds")
    if parsed > policy.max_step_timeout_seconds:
        raise BadRequestException(
            "Step timeout exceeds the tenant runtime policy maximum.",
            code="flow_step_timeout_exceeds_tenant_max",
            context={
                "timeout_seconds": parsed,
                "max_step_timeout_seconds": policy.max_step_timeout_seconds,
            },
        )
    return parsed


def _is_supported_storage_version(value: Any) -> bool:
    return value is None or (
        type(value) is int and value == FLOW_RUNTIME_POLICY_STORAGE_VERSION
    )


def _validate_storage_version(value: Any) -> None:
    if _is_supported_storage_version(value):
        return
    raise BadRequestException(
        "flow_settings.runtime_policy.version must be 1",
        code="flow_runtime_policy_version_unsupported",
    )
