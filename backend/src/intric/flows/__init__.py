from importlib import import_module
from typing import TYPE_CHECKING

from intric.flows.domain.flow import (
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
from intric.flows.infrastructure.flow_repo import FlowRepository
from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository
from intric.flows.variable_resolver import FlowVariableResolver, iter_template_expressions

_LAZY_EXPORTS = {
    "FlowRunService": ("intric.flows.application.flow_run_service", "FlowRunService"),
    "FlowService": ("intric.flows.application.flow_service", "FlowService"),
    "flow_file_upload_service": ("intric.flows.flow_file_upload_service", None),
    "flow_run_service": ("intric.flows.application.flow_run_service", None),
    "flow_service": ("intric.flows.application.flow_service", None),
}

if TYPE_CHECKING:
    from intric.flows.application.flow_run_service import FlowRunService
    from intric.flows.application.flow_service import FlowService
    from intric.flows import flow_file_upload_service
    from intric.flows.application import flow_run_service, flow_service

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
