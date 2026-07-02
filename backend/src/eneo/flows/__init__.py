from importlib import import_module
from typing import TYPE_CHECKING

_LAZY_EXPORTS = {
    "FlowExecutionBackend": ("eneo.flows.execution_backend", "FlowExecutionBackend"),
    "FlowFactory": ("eneo.flows.flow_factory", "FlowFactory"),
    "FlowRepository": ("eneo.flows.infrastructure.flow_repo", "FlowRepository"),
    "FlowRunRepository": (
        "eneo.flows.infrastructure.flow_run_repo",
        "FlowRunRepository",
    ),
    "FlowRunService": ("eneo.flows.application.flow_run_service", "FlowRunService"),
    "FlowService": ("eneo.flows.application.flow_service", "FlowService"),
    "FlowVersionRepository": (
        "eneo.flows.infrastructure.flow_version_repo",
        "FlowVersionRepository",
    ),
    "ai_builder": ("eneo.flows.ai_builder", None),
    "flow_runtime_file_service": ("eneo.flows.flow_runtime_file_service", None),
    "flow_input_limits": ("eneo.flows.flow_input_limits", None),
    "FlowVariableResolver": (
        "eneo.flows.variable_resolver",
        "FlowVariableResolver",
    ),
    "iter_template_expressions": (
        "eneo.flows.variable_resolver",
        "iter_template_expressions",
    ),
}

if TYPE_CHECKING:
    from eneo.flows import ai_builder, flow_input_limits, flow_runtime_file_service
    from eneo.flows.application.flow_run_service import FlowRunService
    from eneo.flows.application.flow_service import FlowService
    from eneo.flows.execution_backend import FlowExecutionBackend
    from eneo.flows.flow_factory import FlowFactory
    from eneo.flows.infrastructure.flow_repo import FlowRepository
    from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
    from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
    from eneo.flows.variable_resolver import (
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
