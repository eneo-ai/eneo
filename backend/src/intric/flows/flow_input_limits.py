from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from intric.main.config import get_settings
from intric.main.exceptions import BadRequestException
from intric.main.logging import get_logger

logger = get_logger(__name__)

_MIN_LIMIT_BYTES = 1
_MAX_LIMIT_BYTES = 2 * 1024**3  # 2 GB hard guard against accidental runaway values


@dataclass(frozen=True)
class FlowInputLimits:
    file_max_size_bytes: int
    audio_max_size_bytes: int


def _default_limits(defaults: Any | None = None) -> FlowInputLimits:
    source = defaults or get_settings()
    return FlowInputLimits(
        file_max_size_bytes=int(source.upload_max_file_size),
        audio_max_size_bytes=int(source.transcription_max_file_size),
    )


def _parse_limit(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise BadRequestException(f"{field_name} must be an integer.")

    if value < _MIN_LIMIT_BYTES or value > _MAX_LIMIT_BYTES:
        raise BadRequestException(
            f"{field_name} must be between {_MIN_LIMIT_BYTES} and {_MAX_LIMIT_BYTES} bytes."
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

    return FlowInputLimits(
        file_max_size_bytes=file_limit,
        audio_max_size_bytes=audio_limit,
    )


def apply_flow_input_limits_patch(
    current_flow_settings: dict[str, Any] | None,
    *,
    file_max_size_bytes: int | None = None,
    audio_max_size_bytes: int | None = None,
) -> dict[str, Any]:
    """Apply validated partial updates while preserving unrelated flow settings keys."""
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

    result["input_limits"] = next_input_limits
    return result


def effective_flow_input_limit(*, input_type: str, limits: FlowInputLimits) -> int:
    if input_type == "audio":
        return limits.audio_max_size_bytes
    return limits.file_max_size_bytes
