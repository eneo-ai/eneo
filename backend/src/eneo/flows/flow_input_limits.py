from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, cast

from eneo.files.audio import AudioDecodeLimits
from eneo.main.config import (
    FLOW_AUDIO_MAX_DURATION_BOUND_SECONDS,
    Settings,
    get_settings,
)
from eneo.main.exceptions import BadRequestException

FLOW_INPUT_MIN_LIMIT_BYTES = 1
FLOW_INPUT_MAX_LIMIT_BYTES = 2 * 1024**3
FLOW_INPUT_MAX_FILES_COUNT = 1000
FLOW_INPUT_MAX_AUDIO_FILES_COUNT = 100

DEFAULT_MAX_AUDIO_FILES_PER_RUN = 10
# The shortest longest-recording an admin can set: a minute, the page's unit and
# room for a recorder's margin below it.
FLOW_AUDIO_MIN_DURATION_SECONDS = 60


@dataclass(frozen=True)
class FlowInputLimits:
    file_max_size_bytes: int
    audio_max_size_bytes: int
    max_files_per_run: int | None = FLOW_INPUT_MAX_FILES_COUNT
    audio_max_files_per_run: int = DEFAULT_MAX_AUDIO_FILES_PER_RUN
    # The longest recording, in seconds; None reads the deployment default.
    audio_max_duration_seconds: int | None = None


FLOW_INPUT_LIMIT_KEYS = frozenset(FlowInputLimits.__dataclass_fields__)


@dataclass(frozen=True)
class FlowRuntimeUploadPolicy:
    min_timeout_seconds: int = 120
    seconds_per_mebibyte: int = 8
    max_timeout_seconds: int = 600
    idle_timeout_seconds: int = 120


def audio_duration_ceiling_seconds(settings: Settings | None = None) -> int:
    """The longest recording a tenant admin may set for flows: the deployment's
    flow ceiling, or less when the decoded-byte bound holds less."""
    settings = settings or get_settings()
    return AudioDecodeLimits(
        max_duration_seconds=settings.flow_audio_max_duration_ceiling_seconds,
        max_decoded_bytes=settings.flow_audio_max_decoded_bytes,
    ).longest_audio_seconds


def _default_audio_duration_seconds(settings: Settings | None = None) -> int:
    settings = settings or get_settings()
    return min(
        settings.flow_audio_max_duration_seconds,
        audio_duration_ceiling_seconds(settings),
    )


def flow_audio_decode_limits(
    limits: FlowInputLimits, settings: Settings | None = None
) -> AudioDecodeLimits:
    """What a flow's audio may decode to: the tenant's longest recording and
    the deployment's decoded-byte bound."""
    return AudioDecodeLimits(
        max_duration_seconds=limits.audio_max_duration_seconds
        or _default_audio_duration_seconds(settings),
        max_decoded_bytes=(settings or get_settings()).flow_audio_max_decoded_bytes,
    )


class FlowInputLimitsSource(Protocol):
    async def get_flow_input_limits_resolved(self) -> FlowInputLimits: ...


class FlowInputLimitDefaults(Protocol):
    @property
    def session_file_maximum_bytes(self) -> int: ...

    @property
    def session_audio_maximum_bytes(self) -> int: ...


def effective_upload_ceiling_bytes(admission_ceiling_bytes: int) -> int:
    """The actual writable bound for a tenant upload limit: the deployment
    admission ceiling capped by the flow-input hard maximum, so the exposed
    ceiling can never advertise values the update path rejects."""
    return min(admission_ceiling_bytes, FLOW_INPUT_MAX_LIMIT_BYTES)


async def resolve_flow_input_limits_from_source(
    source: FlowInputLimitsSource | None,
) -> FlowInputLimits:
    if source is None:
        raise RuntimeError("A Flow input limits source is required")
    return await source.get_flow_input_limits_resolved()


def _default_limits(defaults: FlowInputLimitDefaults | None) -> FlowInputLimits:
    if defaults is None:
        raise RuntimeError("Flow input limit defaults are required")
    # Admission may admit more than the flow-input hard cap; the resolved
    # defaults must stay within the writable bound.
    return FlowInputLimits(
        file_max_size_bytes=effective_upload_ceiling_bytes(
            defaults.session_file_maximum_bytes
        ),
        audio_max_size_bytes=effective_upload_ceiling_bytes(
            defaults.session_audio_maximum_bytes
        ),
        max_files_per_run=FLOW_INPUT_MAX_FILES_COUNT,
        audio_max_files_per_run=DEFAULT_MAX_AUDIO_FILES_PER_RUN,
        audio_max_duration_seconds=_default_audio_duration_seconds(),
    )


def _parse_duration(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(f"{field_name} must be an integer.")
    if (
        value < FLOW_AUDIO_MIN_DURATION_SECONDS
        or value > FLOW_AUDIO_MAX_DURATION_BOUND_SECONDS
    ):
        raise BadRequestException(
            f"{field_name} must be between {FLOW_AUDIO_MIN_DURATION_SECONDS} and "
            f"{FLOW_AUDIO_MAX_DURATION_BOUND_SECONDS} seconds."
        )
    return value


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
    if "audio_max_duration_seconds" in input_limits_dict:
        _parse_duration(
            input_limits_dict["audio_max_duration_seconds"],
            "audio_max_duration_seconds",
        )

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
            max_files = FLOW_INPUT_MAX_FILES_COUNT
        else:
            max_files = _parse_optional_file_count(
                raw, "max_files_per_run", FLOW_INPUT_MAX_FILES_COUNT
            )

    if "audio_max_files_per_run" in input_limits:
        raw = input_limits["audio_max_files_per_run"]
        if raw is not None:
            audio_max_files = _parse_optional_file_count(
                raw, "audio_max_files_per_run", FLOW_INPUT_MAX_AUDIO_FILES_COUNT
            )

    audio_duration = resolved_defaults.audio_max_duration_seconds
    if "audio_max_duration_seconds" in input_limits:
        audio_duration = min(
            _parse_duration(
                input_limits["audio_max_duration_seconds"], "audio_max_duration_seconds"
            ),
            audio_duration_ceiling_seconds(),
        )

    return FlowInputLimits(
        file_max_size_bytes=file_limit,
        audio_max_size_bytes=audio_limit,
        max_files_per_run=max_files,
        audio_max_files_per_run=audio_max_files,
        audio_max_duration_seconds=audio_duration,
    )


def apply_flow_input_limits_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    file_max_size_bytes: int | None = None,
    audio_max_size_bytes: int | None = None,
    max_files_per_run: int | None = None,
    audio_max_files_per_run: int | None = None,
    audio_max_duration_seconds: int | None = None,
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

    if audio_max_duration_seconds is not None:
        next_input_limits["audio_max_duration_seconds"] = _parse_duration(
            audio_max_duration_seconds, "audio_max_duration_seconds"
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


def effective_max_files_per_run(*, input_type: str, limits: FlowInputLimits) -> int:
    if input_type == "audio":
        return limits.audio_max_files_per_run
    return min(
        limits.max_files_per_run
        if limits.max_files_per_run is not None
        else FLOW_INPUT_MAX_FILES_COUNT,
        FLOW_INPUT_MAX_FILES_COUNT,
    )


def effective_runtime_max_files(
    *,
    input_type: str,
    step_max_files: int | None,
    limits: FlowInputLimits,
) -> int:
    """Apply the stricter of a step limit and the tenant flow-input ceiling."""

    tenant_limit = effective_max_files_per_run(input_type=input_type, limits=limits)
    if step_max_files is None:
        return tenant_limit
    return min(step_max_files, tenant_limit)
