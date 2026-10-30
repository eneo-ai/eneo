"""One tool call for a caller that runs with nobody watching.

A fresh connection per call: connect, initialize, call and close share one
time budget, the answer is refused while it arrives if it is larger than the
caller accepts, and no redirect is followed. Every request of the call goes
through the HTTP client the caller's factory builds, so the caller decides
which addresses the call may connect to. Whether the call is allowed is
decided before, by ``unattended_tool_refusal``.
"""

import asyncio
from typing import TYPE_CHECKING

from eneo.main.exceptions import (
    EncryptionNotConfiguredException,
    MCPClientError,
    MCPToolCallTimedOut,
)
from eneo.mcp_servers.infrastructure.client.mcp_client import (
    MCPClient,
    MCPHttpClientFactory,
    MCPToolAnswer,
)

if TYPE_CHECKING:
    from eneo.mcp_servers.domain.entities.mcp_server import MCPServer
    from eneo.mcp_servers.infrastructure.proxy.mcp_proxy_factory import (
        MCPProxySessionFactory,
    )

# How long a caller waits, in all, for an exchange it has stopped. Closing
# makes no request to the server, so a stopped exchange normally ends at once
# and the caller leaves with the connection closed.
EXCHANGE_STOP_GRACE_SECONDS = 1.0

# An exchange is told to stop this many times, each with an equal share of
# the grace. One time may not be enough: a stage of the exchange can go on
# through a cancellation (the close that follows a cancelled call runs under
# it), and the next one ends it.
_STOP_ATTEMPTS = 2

# An exchange that was let go is still a running task; its name tells it apart
# among the tasks of the process.
EXCHANGE_TASK_NAME = "mcp-unattended-tool-call"

# Every exchange that has not ended. asyncio keeps only a weak reference to a
# task, and the caller lets go of an exchange that outlives the grace.
_running_exchanges: set[asyncio.Task[MCPToolAnswer]] = set()


def _exchange_ended(exchange: asyncio.Task[MCPToolAnswer]) -> None:
    _running_exchanges.discard(exchange)
    # The caller may have left already; reading the failure here keeps asyncio
    # from logging it as one that nobody retrieved.
    if not exchange.cancelled():
        exchange.exception()


async def _exchange(
    client: MCPClient, tool_name: str, arguments: dict[str, object]
) -> MCPToolAnswer:
    async with client:
        return await client.call_tool_as_sent(tool_name, arguments)


async def _stop(exchange: asyncio.Task[MCPToolAnswer]) -> None:
    """Tell the exchange to stop and wait for it, within the grace.

    A caller that is cancelled while it waits here still tells the exchange
    every time and waits each share out: left after the first time, the
    exchange would stay in a stage that went on through it for as long as
    the server likes. The caller's own cancellation is raised when this is
    done.
    """
    loop = asyncio.get_running_loop()
    cancelled = False
    for _ in range(_STOP_ATTEMPTS):
        exchange.cancel()
        share_ends = loop.time() + EXCHANGE_STOP_GRACE_SECONDS / _STOP_ATTEMPTS
        while not exchange.done() and (left := share_ends - loop.time()) > 0:
            try:
                await asyncio.wait({exchange}, timeout=left)
            except asyncio.CancelledError:
                cancelled = True
    if cancelled:
        raise asyncio.CancelledError


class UnattendedToolCaller:
    def __init__(self, credentials: "MCPProxySessionFactory") -> None:
        self._credentials = credentials

    async def call(
        self,
        server: "MCPServer",
        tool_name: str,
        arguments: dict[str, object],
        *,
        max_answer_bytes: int,
        timeout_seconds: int,
        http_client_factory: MCPHttpClientFactory,
    ) -> MCPToolAnswer:
        """Call ``tool_name`` with the server's stored credential, every
        request through a client ``http_client_factory`` builds.

        Raises MCPToolCallTimedOut when the exchange (connect, initialize,
        the call, close) has not ended after ``timeout_seconds``, whatever
        was arriving then; MCPToolAnswerTooLarge when a response was stopped
        at ``max_answer_bytes`` before that; MCPClientError for every other
        failed call, a stored credential that cannot be read included (then
        nothing is sent). A tool that answers "I failed" is an answer, with
        ``is_error`` set.

        This call waits for the exchange for at most ``timeout_seconds`` and,
        once it has stopped it, for at most ``EXCHANGE_STOP_GRACE_SECONDS``
        more: it returns or raises at the latest that sum after it began to
        wait. A caller that is cancelled gets its CancelledError, whatever
        the exchange had reached, at the latest that grace after the
        cancellation, also when it arrives while the exchange is being
        stopped. An exchange that has not ended by then, although it was told
        to more than once, is left to end on its own; it is kept until it has.
        """
        try:
            credentials = self._credentials.auth_credentials(server)
        except (EncryptionNotConfiguredException, ValueError) as error:
            # What decrypting raises can quote the stored value, so the
            # message says only what failed; the cause stays on the exception.
            raise MCPClientError(
                "Tool call failed: the server's stored credential could not be read"
            ) from error
        client = MCPClient(
            server,
            credentials,
            timeout=timeout_seconds,
            # Read by the transport for its read timeout: a slow answer must
            # not be cut there before the budget ends.
            tool_call_timeout=timeout_seconds,
            tool_call_max_bytes=max_answer_bytes,
            terminate_session_on_close=False,
            http_client_factory=http_client_factory,
        )
        # A task of its own: the caller's cancellation is taken here, at this
        # task's own wait, where nothing can rewrite it, and the exchange is
        # then told to stop whatever it had reached, the connection closed
        # with it.
        exchange = asyncio.create_task(
            _exchange(client, tool_name, arguments), name=EXCHANGE_TASK_NAME
        )
        _running_exchanges.add(exchange)
        exchange.add_done_callback(_exchange_ended)
        try:
            ended, _ = await asyncio.wait({exchange}, timeout=timeout_seconds)
        except asyncio.CancelledError:
            await _stop(exchange)
            raise
        if not ended:
            await _stop(exchange)
            raise MCPToolCallTimedOut(
                f"Tool call failed: no answer within {timeout_seconds}s"
            )
        if exchange.cancelled():
            # Nobody here stopped it, and the caller was not cancelled: an
            # exchange cancelled by whatever it ran is a failed call.
            raise MCPClientError("Tool call failed: the request to the server failed")
        return exchange.result()
