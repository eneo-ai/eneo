from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger

logger = get_logger(__name__)

_MIN_LIMIT_BYTES = 1
_MAX_LIMIT_BYTES = 2 * 1024**3  # 2 GB hard guard against accidental runaway values

DEFAULT_MAX_AUDIO_FILES_PER_RUN = 10
_MAX_FILES_COUNT = 1000  # generic file count guard
_MAX_AUDIO_FILES_COUNT = 100  # audio: tighter due to cost/timeout


@dataclass(frozen=True)
class FlowInputLimits:
    file_max_size_bytes: int
    audio_max_size_bytes: int
    max_files_per_run: int | None = None  # None = unlimited
    audio_max_files_per_run: int | None = DEFAULT_MAX_AUDIO_FILES_PER_RUN


def _default_limits(defaults: Any | None = None) -> FlowInputLimits:
    source = defaults or get_settings()
    return FlowInputLimits(
        file_max_size_bytes=int(source.upload_max_file_size),
        audio_max_size_bytes=int(source.transcription_max_file_size),
        max_files_per_run=None,
        audio_max_files_per_run=DEFAULT_MAX_AUDIO_FILES_PER_RUN,
    )


def _parse_limit(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(f"{field_name} must be an integer.")

    if value < _MIN_LIMIT_BYTES or value > _MAX_LIMIT_BYTES:
        raise BadRequestException(
            f"{field_name} must be between {_MIN_LIMIT_BYTES} and {_MAX_LIMIT_BYTES} bytes."
        )

    return value


def _parse_optional_file_count(value: Any, field_name: str, max_bound: int) -> int:
    """Parse an optional file count value. Returns validated int or raises BadRequestException."""
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(f"{field_name} must be an integer.")
    if value < 1 or value > max_bound:
        raise BadRequestException(
            f"{field_name} must be between 1 and {max_bound}."
        )
    return value


def _extract_input_limits(tenant_flow_settings: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(tenant_flow_settings, dict):
        return {}

    input_limits = tenant_flow_settings.get("input_limits")
    if not isinstance(input_limits, dict):
        return {}

    return input_limits


def resolve_flow_input_limits(
    tenant_flow_settings: dict[str, Any] | None,
    *,
    defaults: Any | None = None,
) -> FlowInputLimits:
    """Resolve effective flow input limits with tolerant fallback behavior."""
    resolved_defaults = _default_limits(defaults)
    input_limits = _extract_input_limits(tenant_flow_settings)

    file_limit = resolved_defaults.file_max_size_bytes
    audio_limit = resolved_defaults.audio_max_size_bytes

    if "file_max_size_bytes" in input_limits:
        try:
            file_limit = _parse_limit(
                input_limits["file_max_size_bytes"], "file_max_size_bytes"
            )
        except BadRequestException:
            logger.warning(
                "Ignoring invalid tenant flow setting: file_max_size_bytes",
                extra={"value": input_limits.get("file_max_size_bytes")},
            )

    if "audio_max_size_bytes" in input_limits:
        try:
            audio_limit = _parse_limit(
                input_limits["audio_max_size_bytes"], "audio_max_size_bytes"
            )
        except BadRequestException:
            logger.warning(
                "Ignoring invalid tenant flow setting: audio_max_size_bytes",
                extra={"value": input_limits.get("audio_max_size_bytes")},
            )

    max_files = resolved_defaults.max_files_per_run
    audio_max_files = resolved_defaults.audio_max_files_per_run

    if "max_files_per_run" in input_limits:
        raw = input_limits["max_files_per_run"]
        if raw is None:
            max_files = None  # explicit null means unlimited
        else:
            try:
                max_files = _parse_optional_file_count(raw, "max_files_per_run", _MAX_FILES_COUNT)
            except BadRequestException:
                logger.warning(
                    "Ignoring invalid tenant flow setting: max_files_per_run",
                    extra={"value": raw},
                )

    if "audio_max_files_per_run" in input_limits:
        raw = input_limits["audio_max_files_per_run"]
        if raw is None:
            audio_max_files = None
        else:
            try:
                audio_max_files = _parse_optional_file_count(
                    raw, "audio_max_files_per_run", _MAX_AUDIO_FILES_COUNT
                )
            except BadRequestException:
                logger.warning(
                    "Ignoring invalid tenant flow setting: audio_max_files_per_run",
                    extra={"value": raw},
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
        dict(current_flow_settings)
        if isinstance(current_flow_settings, dict)
        else {}
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
            max_files_per_run, "max_files_per_run", _MAX_FILES_COUNT
        )
    if audio_max_files_per_run is not None:
        next_input_limits["audio_max_files_per_run"] = _parse_optional_file_count(
            audio_max_files_per_run, "audio_max_files_per_run", _MAX_AUDIO_FILES_COUNT
        )

    for key in remove_keys or ():
        next_input_limits.pop(key, None)

    result["input_limits"] = next_input_limits
    return result


def effective_flow_input_limit(*, input_type: str, limits: FlowInputLimits) -> int:
    if input_type == "audio":
        return limits.audio_max_size_bytes
    return limits.file_max_size_bytes


def effective_max_files_per_run(*, input_type: str, limits: FlowInputLimits) -> int | None:
    if input_type == "audio":
        return limits.audio_max_files_per_run
    return limits.max_files_per_run
