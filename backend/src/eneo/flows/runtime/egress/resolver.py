"""Name resolution for flow destinations, on its own small thread pool.

getaddrinfo cannot be cancelled: a deadline abandons the await, not the thread
that is waiting on the resolver. On the event loop's default executor a burst of
stalled names chosen by flow authors would occupy every worker there and stall
name resolution for the whole process, model providers included. Flow lookups
therefore run on their own pool, a lookup holds one slot until its thread ends,
and a lookup that finds no slot fails at once.
"""

from __future__ import annotations

import asyncio
import functools
import socket
import threading
from collections.abc import Sequence
from concurrent.futures import Future, ThreadPoolExecutor

from eneo.flows.runtime.egress.policy import (
    MAX_ANSWER_ADDRESSES,
    DestinationUnresolvable,
)
from eneo.main.config import get_settings


class BoundedResolver:
    def __init__(self, *, workers: int) -> None:
        self._pool = ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="flow-dns"
        )
        self._slots = threading.BoundedSemaphore(workers)

    async def __call__(self, host: str, port: int) -> Sequence[str]:
        if not self._slots.acquire(blocking=False):
            raise DestinationUnresolvable(host)
        try:
            future = self._pool.submit(_lookup, host, port)
        except BaseException:
            self._slots.release()
            raise
        # Released when the lookup thread ends (or the job is dropped), whatever
        # became of the await that asked for it.
        future.add_done_callback(self._release)
        return await asyncio.wrap_future(future)

    def _release(self, _future: Future[list[str]]) -> None:
        self._slots.release()


def _lookup(host: str, port: int) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise DestinationUnresolvable(host) from exc
    if len(infos) > MAX_ANSWER_ADDRESSES:
        raise DestinationUnresolvable(host)
    return [str(info[4][0]) for info in infos]


@functools.cache
def flow_name_resolver() -> BoundedResolver:
    """The process-wide resolver, sized by ``flow_http_dns_workers``."""
    return BoundedResolver(workers=get_settings().flow_http_dns_workers)
