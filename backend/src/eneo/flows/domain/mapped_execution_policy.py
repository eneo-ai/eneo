"""Tenant policy and effective bounds for mapped Flow execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal, Protocol, cast

from eneo.main.config import get_settings
from eneo.main.exceptions import BadRequestException
from eneo.main.logging import get_logger

logger = get_logger(__name__)

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

# Runtime admission may add one native-JSON fallback provider call on top of the
# per-item calls, so item ceilings derived from the call ceiling reserve it and
# an enabled ceiling must be at least 2 to admit a single item.
MAPPED_FALLBACK_RESERVED_CALLS: Final[int] = 1
MAPPED_EXECUTION_MIN_CALL_CEILING: Final[int] = 2


class _UseDeploymentDefault:
    """Sentinel type: caller did not override the deployment default."""


USE_DEPLOYMENT_DEFAULT: Final = _UseDeploymentDefault()


@dataclass(frozen=True, slots=True)
class FlowMappedExecutionPolicy:
    version: Literal[1] = MAPPED_EXECUTION_STORAGE_VERSION
    max_provider_calls_per_mapped_step: int | None = None
    max_estimated_input_tokens_per_mapped_step: int | None = None

    def __post_init__(self) -> None:
        calls = self.max_provider_calls_per_mapped_step
        if calls is not None and calls < MAPPED_EXECUTION_MIN_CALL_CEILING:
            raise ValueError(
                "max_provider_calls_per_mapped_step must be at least "
                f"{MAPPED_EXECUTION_MIN_CALL_CEILING} or None."
            )
        tokens = self.max_estimated_input_tokens_per_mapped_step
        if tokens is not None and tokens < 1:
            raise ValueError(
                "max_estimated_input_tokens_per_mapped_step must be positive or None."
            )


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
    # A present call-ceiling key holding null is an explicit organization
    # decision: it turns the ceiling off (blocking new mapped authoring)
    # instead of inheriting the deployment default that applies while the key
    # is absent. The token ceiling has no null semantics; its absent-key state
    # is the only unset representation.
    if MAPPED_EXECUTION_MAX_CALLS_KEY in policy_dict:
        stored_calls = policy_dict[MAPPED_EXECUTION_MAX_CALLS_KEY]
        if stored_calls is not None:
            parsed_calls = _parse_positive_int(
                stored_calls, MAPPED_EXECUTION_MAX_CALLS_KEY
            )
            if parsed_calls < MAPPED_EXECUTION_MIN_CALL_CEILING:
                raise BadRequestException(
                    f"{MAPPED_EXECUTION_MAX_CALLS_KEY} must be at least "
                    f"{MAPPED_EXECUTION_MIN_CALL_CEILING}: one provider call "
                    "stays reserved for the native-JSON fallback.",
                    code="flow_mapped_execution_policy_invalid",
                )
    if MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY in policy_dict:
        stored_tokens = policy_dict[MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY]
        if stored_tokens is None:
            raise BadRequestException(
                f"{MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY} cannot be stored as "
                "null; remove the key instead.",
                code="flow_mapped_execution_policy_invalid",
            )
        _parse_positive_int(stored_tokens, MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY)
    return policy_dict


def _extract_mapped_execution_policy(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Return the validated stored policy, ``{}`` when absent, ``None`` when
    the stored object is invalid — so corrupt state stays distinguishable from
    an organization that never configured anything."""
    if not isinstance(tenant_flow_settings, dict):
        return {}
    if MAPPED_EXECUTION_SETTINGS_KEY not in tenant_flow_settings:
        return {}
    raw = tenant_flow_settings[MAPPED_EXECUTION_SETTINGS_KEY]
    if not isinstance(raw, dict):
        # A present null/scalar/list envelope was never written by this code;
        # treat it as corrupt so resolution fails closed.
        return None
    raw_dict = cast(dict[str, Any], raw)
    try:
        return validate_flow_mapped_execution_policy_object(raw_dict)
    except BadRequestException:
        return None


def resolve_flow_mapped_execution_policy(
    tenant_flow_settings: dict[str, Any] | None,
    *,
    default_max_provider_calls: int | None | _UseDeploymentDefault = (
        USE_DEPLOYMENT_DEFAULT
    ),
) -> FlowMappedExecutionPolicy:
    """Resolve the organization policy over the deployment default.

    The call ceiling is tri-state: an absent key inherits the deployment
    default (``flow_mapped_step_max_provider_calls_default``), a stored integer
    is the organization's own ceiling, and a stored null is an explicit
    organization opt-out that blocks new mapped authoring regardless of the
    deployment default. This resolver owns the deployment fallback; the keyword
    exists for tests and callers that must pin a different default.

    An invalid stored policy fails closed: the call ceiling resolves to null
    (blocking new mapped authoring) rather than silently inheriting the
    deployment default.
    """
    resolved_default: int | None
    if isinstance(default_max_provider_calls, _UseDeploymentDefault):
        resolved_default = get_settings().flow_mapped_step_max_provider_calls_default
    else:
        resolved_default = default_max_provider_calls
    if (
        resolved_default is not None
        and resolved_default < MAPPED_EXECUTION_MIN_CALL_CEILING
    ):
        logger.warning(
            "Ignoring mapped-call deployment default below the minimum ceiling.",
            extra={"default_max_provider_calls": resolved_default},
        )
        resolved_default = None
    raw = _extract_mapped_execution_policy(tenant_flow_settings)
    if raw is None:
        logger.warning(
            "Stored mapped execution policy is invalid; failing closed with a "
            "null call ceiling.",
            extra={"flow_settings_key": MAPPED_EXECUTION_SETTINGS_KEY},
        )
        return FlowMappedExecutionPolicy(
            max_provider_calls_per_mapped_step=None,
            max_estimated_input_tokens_per_mapped_step=None,
        )
    if MAPPED_EXECUTION_MAX_CALLS_KEY in raw:
        stored_calls = raw[MAPPED_EXECUTION_MAX_CALLS_KEY]
        max_calls = (
            _parse_positive_int(stored_calls, MAPPED_EXECUTION_MAX_CALLS_KEY)
            if stored_calls is not None
            else None
        )
    else:
        max_calls = resolved_default
    max_tokens = raw.get(MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY)
    return FlowMappedExecutionPolicy(
        max_provider_calls_per_mapped_step=max_calls,
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
    disable_max_provider_calls: bool = False,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Apply an admin patch to the stored mapped-execution policy.

    ``disable_max_provider_calls`` stores an explicit null call ceiling (an
    organization opt-out that the resolver never overrides with the deployment
    default), while ``remove_keys`` deletes a key so its absent-key state
    applies again.
    """
    result = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    extracted = _extract_mapped_execution_policy(result)
    if extracted is None:
        logger.warning(
            "Replacing invalid stored mapped execution policy with the "
            "incoming admin patch.",
            extra={"flow_settings_key": MAPPED_EXECUTION_SETTINGS_KEY},
        )
        extracted = {}
    next_policy = extracted
    updates = {
        MAPPED_EXECUTION_MAX_CALLS_KEY: max_provider_calls_per_mapped_step,
        MAPPED_EXECUTION_MAX_INPUT_TOKENS_KEY: max_estimated_input_tokens_per_mapped_step,
    }
    for field_name, value in updates.items():
        if value is not None:
            next_policy[field_name] = _parse_positive_int(value, field_name)
    if disable_max_provider_calls:
        next_policy[MAPPED_EXECUTION_MAX_CALLS_KEY] = None
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


MappedCallCeilingSource = Literal[
    "deployment_default", "organization", "organization_disabled", "invalid"
]


def mapped_call_ceiling_source(
    tenant_flow_settings: dict[str, Any] | None,
) -> MappedCallCeilingSource:
    """Where the resolved call ceiling comes from.

    ``deployment_default`` — no stored organization value (the deployment
    fallback, possibly unset, applies); ``organization`` — a stored ceiling;
    ``organization_disabled`` — a stored explicit opt-out; ``invalid`` —
    corrupt stored state that resolution fails closed on and an administrator
    should repair by saving a value or restoring the default.
    """
    raw = _extract_mapped_execution_policy(tenant_flow_settings)
    if raw is None:
        return "invalid"
    if MAPPED_EXECUTION_MAX_CALLS_KEY not in raw:
        return "deployment_default"
    if raw[MAPPED_EXECUTION_MAX_CALLS_KEY] is None:
        return "organization_disabled"
    return "organization"


def max_mapped_items_per_step(policy: FlowMappedExecutionPolicy) -> int | None:
    """Largest per-step item count the call ceiling can guarantee to admit.

    Runtime admission counts one reserved native-JSON fallback call on top of
    the per-item calls, so the item ceiling stays one below the call ceiling.
    Every enabled ceiling is validated to be at least
    ``MAPPED_EXECUTION_MIN_CALL_CEILING``, so the result is always >= 1.
    """
    calls = policy.max_provider_calls_per_mapped_step
    if calls is None:
        return None
    return calls - MAPPED_FALLBACK_RESERVED_CALLS


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
    policy_items = max_mapped_items_per_step(mapped_policy)
    if policy_items is not None:
        bounds.append(policy_items)
    if input_max_files is not None:
        bounds.append(input_max_files)
    return min(bounds)
