"""Redis servers that stop answering, for tests of how long Eneo waits.

``silent_server`` accepts connections and never answers. ``freezing_redis``
answers what arq's startup and an enqueue send until it has answered a chosen
command, then answers nothing more on any connection until it is thawed: a
Redis that froze in the middle of a transaction.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator


@contextlib.asynccontextmanager
async def silent_server() -> AsyncIterator[int]:
    """Serve on a free local port, yielded, until the block ends."""
    writers: list[asyncio.StreamWriter] = []

    async def hold(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        await reader.read()  # until the client gives up

    server = await asyncio.start_server(hold, "127.0.0.1", 0)
    try:
        yield server.sockets[0].getsockname()[1]
    finally:
        server.close()
        for writer in writers:
            writer.close()
        await server.wait_closed()


class FreezingRedis:
    """What the test controls: the port, the freeze and the commands seen."""

    def __init__(self, freeze_after: bytes) -> None:
        self.port = 0
        self.freeze_after: bytes | None = freeze_after
        self.frozen = False
        self.commands: list[bytes] = []

    def thaw(self) -> None:
        self.freeze_after = None
        self.frozen = False

    def reply(self, name: bytes, in_transaction: bool) -> bytes:
        if name == b"PING":
            return b"+PONG\r\n"
        if name == b"EXISTS":
            return b":0\r\n"
        if name == b"EXEC":
            return b"*2\r\n+OK\r\n:1\r\n"
        return b"+QUEUED\r\n" if in_transaction else b"+OK\r\n"


async def _command(reader: asyncio.StreamReader) -> list[bytes]:
    """One RESP array of bulk strings, as redis-py sends commands."""
    header = await reader.readline()
    if not header:
        raise EOFError
    arguments: list[bytes] = []
    for _ in range(int(header[1:])):
        length = int((await reader.readline())[1:])
        arguments.append((await reader.readexactly(length + 2))[:-2])
    return arguments


@contextlib.asynccontextmanager
async def freezing_redis(*, freeze_after: bytes) -> AsyncIterator[FreezingRedis]:
    redis = FreezingRedis(freeze_after)
    writers: list[asyncio.StreamWriter] = []

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writers.append(writer)
        in_transaction = False
        with contextlib.suppress(
            EOFError, ConnectionError, asyncio.IncompleteReadError
        ):
            while True:
                arguments = await _command(reader)
                name = arguments[0].upper()
                redis.commands.append(name)
                if redis.frozen:
                    continue
                if name == b"MULTI":
                    writer.write(b"+OK\r\n")
                    in_transaction = True
                else:
                    writer.write(redis.reply(name, in_transaction))
                    in_transaction = in_transaction and name != b"EXEC"
                await writer.drain()
                if name == redis.freeze_after:
                    redis.frozen = True

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    redis.port = server.sockets[0].getsockname()[1]
    try:
        yield redis
    finally:
        server.close()
        for writer in writers:
            writer.close()
        await server.wait_closed()
