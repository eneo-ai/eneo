from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from eneo.main.exceptions import BadRequestException

FLOW_INPUT_MIN_LIMIT_BYTES = 1
FLOW_INPUT_MAX_LIMIT_BYTES = 2 * 1024**3
FLOW_INPUT_MAX_FILES_COUNT = 1000
FLOW_INPUT_MAX_AUDIO_FILES_COUNT = 100

DEFAULT_MAX_AUDIO_FILES_PER_RUN = 10


@dataclass(frozen=True)
class FlowInputLimits:
    file_max_size_bytes: int
    audio_max_size_bytes: int
    max_files_per_run: int | None = None  # None = unlimited
    audio_max_files_per_run: int | None = DEFAULT_MAX_AUDIO_FILES_PER_RUN


FLOW_INPUT_LIMIT_KEYS = frozenset(FlowInputLimits.__dataclass_fields__)


@dataclass(frozen=True)
class FlowRuntimeUploadPolicy:
    min_timeout_seconds: int = 120
    seconds_per_mebibyte: int = 8
    max_timeout_seconds: int = 600
    idle_timeout_seconds: int = 120


class FlowInputLimitsSource(Protocol):
    async def get_flow_input_limits_resolved(self) -> FlowInputLimits: ...


class FlowInputLimitDefaults(Protocol):
    @property
    def session_file_maximum_bytes(self) -> int: ...

    @property
    def session_audio_maximum_bytes(self) -> int: ...


async def resolve_flow_input_limits_from_source(
    source: FlowInputLimitsSource | None,
) -> FlowInputLimits:
    if source is None:
        raise RuntimeError("A Flow input limits source is required")
    return await source.get_flow_input_limits_resolved()


def _default_limits(defaults: FlowInputLimitDefaults | None) -> FlowInputLimits:
    if defaults is None:
        raise RuntimeError("Flow input limit defaults are required")
    return FlowInputLimits(
        file_max_size_bytes=defaults.session_file_maximum_bytes,
        audio_max_size_bytes=defaults.session_audio_maximum_bytes,
        max_files_per_run=None,
        audio_max_files_per_run=DEFAULT_MAX_AUDIO_FILES_PER_RUN,
    )


def _parse_limit(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(f"{field_name} must be an integer.")

    if value < FLOW_INPUT_MIN_LIMIT_BYTES or value > FLOW_INPUT_MAX_LIMIT_BYTES:
        raise BadRequestException(
            f"{field_name} must be between "
            f"{FLOW_INPUT_MIN_LIMIT_BYTES} and {FLOW_INPUT_MAX_LIMIT_BYTES} bytes."
        )

    return value


def _parse_optional_file_count(value: Any, field_name: str, max_bound: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(f"{field_name} must be an integer.")
    if value < 1 or value > max_bound:
        raise BadRequestException(f"{field_name} must be between 1 and {max_bound}.")
    return value


def _extract_input_limits(
    tenant_flow_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}

    input_limits = tenant_flow_settings.get("input_limits")
    if not isinstance(input_limits, dict):
        return {}

    return dict(cast(dict[str, Any], input_limits))


def validate_flow_input_limits_object(input_limits: Any) -> dict[str, Any]:
    if not isinstance(input_limits, dict):
        raise BadRequestException("flow_settings.input_limits must be an object")

    input_limits_dict = cast(dict[str, Any], input_limits)
    unknown_fields = set(input_limits_dict) - FLOW_INPUT_LIMIT_KEYS
    if unknown_fields:
        unknown = ", ".join(sorted(unknown_fields))
        raise BadRequestException(
            f"flow_settings.input_limits contains unknown fields: {unknown}"
        )

    for key in ("file_max_size_bytes", "audio_max_size_bytes"):
        if key not in input_limits_dict:
            continue
        _parse_limit(input_limits_dict[key], key)

    count_bounds = {
        "max_files_per_run": FLOW_INPUT_MAX_FILES_COUNT,
        "audio_max_files_per_run": FLOW_INPUT_MAX_AUDIO_FILES_COUNT,
    }
    for key, max_bound in count_bounds.items():
        if key not in input_limits_dict:
            continue
        value = input_limits_dict[key]
        if value is None:
            continue
        _parse_optional_file_count(value, key, max_bound)

    return input_limits_dict


def resolve_flow_input_limits(
    tenant_flow_settings: dict[str, Any] | None,
    *,
    defaults: FlowInputLimitDefaults | None = None,
) -> FlowInputLimits:
    """Resolve tenant policy beneath the current upload-admission ceiling."""
    resolved_defaults = _default_limits(defaults)
    input_limits = _extract_input_limits(tenant_flow_settings)

    file_limit = resolved_defaults.file_max_size_bytes
    audio_limit = resolved_defaults.audio_max_size_bytes

    if "file_max_size_bytes" in input_limits:
        file_limit = min(
            _parse_limit(input_limits["file_max_size_bytes"], "file_max_size_bytes"),
            resolved_defaults.file_max_size_bytes,
        )

    if "audio_max_size_bytes" in input_limits:
        audio_limit = min(
            _parse_limit(input_limits["audio_max_size_bytes"], "audio_max_size_bytes"),
            resolved_defaults.audio_max_size_bytes,
        )

    max_files = resolved_defaults.max_files_per_run
    audio_max_files = resolved_defaults.audio_max_files_per_run

    if "max_files_per_run" in input_limits:
        raw = input_limits["max_files_per_run"]
        if raw is None:
            max_files = None  # explicit null means unlimited
        else:
            max_files = _parse_optional_file_count(
                raw, "max_files_per_run", FLOW_INPUT_MAX_FILES_COUNT
            )

    if "audio_max_files_per_run" in input_limits:
        raw = input_limits["audio_max_files_per_run"]
        if raw is None:
            audio_max_files = None
        else:
            audio_max_files = _parse_optional_file_count(
                raw, "audio_max_files_per_run", FLOW_INPUT_MAX_AUDIO_FILES_COUNT
            )

    return FlowInputLimits(
        file_max_size_bytes=file_limit,
        audio_max_size_bytes=audio_limit,
        max_files_per_run=max_files,
        audio_max_files_per_run=audio_max_files,
    )


def apply_flow_input_limits_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    file_max_size_bytes: int | None = None,
    audio_max_size_bytes: int | None = None,
    max_files_per_run: int | None = None,
    audio_max_files_per_run: int | None = None,
    remove_keys: set[str] | None = None,
) -> dict[str, Any]:
    """Apply validated partial updates while preserving unrelated flow settings keys.

    When a field is in ``remove_keys``, it is deleted from the JSONB dict
    (reverting to the env-var default on next resolve).
    """
    result = (
        dict(current_flow_settings) if isinstance(current_flow_settings, dict) else {}
    )
    existing_input_limits = _extract_input_limits(result)

    next_input_limits: dict[str, Any] = dict(existing_input_limits)

    if file_max_size_bytes is not None:
        next_input_limits["file_max_size_bytes"] = _parse_limit(
            file_max_size_bytes, "file_max_size_bytes"
        )
    if audio_max_size_bytes is not None:
        next_input_limits["audio_max_size_bytes"] = _parse_limit(
            audio_max_size_bytes, "audio_max_size_bytes"
        )
    if max_files_per_run is not None:
        next_input_limits["max_files_per_run"] = _parse_optional_file_count(
            max_files_per_run, "max_files_per_run", FLOW_INPUT_MAX_FILES_COUNT
        )
    if audio_max_files_per_run is not None:
        next_input_limits["audio_max_files_per_run"] = _parse_optional_file_count(
            audio_max_files_per_run,
            "audio_max_files_per_run",
            FLOW_INPUT_MAX_AUDIO_FILES_COUNT,
        )

    for key in remove_keys or ():
        next_input_limits.pop(key, None)

    result["input_limits"] = next_input_limits
    return result


def effective_flow_input_limit(*, input_type: str, limits: FlowInputLimits) -> int:
    if input_type == "audio":
        return limits.audio_max_size_bytes
    return limits.file_max_size_bytes


def effective_runtime_upload_policy() -> FlowRuntimeUploadPolicy:
    return FlowRuntimeUploadPolicy()


def effective_max_files_per_run(
    *, input_type: str, limits: FlowInputLimits
) -> int | None:
    if input_type == "audio":
        return limits.audio_max_files_per_run
    return limits.max_files_per_run


def effective_runtime_max_files(
    *,
    input_type: str,
    step_max_files: int | None,
    limits: FlowInputLimits,
) -> int | None:
    """Apply the stricter of a step limit and the tenant flow-input ceiling."""

    tenant_limit = effective_max_files_per_run(input_type=input_type, limits=limits)
    if step_max_files is None:
        return tenant_limit
    if tenant_limit is None:
        return step_max_files
    return min(step_max_files, tenant_limit)
