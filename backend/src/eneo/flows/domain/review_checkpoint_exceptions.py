"""Typed review-checkpoint failures.

Lifecycle failures are translated at the application/API boundary. Runtime
open failures are raised from worker paths; `RunNotRunning` is a recoverable
state race, while open-terminal invariants are terminalized by the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, TypeAlias
from uuid import UUID


class FlowReviewCheckpointLifecycleError(Exception):
    """Base class for transactional review-checkpoint lifecycle rejections."""

    pass


class FlowReviewCheckpointRuntimeInvariantError(Exception):
    """Base class for review-checkpoint worker/runtime invariant failures."""

    pass


@dataclass(eq=False)
class FlowReviewCheckpointNotFoundError(FlowReviewCheckpointLifecycleError):
    pass


@dataclass(eq=False)
class FlowReviewRunNotAwaitingReviewError(FlowReviewCheckpointLifecycleError):
    status: str


@dataclass(eq=False)
class FlowReviewRunNoLongerAwaitingReviewError(FlowReviewCheckpointLifecycleError):
    pass


@dataclass(eq=False)
class FlowReviewCheckpointExpiredError(FlowReviewCheckpointLifecycleError):
    checkpoint_id: UUID
    state: str
    expires_at: datetime | None
    expired_at: datetime | None


@dataclass(eq=False)
class FlowReviewCheckpointStaleRevisionError(FlowReviewCheckpointLifecycleError):
    expected_checkpoint_revision: int
    current_checkpoint_revision: int


@dataclass(eq=False)
class FlowReviewCheckpointNotActiveError(FlowReviewCheckpointLifecycleError):
    state: str


@dataclass(eq=False)
class FlowReviewEditStepResultMissingError(FlowReviewCheckpointLifecycleError):
    pass


@dataclass(eq=False)
class FlowReviewCheckpointAlreadyResumedError(FlowReviewCheckpointLifecycleError):
    pass


@dataclass(eq=False)
class FlowReviewCheckpointRejectedError(FlowReviewCheckpointLifecycleError):
    pass


@dataclass(eq=False)
class FlowReviewCheckpointCancelledError(FlowReviewCheckpointLifecycleError):
    pass


@dataclass(eq=False)
class FlowReviewCheckpointNotApprovedError(FlowReviewCheckpointLifecycleError):
    state: str


@dataclass(eq=False)
class FlowReviewCheckpointRunNotRunningError(FlowReviewCheckpointRuntimeInvariantError):
    status: str | None = None


@dataclass(frozen=True, slots=True)
class FlowReviewOpenBlockedByActiveCheckpointError(
    FlowReviewCheckpointRuntimeInvariantError
):
    active_checkpoint_id: UUID


@dataclass(frozen=True, slots=True)
class FlowReviewCheckpointStepResultIncompleteError(
    FlowReviewCheckpointRuntimeInvariantError
):
    step_id: UUID
    attempt_no: int


@dataclass(frozen=True, slots=True)
class FlowReviewMultipleActiveCheckpointsError(
    FlowReviewCheckpointRuntimeInvariantError
):
    pass


FlowReviewCheckpointLifecycleFailure: TypeAlias = (
    FlowReviewCheckpointNotFoundError
    | FlowReviewRunNotAwaitingReviewError
    | FlowReviewRunNoLongerAwaitingReviewError
    | FlowReviewCheckpointExpiredError
    | FlowReviewCheckpointStaleRevisionError
    | FlowReviewCheckpointNotActiveError
    | FlowReviewEditStepResultMissingError
    | FlowReviewCheckpointAlreadyResumedError
    | FlowReviewCheckpointRejectedError
    | FlowReviewCheckpointCancelledError
    | FlowReviewCheckpointNotApprovedError
)

# Keep `Final` unparameterized so Pyright preserves exact `except` narrowing.
FLOW_REVIEW_CHECKPOINT_LIFECYCLE_FAILURE_CLASSES: Final = (
    FlowReviewCheckpointNotFoundError,
    FlowReviewRunNotAwaitingReviewError,
    FlowReviewRunNoLongerAwaitingReviewError,
    FlowReviewCheckpointExpiredError,
    FlowReviewCheckpointStaleRevisionError,
    FlowReviewCheckpointNotActiveError,
    FlowReviewEditStepResultMissingError,
    FlowReviewCheckpointAlreadyResumedError,
    FlowReviewCheckpointRejectedError,
    FlowReviewCheckpointCancelledError,
    FlowReviewCheckpointNotApprovedError,
)

FlowReviewCheckpointRuntimeInvariantFailure: TypeAlias = (
    FlowReviewCheckpointRunNotRunningError
    | FlowReviewOpenBlockedByActiveCheckpointError
    | FlowReviewCheckpointStepResultIncompleteError
    | FlowReviewMultipleActiveCheckpointsError
)

FlowReviewCheckpointOpenTerminalInvariantFailure: TypeAlias = (
    FlowReviewOpenBlockedByActiveCheckpointError
    | FlowReviewCheckpointStepResultIncompleteError
    | FlowReviewMultipleActiveCheckpointsError
)

# Keep `Final` unparameterized so Pyright preserves exact `except` narrowing.
FLOW_REVIEW_CHECKPOINT_RUNTIME_INVARIANT_CLASSES: Final = (
    FlowReviewCheckpointRunNotRunningError,
    FlowReviewOpenBlockedByActiveCheckpointError,
    FlowReviewCheckpointStepResultIncompleteError,
    FlowReviewMultipleActiveCheckpointsError,
)

# Keep `Final` unparameterized so Pyright preserves exact `except` narrowing.
FLOW_REVIEW_CHECKPOINT_OPEN_TERMINAL_INVARIANT_CLASSES: Final = (
    FlowReviewOpenBlockedByActiveCheckpointError,
    FlowReviewCheckpointStepResultIncompleteError,
    FlowReviewMultipleActiveCheckpointsError,
)
