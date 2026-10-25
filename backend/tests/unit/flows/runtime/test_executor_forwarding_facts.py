from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from eneo.flows.domain.forwarding_facts import ForwardingFacts
from eneo.flows.flow_run_provenance import (
    FlowResolvedInputFlowInputSource,
    FlowResolvedInputJsonPath,
    build_resolved_input_edge,
)
from eneo.flows.runtime import executor as executor_module
from eneo.flows.runtime.executor import FlowRunExecutor
from eneo.flows.runtime.forwarding_capture import (
    hold_attempt_edges,
    record_completed_model_call,
)
from eneo.main.exceptions import TypedIOValidationException

TEXT = " ".join(f"ord{index}" for index in range(100))


class _Session:
    @asynccontextmanager
    async def begin(self):
        yield self


class _SessionManager:
    @asynccontextmanager
    async def session(self):
        yield _Session()


class _Writes:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail = fail

    def repository(self, *, session: object) -> SimpleNamespace:
        async def record_forwarding_facts(**kwargs: Any) -> bool:
            if self.fail:
                raise RuntimeError("database unavailable")
            self.calls.append(kwargs)
            return True

        return SimpleNamespace(record_forwarding_facts=record_forwarding_facts)


@pytest.fixture
def writes(monkeypatch: pytest.MonkeyPatch) -> _Writes:
    recorded = _Writes()
    monkeypatch.setattr(executor_module, "sessionmanager", _SessionManager())
    monkeypatch.setattr(executor_module, "FlowRunRepository", recorded.repository)
    return recorded


def _model_call() -> None:
    """What a model step attempt does: builds an edge, activates, calls."""
    edge = build_resolved_input_edge(
        binding_ref="input_source",
        source=FlowResolvedInputFlowInputSource(
            kind="flow_input",
            selector=FlowResolvedInputJsonPath(kind="json_path", path=("text",)),
        ),
        selected_value=TEXT,
    )
    hold_attempt_edges((edge,))
    record_completed_model_call(edge_indexes=(0,), output_text=TEXT)


def _executor(attempt: Any) -> FlowRunExecutor:
    executor = object.__new__(FlowRunExecutor)
    executor._execute_step_attempt = attempt
    return executor


def _run() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), tenant_id=uuid4())


def _step() -> SimpleNamespace:
    return SimpleNamespace(step_id=uuid4(), step_order=2)


async def test_a_model_attempt_stores_its_facts_once(writes: _Writes) -> None:
    result = object()

    async def attempt(**_kwargs: Any) -> object:
        _model_call()
        return result

    run, step = _run(), _step()
    returned = await _executor(attempt)._execute_step(
        step=step,
        run=run,
        attempt_no=3,
    )

    assert returned is result
    assert len(writes.calls) == 1
    call = writes.calls[0]
    assert (call["run_id"], call["step_id"], call["attempt_no"], call["tenant_id"]) == (
        run.id,
        step.step_id,
        3,
        run.tenant_id,
    )
    facts = call["facts"]
    assert isinstance(facts, ForwardingFacts)
    assert facts.output_verbatim_ratio == 1.0


async def test_a_failed_model_attempt_still_stores_its_facts(writes: _Writes) -> None:
    async def attempt(**_kwargs: Any) -> object:
        _model_call()
        raise TypedIOValidationException("output rejected", code="x")

    with pytest.raises(TypedIOValidationException):
        await _executor(attempt)._execute_step(
            step=_step(),
            run=_run(),
            attempt_no=1,
        )

    assert len(writes.calls) == 1


async def test_an_attempt_without_a_model_call_stores_nothing(writes: _Writes) -> None:
    async def attempt(**_kwargs: Any) -> object:
        build_resolved_input_edge(
            binding_ref="input_source",
            source=FlowResolvedInputFlowInputSource(
                kind="flow_input",
                selector=FlowResolvedInputJsonPath(kind="json_path", path=("text",)),
            ),
            selected_value=TEXT,
        )
        return object()

    await _executor(attempt)._execute_step(
        step=_step(),
        run=_run(),
        attempt_no=1,
    )

    assert writes.calls == []


async def test_a_cancelled_attempt_stores_nothing(writes: _Writes) -> None:
    async def attempt(**_kwargs: Any) -> object:
        _model_call()
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _executor(attempt)._execute_step(
            step=_step(),
            run=_run(),
            attempt_no=1,
        )

    assert writes.calls == []


async def test_a_failed_write_never_reaches_the_step(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    failing = _Writes(fail=True)
    monkeypatch.setattr(executor_module, "sessionmanager", _SessionManager())
    monkeypatch.setattr(executor_module, "FlowRunRepository", failing.repository)
    result = object()

    async def attempt(**_kwargs: Any) -> object:
        _model_call()
        return result

    with caplog.at_level(logging.WARNING):
        returned = await _executor(attempt)._execute_step(
            step=_step(),
            run=_run(),
            attempt_no=1,
        )

    assert returned is result
    assert "forwarding_facts_not_recorded" in caplog.text
    assert "ord1" not in caplog.text
