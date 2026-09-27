"""Dataclass exceptions must survive generator-based context managers.

``contextlib`` assigns ``exc.__traceback__`` when an exception leaves a
``@contextmanager``/``@asynccontextmanager`` body, and a frozen dataclass
refuses that assignment: the original error is replaced by
``FrozenInstanceError`` before any handler can match it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from eneo.completion_models.infrastructure.context_builder import (
    ContextWindowExceededError,
)
from eneo.flows.domain.review_checkpoint_exceptions import (
    FlowReviewCheckpointStepResultIncompleteError,
    FlowReviewMultipleActiveCheckpointsError,
    FlowReviewOpenBlockedByActiveCheckpointError,
)
from eneo.flows.runtime.flow_runtime_trace import trace_flow_run, trace_flow_step


def _errors() -> list[Exception]:
    return [
        ContextWindowExceededError(estimated_tokens=42000, max_tokens=32000),
        FlowReviewOpenBlockedByActiveCheckpointError(active_checkpoint_id=uuid4()),
        FlowReviewCheckpointStepResultIncompleteError(step_id=uuid4(), attempt_no=1),
        FlowReviewMultipleActiveCheckpointsError(),
    ]


@asynccontextmanager
async def _rolling_back_scope() -> AsyncIterator[None]:
    # The shape of sessionmanager.session(): observe the failure, re-raise it.
    try:
        yield
    except Exception:
        raise


@pytest.mark.parametrize("error", _errors(), ids=lambda error: type(error).__name__)
async def test_error_crosses_asynccontextmanager_intact(error: Exception) -> None:
    with pytest.raises(type(error)) as exc_info:
        async with _rolling_back_scope():
            raise error

    assert exc_info.value is error
    assert exc_info.value.__traceback__ is not None


@pytest.mark.parametrize("error", _errors(), ids=lambda error: type(error).__name__)
def test_error_crosses_flow_trace_scopes_intact(error: Exception) -> None:
    with pytest.raises(type(error)) as exc_info:
        with trace_flow_run(
            run_id=uuid4(),
            flow_id=uuid4(),
            tenant_id=uuid4(),
            task_id="task-1",
            retry_count=0,
        ):
            with trace_flow_step(
                run_id=uuid4(),
                run_trace_id=uuid4(),
                flow_id=uuid4(),
                tenant_id=uuid4(),
                step_id=uuid4(),
                step_order=1,
                attempt_no=1,
                input_type="text",
                output_type="text",
                output_mode="pass_through",
            ):
                raise error

    assert exc_info.value is error


async def test_context_window_error_keeps_fields_and_message() -> None:
    error = ContextWindowExceededError(estimated_tokens=42000, max_tokens=32000)

    with pytest.raises(ContextWindowExceededError) as exc_info:
        async with _rolling_back_scope():
            raise error

    assert exc_info.value.estimated_tokens == 42000
    assert exc_info.value.max_tokens == 32000
    assert str(exc_info.value) == (
        "Estimated context exceeds configured model limit: "
        "42000 estimated tokens vs 32000 configured tokens."
    )
