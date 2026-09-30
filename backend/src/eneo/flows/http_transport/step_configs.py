from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from eneo.flows.domain.flow_step_validation import (
    FlowGraphIssueCode,
    FlowStepValidationError,
)
from eneo.flows.enums import FlowInputSource, FlowOutputMode
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.http_transport.authored_config import HttpAuthoredConfig
from eneo.flows.http_transport.normalizer import parse_authored_http_config
from eneo.main.exceptions import TypedIOValidationException

HttpConfigColumn = Literal["input_config", "output_config"]


def sends_http_config(
    column: HttpConfigColumn,
    input_source: FlowInputSource | str,
    output_mode: FlowOutputMode | str,
    config: Mapping[str, object] | None = None,
) -> bool:
    """Whether a step sends an HTTP request from ``column``: the input of an
    ``http_get`` step, the output of an ``http_post`` step (which sends nothing
    without a config). The one owner of which column is HTTP for which mode."""
    if column == "input_config":
        return FlowInputSource(input_source) is FlowInputSource.HTTP_GET
    return (
        FlowOutputMode(output_mode) is FlowOutputMode.HTTP_POST and config is not None
    )


def sent_step_http_configs(
    *,
    step_order: int,
    input_source: FlowInputSource | str,
    output_mode: FlowOutputMode | str,
    input_config: Mapping[str, object] | None,
    output_config: Mapping[str, object] | None,
) -> tuple[tuple[str, HttpAuthoredConfig], ...]:
    """The stored HTTP configs a step sends from, parsed as the runtime parses them.

    Only the configuration of a mode the step runs is sent: the input of an
    ``http_get`` step, the output of an ``http_post`` step (which sends nothing
    without one). A config the runtime would reject raises a step-scoped
    ``FlowStepValidationError`` with ``typed_io_http_invalid_config``, naming the
    field and never the value.
    """
    candidates: tuple[tuple[HttpConfigColumn, Mapping[str, object] | None], ...] = (
        ("input_config", input_config),
        ("output_config", output_config),
    )
    configs: list[tuple[str, HttpAuthoredConfig]] = []
    for label, config in candidates:
        if not sends_http_config(label, input_source, output_mode, config):
            continue
        try:
            parsed = parse_authored_http_config(
                config, step_order=step_order, config_label=label
            )
        except TypedIOValidationException as exc:
            raise _step_error(
                str(exc), step_order=step_order, field=_field_of(exc, default=label)
            ) from None
        configs.append((label, parsed))
    return tuple(configs)


def _field_of(exc: TypedIOValidationException, *, default: str) -> str:
    field = (exc.context or {}).get("field")
    return field if isinstance(field, str) else default


def _step_error(
    message: str, *, step_order: int, field: str
) -> FlowStepValidationError:
    return FlowStepValidationError(
        message,
        step_order=step_order,
        code=FlowApiErrorCode.TYPED_IO_HTTP_INVALID_CONFIG.value,
        context={
            "issue_code": FlowGraphIssueCode.FLOW_STEP_INVALID.value,
            "step_order": step_order,
            "field": field,
        },
    )
