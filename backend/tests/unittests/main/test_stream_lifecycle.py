import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from unittest.mock import Mock

import anyio
import pytest
from litellm.litellm_core_utils.litellm_logging import Logging
from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper

from eneo.main import stream_lifecycle
from eneo.main.stream_lifecycle import (
    OwnedAsyncGenerator,
    close_provider_stream,
    finalization_deadline,
    finalization_owner,
    finalizing,
)


def _litellm_stream(source: object) -> CustomStreamWrapper:
    return CustomStreamWrapper(
        completion_stream=source,
        model="gpt-4o-mini",
        custom_llm_provider="openai",
        logging_obj=Logging(
            model="gpt-4o-mini",
            messages=[],
            stream=True,
            call_type="acompletion",
            start_time=datetime.now(timezone.utc),
            litellm_call_id="close-test",
            function_id="close-test",
        ),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("slow", [False, True])
@pytest.mark.parametrize("through_litellm", [False, True])
async def test_provider_close_shares_the_budget_and_allows_the_next_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    slow: bool,
    through_litellm: bool,
):
    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.02)
    monkeypatch.setattr(stream_lifecycle.logger, "handlers", [caplog.handler])
    events: list[str] = []
    task = asyncio.current_task()
    assert task is not None
    cancelling = task.cancelling()

    class Provider:
        async def aclose(self) -> None:
            assert asyncio.current_task() is task
            events.append("closing")
            try:
                await asyncio.sleep(0.2 if slow else 0)
                events.append("finished")
            except asyncio.CancelledError:
                events.append("cancelled")
                raise

    # Exercise LiteLLM's real shield AND its BaseException handler, nested
    # inside the same owner/scopes as an answer being closed from SSE.
    provider = Provider()
    source = _litellm_stream(provider) if through_litellm else provider
    with finalization_owner(), finalizing("answer stream"):
        await close_provider_stream(source)
        with finalizing("next step"):
            events.append("next")

    assert events == ["closing", "cancelled" if slow else "finished", "next"]
    assert ("provider stream' exceeded" in caplog.text) is slow
    assert task.cancelling() == cancelling
    assert finalization_deadline() is None
    # A successful close must disarm its timeout, not cancel later work.
    await asyncio.sleep(0.03)


@pytest.mark.asyncio
async def test_litellm_close_does_not_refresh_an_already_spent_budget(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.02)
    monkeypatch.setattr(stream_lifecycle.logger, "handlers", [caplog.handler])
    started = False
    finished = False
    deadline: float | None = None

    class Provider:
        async def aclose(self) -> None:
            nonlocal started, finished
            started = True
            assert finalization_deadline() == deadline
            await asyncio.sleep(0.01)
            finished = True

    with finalization_owner():
        with finalizing("earlier cleanup"):
            await asyncio.sleep(0.1)
        deadline = finalization_deadline()
        assert deadline is not None and deadline <= anyio.current_time()
        await close_provider_stream(_litellm_stream(Provider()))

    assert started and not finished
    assert "provider stream' was cut off at its first await" in caplog.text


@pytest.mark.asyncio
async def test_provider_close_finishes_under_anyio_cancellation():
    ready = asyncio.Event()
    finished = False

    class Provider:
        async def aclose(self) -> None:
            nonlocal finished
            await asyncio.sleep(0.01)
            finished = True

    async def worker() -> None:
        try:
            ready.set()
            await anyio.sleep_forever()
        finally:
            await close_provider_stream(_litellm_stream(Provider()))

    async with anyio.create_task_group() as group:
        group.start_soon(worker)
        await ready.wait()
        group.cancel_scope.cancel()

    assert finished


@pytest.mark.asyncio
async def test_litellm_cannot_swallow_external_cancellation_during_close():
    started = asyncio.Event()

    class Provider:
        async def aclose(self) -> None:
            started.set()
            await asyncio.sleep(0.2)

    closing = asyncio.create_task(close_provider_stream(_litellm_stream(Provider())))
    await started.wait()
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing


@pytest.mark.asyncio
async def test_provider_timeout_error_is_not_mistaken_for_the_cleanup_deadline():
    class Provider:
        async def aclose(self) -> None:
            raise TimeoutError("provider failure")

    with pytest.raises(TimeoutError, match="provider failure"):
        await close_provider_stream(Provider())


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
async def test_nested_cleanups_share_the_outermost_deadline():
    with finalization_owner():
        with finalizing("outer step"):
            outer = finalization_deadline()
        await anyio.sleep(0.01)
        with finalization_owner(), finalizing("inner step"):
            inner = finalization_deadline()
    assert inner == outer


@pytest.mark.asyncio
async def test_the_deadline_ends_with_the_cleanup_that_set_it():
    with finalization_owner(), finalizing("first"):
        first = finalization_deadline()
    assert finalization_deadline() is None
    await anyio.sleep(0.01)
    with finalization_owner(), finalizing("second"):
        second = finalization_deadline()
    assert first is not None and second is not None
    assert second > first


@pytest.mark.asyncio
async def test_a_step_past_the_budget_is_cut_off_and_the_next_one_still_runs(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.02)
    warnings = Mock()
    monkeypatch.setattr(stream_lifecycle.logger, "warning", warnings)
    ran: list[str] = []

    with finalization_owner():
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

    async def elsewhere() -> float | None:
        started.set()
        await proceed.wait()
        with finalization_owner(), finalizing("elsewhere"):
            return finalization_deadline()

    other = asyncio.create_task(elsewhere())
    await started.wait()
    with finalization_owner(), finalizing("here"):
        here = finalization_deadline()
        await anyio.sleep(0.01)
        proceed.set()
        elsewhere_deadline = await other

    assert elsewhere_deadline != here


@pytest.mark.asyncio
async def test_a_task_created_inside_a_frame_gets_a_budget_of_its_own():
    """A child task inherits the context, not the ownership: the frame's
    deadline must not bound, nor be forgotten by, what the child finalizes."""

    async def child() -> float | None:
        with finalizing("child step"):
            return finalization_deadline()

    with finalization_owner(), finalizing("parent step"):
        parent = finalization_deadline()
        await anyio.sleep(0.01)
        child_deadline = await asyncio.create_task(child())
        still_parent = finalization_deadline()

    assert child_deadline is not None and parent is not None
    assert child_deadline > parent
    assert still_parent == parent


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


@pytest.mark.asyncio
async def test_a_later_cleanup_is_not_cut_by_an_earlier_spent_budget(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.02)
    with finalizing("an earlier cleanup"):
        await anyio.sleep(10)
    ran = False

    with finalizing("a later cleanup"):
        await anyio.sleep(0)
        ran = True

    assert ran


@pytest.mark.asyncio
async def test_a_step_skipped_for_a_spent_budget_says_so(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(stream_lifecycle, "FINALIZATION_BUDGET_SECONDS", 0.02)
    warnings = Mock()
    monkeypatch.setattr(stream_lifecycle.logger, "warning", warnings)

    with finalization_owner():
        with finalizing("slow"):
            await anyio.sleep(10)
        with finalizing("next"):
            await anyio.sleep(0)

    messages = [call.args[0] for call in warnings.call_args_list]
    assert "exceeded" in messages[0]
    assert "already spent" in messages[1]


@pytest.mark.asyncio
async def test_throwing_into_an_unstarted_owned_generator_releases_it():
    events: list[str] = []

    async def release() -> None:
        events.append("released")

    owned = OwnedAsyncGenerator(_source(events), release=release)
    with pytest.raises(ValueError):
        await owned.athrow(ValueError("boom"))

    assert events == ["released"]
