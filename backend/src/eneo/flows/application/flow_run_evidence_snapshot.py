"""One snapshot for evidence authorization, reads and audit writes."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from eneo.main.container.container import Container


@asynccontextmanager
async def flow_run_evidence_snapshot_transaction(
    container: Container,
) -> AsyncGenerator[None, None]:
    """Keep authorization, evidence assembly, and audit writes in one snapshot.

    Evidence reads must not mix states across run resolution, preflight, and
    section queries. Audit writes are insert-only and remain atomic with the
    evidence read. Transaction failures are handled fail-closed without retry
    machinery.
    """
    session = cast(AsyncSession, container.session())
    async with session.begin():
        await session.connection(
            execution_options={"isolation_level": "REPEATABLE READ"}
        )
        yield
