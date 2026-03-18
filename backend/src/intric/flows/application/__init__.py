from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

_EXPORTS = {
    "dispatch_flow_run_after_commit": (
        "intric.flows.application.flow_dispatch",
        "dispatch_flow_run_after_commit",
    ),
    "FlowRunService": ("intric.flows.application.flow_run_service", "FlowRunService"),
    "FlowService": ("intric.flows.application.flow_service", "FlowService"),
}

__all__ = [
    "dispatch_flow_run_after_commit",
    "FlowRunService",
    "FlowService",
]

if TYPE_CHECKING:
    from intric.flows.application.flow_dispatch import dispatch_flow_run_after_commit
    from intric.flows.application.flow_run_service import FlowRunService
    from intric.flows.application.flow_service import FlowService


def __getattr__(name: str):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
