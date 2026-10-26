from collections.abc import AsyncIterable, Sequence
from typing import Any, cast

from sse_starlette import EventSourceResponse
from starlette.types import Send

from eneo.main.logging import get_logger
from eneo.main.stream_lifecycle import (
    aclose_if_possible,
    clear_finalization_deadline,
    closing,
    finalizing,
)

__all__ = ["ClosingEventSourceResponse", "closing"]

logger = get_logger(__name__)


async def _close(step: str, source: object) -> None:
    try:
        with finalizing(step):
            await aclose_if_possible(source)
    except Exception:
        # The other sources still get closed; the failure is reported.
        logger.exception("Closing the %s failed", step)


class ClosingEventSourceResponse(EventSourceResponse):
    """An SSE response that closes what it streams, on the task that streamed it.

    On a client disconnect sse-starlette cancels the streaming task. When the
    cancellation lands in ``send`` rather than inside the body, the body
    generator stays suspended at its ``yield``; left alone, its ``finally``
    (partial answer save, release of the model and tool connections) would
    run only when the garbage collector finalizes it, on another task.

    ``closes`` names the streams behind the body, outermost first. A body
    that never started cannot close them itself (closing an unstarted
    generator runs nothing), so the response closes them directly; once the
    body has run, they are already closed and this is a no-op.
    """

    def __init__(
        self,
        content: AsyncIterable[Any],
        *args: Any,
        closes: Sequence[object] = (),
        **kwargs: Any,
    ) -> None:
        super().__init__(content, *args, **kwargs)  # pyright: ignore[reportUnknownMemberType]
        self._closes = tuple(closes)

    async def stream_response(self, send: Send) -> None:
        try:
            await super().stream_response(send)
        finally:
            body = cast(object, self.body_iterator)  # pyright: ignore[reportUnknownMemberType]
            try:
                await _close("response body", body)
                for source in self._closes:
                    await _close("response source", source)
            finally:
                clear_finalization_deadline()
