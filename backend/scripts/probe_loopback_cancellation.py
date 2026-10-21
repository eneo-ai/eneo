"""Report whether a stateless MCP cancellation reaches an active tool request.

Uses an in-memory ASGI transport. No listening socket, model, database or real
tool side effect is started. This is a transport probe, not an Eneo end-to-end
test; see docs/adr/assistant-delegation-execution-boundary.md.
"""

import asyncio
import json
from importlib.metadata import version

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import LATEST_PROTOCOL_VERSION


async def main() -> None:
    mcp = FastMCP("delegation-proof", stateless_http=True, json_response=True)
    started, release, stopped = asyncio.Event(), asyncio.Event(), asyncio.Event()

    @mcp.tool()
    async def consult() -> str:
        started.set()
        try:
            await release.wait()
            return "specialist completed"
        finally:
            stopped.set()

    app = mcp.streamable_http_app()
    headers = {
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": LATEST_PROTOCOL_VERSION,
    }
    async with asyncio.timeout(5):
        async with mcp.session_manager.run():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://localhost:8000",
                headers=headers,
            ) as client:
                call = asyncio.create_task(
                    client.post(
                        "/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "tools/call",
                            "params": {"name": "consult", "arguments": {}},
                        },
                    )
                )
                waiting = asyncio.create_task(started.wait())
                try:
                    completed, _ = await asyncio.wait(
                        (call, waiting), return_when=asyncio.FIRST_COMPLETED
                    )
                    if call in completed:
                        early = await call
                        raise RuntimeError(
                            f"Tool did not start; HTTP status {early.status_code}"
                        )
                    cancel = await client.post(
                        "/mcp",
                        json={
                            "jsonrpc": "2.0",
                            "method": "notifications/cancelled",
                            "params": {"requestId": 1, "reason": "parent stopped"},
                        },
                    )
                    # A delivered cancellation reaches the tool only at its next
                    # checkpoint, so give it a bounded chance before releasing.
                    try:
                        async with asyncio.timeout(0.5):
                            await stopped.wait()
                    except TimeoutError:
                        pass
                    still_running = not stopped.is_set()
                    release.set()
                    answer = await call
                    print(
                        json.dumps(
                            {
                                "mcp_version": version("mcp"),
                                "cancel_http_status": cancel.status_code,
                                "specialist_still_running_after_cancel": still_running,
                                "answer_http_status": answer.status_code,
                                "answer": answer.json(),
                            },
                            indent=2,
                        )
                    )
                finally:
                    release.set()
                    if not call.done():
                        call.cancel()
                    if not waiting.done():
                        waiting.cancel()
                    await asyncio.gather(call, waiting, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
