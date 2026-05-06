"""Runtime deadline policy for flow LLM-backed steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, cast

from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger

logger = get_logger(__name__)

FLOW_RUNTIME_POLICY_SETTINGS_KEY: Final[str] = "runtime_policy"
STEP_TIMEOUT_TASK_BUFFER_SECONDS: Final[int] = 60

FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY: Final[str] = "default_step_timeout_seconds"
FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY: Final[str] = "max_step_timeout_seconds"
FLOW_RUNTIME_POLICY_KEYS: Final[frozenset[str]] = frozenset(
    {
        FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY,
        FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY,
    }
)


@dataclass(frozen=True, slots=True)
class FlowRuntimePolicy:
    default_step_timeout_seconds: int
    max_step_timeout_seconds: int
    hard_ceiling_seconds: int


def flow_runtime_step_timeout_hard_ceiling_seconds(
    *,
    defaults: Any | None = None,
) -> int:
    settings = defaults or get_settings()
    configured_ceiling = int(settings.flow_runtime_step_timeout_hard_ceiling_seconds)
    task_ceiling = int(settings.flow_task_timeout_seconds) - STEP_TIMEOUT_TASK_BUFFER_SECONDS
    return max(1, min(configured_ceiling, task_ceiling))


def default_flow_runtime_policy(*, defaults: Any | None = None) -> FlowRuntimePolicy:
    settings = defaults or get_settings()
    hard_ceiling = flow_runtime_step_timeout_hard_ceiling_seconds(defaults=settings)
    return FlowRuntimePolicy(
        default_step_timeout_seconds=min(
            int(settings.flow_llm_request_timeout_seconds),
            hard_ceiling,
        ),
        max_step_timeout_seconds=hard_ceiling,
        hard_ceiling_seconds=hard_ceiling,
    )


def _extract_runtime_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}
    policy = tenant_flow_settings.get(FLOW_RUNTIME_POLICY_SETTINGS_KEY)
    if not isinstance(policy, dict):
        return {}
    return dict(cast(dict[str, Any], policy))


def _parse_positive_timeout_seconds(value: Any, field_name: str) -> int:
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

    hard_ceiling = flow_runtime_step_timeout_hard_ceiling_seconds(defaults=defaults)
    parsed: dict[str, Any] = {}
    if FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY in policy_dict:
        parsed[FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY] = _parse_positive_timeout_seconds(
            policy_dict[FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY],
            FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY,
        )
    if FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY in policy_dict:
        parsed[FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY] = _parse_positive_timeout_seconds(
            policy_dict[FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY],
            FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY,
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

    default_timeout = base.default_step_timeout_seconds
    max_timeout = base.max_step_timeout_seconds
    if FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY in overrides:
        try:
            parsed_max = _parse_positive_timeout_seconds(
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
            parsed_default = _parse_positive_timeout_seconds(
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

    return FlowRuntimePolicy(
        default_step_timeout_seconds=default_timeout,
        max_step_timeout_seconds=max_timeout,
        hard_ceiling_seconds=base.hard_ceiling_seconds,
    )


def apply_flow_runtime_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    default_step_timeout_seconds: int | None = None,
    max_step_timeout_seconds: int | None = None,
    remove_keys: set[str] | None = None,
    defaults: Any | None = None,
) -> dict[str, Any]:
    result = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    next_policy = _extract_runtime_policy(result)

    if default_step_timeout_seconds is not None:
        next_policy[FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY] = _parse_positive_timeout_seconds(
            default_step_timeout_seconds,
            FLOW_RUNTIME_DEFAULT_STEP_TIMEOUT_KEY,
        )
    if max_step_timeout_seconds is not None:
        next_policy[FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY] = _parse_positive_timeout_seconds(
            max_step_timeout_seconds,
            FLOW_RUNTIME_MAX_STEP_TIMEOUT_KEY,
        )

    for key in remove_keys or ():
        if key not in FLOW_RUNTIME_POLICY_KEYS:
            raise BadRequestException(
                f"Unsupported flow runtime policy field: {key}.",
                code="flow_runtime_policy_unknown_field",
            )
        next_policy.pop(key, None)

    validate_flow_runtime_policy_object(next_policy, defaults=defaults)
    if next_policy:
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
    parsed = _parse_positive_timeout_seconds(step_timeout_seconds, "timeout_seconds")
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
