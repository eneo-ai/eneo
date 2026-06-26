from importlib import import_module
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "FlowExecutionBackend": ("intric.flows.execution_backend", "FlowExecutionBackend"),
    "FlowFactory": ("intric.flows.flow_factory", "FlowFactory"),
    "FlowRepository": ("intric.flows.infrastructure.flow_repo", "FlowRepository"),
    "FlowRunRepository": (
        "intric.flows.infrastructure.flow_run_repo",
        "FlowRunRepository",
    ),
    "FlowRunService": ("intric.flows.application.flow_run_service", "FlowRunService"),
    "FlowService": ("intric.flows.application.flow_service", "FlowService"),
    "FlowVersionRepository": (
        "intric.flows.infrastructure.flow_version_repo",
        "FlowVersionRepository",
    ),
    "ai_builder": ("intric.flows.ai_builder", None),
    "flow_runtime_file_service": ("intric.flows.flow_runtime_file_service", None),
    "flow_input_limits": ("intric.flows.flow_input_limits", None),
    "FlowVariableResolver": (
        "intric.flows.variable_resolver",
        "FlowVariableResolver",
    ),
    "iter_template_expressions": (
        "intric.flows.variable_resolver",
        "iter_template_expressions",
    ),
}

if TYPE_CHECKING:
    from intric.flows import ai_builder, flow_input_limits, flow_runtime_file_service
    from intric.flows.application.flow_run_service import FlowRunService
    from intric.flows.application.flow_service import FlowService
    from intric.flows.execution_backend import FlowExecutionBackend
    from intric.flows.flow_factory import FlowFactory
    from intric.flows.infrastructure.flow_repo import FlowRepository
    from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
    from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
    from intric.flows.variable_resolver import (
        FlowVariableResolver,
        iter_template_expressions,
    )

__all__ = [
    "FlowFactory",
    "FlowExecutionBackend",
    "FlowRepository",
    "FlowRunRepository",
    "FlowRunService",
    "FlowVersionRepository",
    "FlowService",
    "FlowVariableResolver",
    "ai_builder",
    "flow_runtime_file_service",
    "flow_input_limits",
    "iter_template_expressions",
]


def __getattr__(name: str):
    try:
        module_name, attr_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value
