from importlib import import_module

from intric.flows.flow import (
    Flow,
    FlowRun,
    FlowRunStatus,
    FlowSparse,
    FlowStep,
    FlowStepAttempt,
    FlowStepAttemptStatus,
    FlowStepResult,
    FlowStepResultStatus,
    FlowVersion,
)
from intric.flows.execution_backend import FlowExecutionBackend
from intric.flows.flow_factory import FlowFactory
from intric.flows.flow_repo import FlowRepository
from intric.flows.flow_run_repo import FlowRunRepository
from intric.flows.flow_version_repo import FlowVersionRepository
from intric.flows.variable_resolver import FlowVariableResolver, iter_template_expressions

_LAZY_EXPORTS = {
    "FlowRunService": ("intric.flows.flow_run_service", "FlowRunService"),
    "FlowService": ("intric.flows.flow_service", "FlowService"),
    "flow_file_upload_service": ("intric.flows.flow_file_upload_service", None),
    "flow_run_service": ("intric.flows.flow_run_service", None),
    "flow_service": ("intric.flows.flow_service", None),
}

__all__ = [
    "Flow",
    "FlowSparse",
    "FlowStep",
    "FlowVersion",
    "FlowRun",
    "FlowRunStatus",
    "FlowStepResult",
    "FlowStepResultStatus",
    "FlowStepAttempt",
    "FlowStepAttemptStatus",
    "FlowFactory",
    "FlowExecutionBackend",
    "FlowRepository",
    "FlowRunRepository",
    "FlowRunService",
    "FlowVersionRepository",
    "FlowService",
    "FlowVariableResolver",
    "flow_file_upload_service",
    "flow_run_service",
    "flow_service",
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
