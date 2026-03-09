from __future__ import annotations

from typing import Any

from intric.files.audio import AudioMimeTypes
from intric.files.text import TextMimeTypes
from intric.flows.flow import FlowRuntimeInputConfig
from intric.main.exceptions import BadRequestException

_DEFAULT_RUNTIME_LABEL = "Indata"


def parse_runtime_input_config(input_config: dict[str, Any] | None) -> FlowRuntimeInputConfig:
    if not isinstance(input_config, dict):
        return FlowRuntimeInputConfig()

    raw_runtime_input = input_config.get("runtime_input")
    if raw_runtime_input in (None, False):
        return FlowRuntimeInputConfig()
    if raw_runtime_input is True:
        return FlowRuntimeInputConfig(enabled=True)
    if not isinstance(raw_runtime_input, dict):
        raise BadRequestException("Step input_config.runtime_input must be an object.")

    try:
        parsed = FlowRuntimeInputConfig.model_validate(raw_runtime_input)
    except Exception as exc:
        raise BadRequestException("Step input_config.runtime_input is invalid.") from exc

    if parsed.max_files is not None and parsed.max_files <= 0:
        raise BadRequestException("Step input_config.runtime_input.max_files must be greater than zero.")

    return parsed


def build_runtime_input_config(
    step_input_config: dict[str, Any] | None,
    *,
    default_required: bool = False,
) -> FlowRuntimeInputConfig:
    config = parse_runtime_input_config(step_input_config)
    if not config.enabled:
        return config
    if config.label is None:
        config = config.model_copy(update={"label": _DEFAULT_RUNTIME_LABEL})
    if default_required and not config.required:
        config = config.model_copy(update={"required": True})
    return config


def runtime_input_accept_mimetypes(config: FlowRuntimeInputConfig) -> list[str]:
    if config.accepted_mimetypes_override:
        return list(config.accepted_mimetypes_override)
    if config.input_format == "audio":
        return AudioMimeTypes.values()
    return TextMimeTypes.values()
