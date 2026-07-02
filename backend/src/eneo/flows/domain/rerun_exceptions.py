from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias
from uuid import UUID


class FlowRunRerunLifecycleError(Exception):
    """Base class for transactional rerun lifecycle rejections."""


class FlowRunRerunRuntimeInvariantError(Exception):
    """Base class for rerun worker/runtime invariant failures."""


@dataclass(frozen=True, slots=True)
class FlowRunRerunStaleRevisionError(FlowRunRerunLifecycleError):
    expected_run_revision: int
    current_run_revision: int


@dataclass(frozen=True, slots=True)
class FlowRunRerunInvalidTransitionError(FlowRunRerunLifecycleError):
    status: str


@dataclass(frozen=True, slots=True)
class FlowRunRerunStepNotFoundError(FlowRunRerunLifecycleError):
    pass


@dataclass(frozen=True, slots=True)
class FlowRunRerunMissingCurrentResultsError(FlowRunRerunLifecycleError):
    step_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class FlowRunRerunRootStepIncompleteError(FlowRunRerunLifecycleError):
    step_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class FlowRunRerunStepInputsInvalidError(FlowRunRerunLifecycleError):
    step_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True)
class FlowRunRerunMultipleActiveOperationsError(FlowRunRerunRuntimeInvariantError):
    flow_run_id: UUID


@dataclass(frozen=True, slots=True)
class FlowRunRerunAttemptLineageConflictError(FlowRunRerunRuntimeInvariantError):
    operation_id: UUID
    step_id: UUID
    new_attempt_id: UUID


FlowRunRerunLifecycleFailure: TypeAlias = (
    FlowRunRerunStaleRevisionError
    | FlowRunRerunInvalidTransitionError
    | FlowRunRerunStepNotFoundError
    | FlowRunRerunMissingCurrentResultsError
    | FlowRunRerunRootStepIncompleteError
    | FlowRunRerunStepInputsInvalidError
)

# Keep `Final` unparameterized so Pyright preserves exact `except` narrowing.
FLOW_RUN_RERUN_LIFECYCLE_FAILURE_CLASSES: Final = (
    FlowRunRerunStaleRevisionError,
    FlowRunRerunInvalidTransitionError,
    FlowRunRerunStepNotFoundError,
    FlowRunRerunMissingCurrentResultsError,
    FlowRunRerunRootStepIncompleteError,
    FlowRunRerunStepInputsInvalidError,
)

FlowRunRerunRuntimeInvariantFailure: TypeAlias = (
    FlowRunRerunMultipleActiveOperationsError | FlowRunRerunAttemptLineageConflictError
)

# Keep `Final` unparameterized so Pyright preserves exact `except` narrowing.
FLOW_RUN_RERUN_RUNTIME_INVARIANT_CLASSES: Final = (
    FlowRunRerunMultipleActiveOperationsError,
    FlowRunRerunAttemptLineageConflictError,
)
