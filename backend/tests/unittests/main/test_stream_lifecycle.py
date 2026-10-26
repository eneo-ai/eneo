import asyncio
from collections.abc import AsyncGenerator
from unittest.mock import Mock

import anyio
import pytest

from eneo.main import stream_lifecycle
from eneo.main.stream_lifecycle import (
    OwnedAsyncGenerator,
    clear_finalization_deadline,
    finalization_scope,
    finalizing,
)


@pytest.fixture(autouse=True)
def _fresh_deadline():
    clear_finalization_deadline()
    yield
    clear_finalization_deadline()


async def _cleanup_under_cancellation(*, shielded: bool) -> bool:
    """Cancel a task mid-await and report whether its async cleanup finished."""
    finished = False

    async def worker() -> None:
        nonlocal finished
        try:
            await anyio.sleep_forever()
        finally:
            if shielded:
                with finalizing("cleanup"):
                    await anyio.sleep(0.01)
                    finished = True
            else:
                await anyio.sleep(0.01)
                finished = True

    async with anyio.create_task_group() as group:
        group.start_soon(worker)
        await anyio.sleep(0.01)
        group.cancel_scope.cancel()
    return finished


@pytest.mark.asyncio
async def test_finalizing_lets_async_cleanup_finish_after_a_cancellation():
    assert await _cleanup_under_cancellation(shielded=True)


@pytest.mark.asyncio
async def test_without_finalizing_the_cancellation_cuts_the_cleanup_short():
    # The negative case: the previous test fails for the right reason.
    assert not await _cleanup_under_cancellation(shielded=False)


@pytest.mark.asyncio
async def test_nested_finalizing_steps_share_the_first_deadline():
    with finalization_scope() as outer:
        await anyio.sleep(0.01)
        with finalization_scope() as inner:
            pass
    assert inner.deadline == outer.deadline


@pytest.mark.asyncio
async def test_a_step_past_the_budget_is_cut_off_and_the_next_one_still_runs(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.02)
    warnings = Mock()
    monkeypatch.setattr(stream_lifecycle.logger, "warning", warnings)
    ran: list[str] = []

    with finalizing("slow"):
        await anyio.sleep(10)
        ran.append("slow")
    with finalizing("next"):
        ran.append("next")
        await anyio.sleep(0)  # the spent budget ends this step here
        ran.append("after the await")

    assert ran == ["next"]
    assert [call.args[1] for call in warnings.call_args_list] == ["slow", "next"]


@pytest.mark.asyncio
async def test_a_task_already_running_has_a_deadline_of_its_own():
    started = asyncio.Event()
    proceed = asyncio.Event()

    async def elsewhere() -> float:
        started.set()
        await proceed.wait()
        with finalization_scope() as scope:
            return scope.deadline

    other = asyncio.create_task(elsewhere())
    await started.wait()
    with finalization_scope() as here:
        await anyio.sleep(0.01)
    proceed.set()

    assert await other != here.deadline


def _source(events: list[str]) -> AsyncGenerator[str, None]:
    async def generator() -> AsyncGenerator[str, None]:
        try:
            yield "a"
            yield "b"
        finally:
            events.append("generator closed")

    return generator()


@pytest.mark.asyncio
async def test_owned_generator_releases_when_closed_before_it_started():
    events: list[str] = []

    async def release() -> None:
        events.append("released")

    owned = OwnedAsyncGenerator(_source(events), release=release)
    await owned.aclose()

    assert events == ["released"]


@pytest.mark.asyncio
async def test_owned_generator_closes_the_generator_once_it_has_started():
    events: list[str] = []

    async def release() -> None:
        events.append("released")

    owned = OwnedAsyncGenerator(_source(events), release=release)
    assert await anext(owned) == "a"
    await owned.aclose()

    assert events == ["generator closed"]


@pytest.mark.asyncio
async def test_owned_generator_closes_once():
    events: list[str] = []

    async def release() -> None:
        events.append("released")

    owned = OwnedAsyncGenerator(_source(events), release=release)
    await owned.aclose()
    await owned.aclose()

    assert events == ["released"]


@pytest.mark.asyncio
async def test_owned_generator_iterates_to_the_end():
    events: list[str] = []

    async def release() -> None:
        events.append("released")

    owned = OwnedAsyncGenerator(_source(events), release=release)
    assert [item async for item in owned] == ["a", "b"]
    await owned.aclose()

    assert events == ["generator closed"]
