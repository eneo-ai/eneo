"""Tenant policy and effective bounds for mapped Flow execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, cast

from eneo.main.exceptions import BadRequestException

MAPPED_EXECUTION_SETTINGS_KEY: Final[str] = "mapped_execution"
MAPPED_EXECUTION_STORAGE_VERSION: Final[Literal[1]] = 1
MAPPED_EXECUTION_VERSION_KEY: Final[str] = "version"
MAPPED_EXECUTION_MAX_CALLS_KEY: Final[str] = "max_provider_calls_per_mapped_step"
MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY: Final[str] = (
    "max_estimated_input_tokens_per_mapped_step"
)
MAPPED_EXECUTION_BUSINESS_KEYS: Final[frozenset[str]] = frozenset(
    {MAPPED_EXECUTION_MAX_CALLS_KEY, MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY}
)
MAPPED_EXECUTION_KEYS: Final[frozenset[str]] = frozenset(
    {MAPPED_EXECUTION_VERSION_KEY, *MAPPED_EXECUTION_BUSINESS_KEYS}
)


@dataclass(frozen=True, slots=True)
class FlowMappedExecutionPolicy:
    version: Literal[1] = MAPPED_EXECUTION_STORAGE_VERSION
    max_provider_calls_per_mapped_step: int | None = None
    max_estimated_input_tokens_per_mapped_step: int | None = None


class FlowMappedExecutionPolicySource(Protocol):
    async def get_mapped_execution_policy_resolved(
        self,
    ) -> FlowMappedExecutionPolicy: ...


async def resolve_flow_mapped_execution_policy_from_source(
    source: FlowMappedExecutionPolicySource | None,
) -> FlowMappedExecutionPolicy:
    if source is not None:
        return await source.get_mapped_execution_policy_resolved()
    return resolve_flow_mapped_execution_policy(None)


def _parse_positive_int(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise BadRequestException(
            f"{field_name} must be an integer.",
            code="flow_mapped_execution_policy_invalid",
        )
    if value < 1:
        raise BadRequestException(
            f"{field_name} must be greater than zero.",
            code="flow_mapped_execution_policy_invalid",
        )
    return value


def validate_flow_mapped_execution_policy_object(policy: object) -> dict[str, Any]:
    if not isinstance(policy, dict):
        raise BadRequestException(
            "flow_settings.mapped_execution must be an object.",
            code="flow_mapped_execution_policy_invalid",
        )
    policy_dict = cast(dict[str, Any], policy)
    unknown = set(policy_dict) - MAPPED_EXECUTION_KEYS
    if unknown:
        raise BadRequestException(
            "Unsupported mapped execution policy fields: " + ", ".join(sorted(unknown)),
            code="flow_mapped_execution_policy_unknown_field",
        )
    version = policy_dict.get(
        MAPPED_EXECUTION_VERSION_KEY, MAPPED_EXECUTION_STORAGE_VERSION
    )
    if type(version) is not int or version != MAPPED_EXECUTION_STORAGE_VERSION:
        raise BadRequestException(
            "flow_settings.mapped_execution.version must be 1.",
            code="flow_mapped_execution_policy_version_unsupported",
        )
    for field_name in MAPPED_EXECUTION_BUSINESS_KEYS:
        if field_name in policy_dict:
            _parse_positive_int(policy_dict[field_name], field_name)
    return policy_dict


def _extract_mapped_execution_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}
    raw = tenant_flow_settings.get(MAPPED_EXECUTION_SETTINGS_KEY)
    if not isinstance(raw, dict):
        return {}
    raw_dict = cast(dict[str, Any], raw)
    try:
        return validate_flow_mapped_execution_policy_object(raw_dict)
    except BadRequestException:
        return {}


def resolve_flow_mapped_execution_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> FlowMappedExecutionPolicy:
    raw = _extract_mapped_execution_policy(tenant_flow_settings)
    max_calls = raw.get(MAPPED_EXECUTION_MAX_CALLS_KEY)
    max_tokens = raw.get(MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY)
    return FlowMappedExecutionPolicy(
        max_provider_calls_per_mapped_step=(
            _parse_positive_int(max_calls, MAPPED_EXECUTION_MAX_CALLS_KEY)
            if max_calls is not None
            else None
        ),
        max_estimated_input_tokens_per_mapped_step=(
            _parse_positive_int(max_tokens, MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY)
            if max_tokens is not None
            else None
        ),
    )


def apply_flow_mapped_execution_policy_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    max_provider_calls_per_mapped_step: int | None = None,
    max_estimated_input_tokens_per_mapped_step: int | None = None,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    result = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    next_policy = _extract_mapped_execution_policy(result)
    updates = {
        MAPPED_EXECUTION_MAX_CALLS_KEY: max_provider_calls_per_mapped_step,
        MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY: max_estimated_input_tokens_per_mapped_step,
    }
    for field_name, value in updates.items():
        if value is not None:
            next_policy[field_name] = _parse_positive_int(value, field_name)
    for field_name in remove_keys or ():
        if field_name not in MAPPED_EXECUTION_BUSINESS_KEYS:
            raise BadRequestException(
                f"Unsupported mapped execution policy field: {field_name}.",
                code="flow_mapped_execution_policy_unknown_field",
            )
        next_policy.pop(field_name, None)
    if any(field_name in next_policy for field_name in MAPPED_EXECUTION_BUSINESS_KEYS):
        next_policy[MAPPED_EXECUTION_VERSION_KEY] = MAPPED_EXECUTION_STORAGE_VERSION
        validate_flow_mapped_execution_policy_object(next_policy)
        result[MAPPED_EXECUTION_SETTINGS_KEY] = next_policy
    else:
        result.pop(MAPPED_EXECUTION_SETTINGS_KEY, None)
    return result


def effective_mapped_cardinality(
    *,
    published_max: int | None,
    mapped_policy: FlowMappedExecutionPolicy,
    input_max_files: int | None = None,
) -> int:
    if published_max is None:
        raise BadRequestException(
            "Mapped execution requires an explicit published cardinality ceiling.",
            code="flow_mapped_execution_published_ceiling_required",
        )
    bounds = [published_max]
    if mapped_policy.max_provider_calls_per_mapped_step is not None:
        bounds.append(mapped_policy.max_provider_calls_per_mapped_step)
    if input_max_files is not None:
        bounds.append(input_max_files)
    return min(bounds)
