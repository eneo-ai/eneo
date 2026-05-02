from importlib import import_module
from typing import TYPE_CHECKING

from intric.flows.domain.flow import (
    Flow,
    FlowRun,
    FlowRunReviewCheckpoint,
    FlowRunReviewCheckpointState,
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
from intric.flows.variable_resolver import (
    FlowVariableResolver,
    iter_template_expressions,
)

_LAZY_EXPORTS = {
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
    "flow_file_upload_service": ("intric.flows.flow_file_upload_service", None),
    "flow_input_limits": ("intric.flows.flow_input_limits", None),
}

if TYPE_CHECKING:
    from intric.flows import ai_builder, flow_file_upload_service, flow_input_limits
    from intric.flows.application.flow_run_service import FlowRunService
    from intric.flows.application.flow_service import FlowService
    from intric.flows.flow_factory import FlowFactory
    from intric.flows.infrastructure.flow_repo import FlowRepository
    from intric.flows.infrastructure.flow_run_repo import FlowRunRepository
    from intric.flows.infrastructure.flow_version_repo import FlowVersionRepository

__all__ = [
    "Flow",
    "FlowSparse",
    "FlowStep",
    "FlowVersion",
    "FlowRun",
    "FlowRunReviewCheckpoint",
    "FlowRunReviewCheckpointState",
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
    "ai_builder",
    "flow_file_upload_service",
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
