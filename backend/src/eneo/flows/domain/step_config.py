from __future__ import annotations

from eneo.flows.domain.flow import FlowPersistedJsonObject, FlowStep
from eneo.flows.http_transport.authored_config import HttpAuthoredConfig

_HTTP_CONFIG_KEYS = frozenset(HttpAuthoredConfig.model_fields)
_TEMPLATE_CONFIG_KEYS = frozenset(
    {
        "template_asset_id",
        "template_file_id",
        "template_name",
        "template_checksum",
        "placeholders",
        "bindings",
    }
)


def clean_inactive_step_config(step: FlowStep) -> FlowStep:
    """Drop only configuration owned by modes the step no longer uses."""
    input_keys = (
        _HTTP_CONFIG_KEYS if step.input_source != "http_get" else frozenset[str]()
    )
    output_keys = (
        _HTTP_CONFIG_KEYS if step.output_mode != "http_post" else frozenset[str]()
    )
    if step.output_mode != "template_fill":
        output_keys = output_keys | _TEMPLATE_CONFIG_KEYS
    return step.model_copy(
        deep=True,
        update={
            "input_config": _without_keys(step.input_config, input_keys),
            "output_config": _without_keys(step.output_config, output_keys),
        },
    )


def _without_keys(
    config: FlowPersistedJsonObject | None, keys: frozenset[str]
) -> FlowPersistedJsonObject | None:
    if config is None or not keys.intersection(config):
        return config
    return {key: value for key, value in config.items() if key not in keys} or None
