from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest

from eneo.worker import upload_tasks


@pytest.mark.asyncio
async def test_publication_claim_loss_does_not_cancel_safe_publication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_lost = asyncio.Event()

    @asynccontextmanager
    async def losing_lease(*args, **kwargs):
        del args, kwargs
        owner = asyncio.current_task()
        assert owner is not None

        async def lose_claim() -> None:
            await asyncio.sleep(0)
            owner.cancel("test lease loss")
            claim_lost.set()

        loss = asyncio.create_task(lose_claim())
        try:
            yield True
        finally:
            loss.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loss

    monkeypatch.setattr(upload_tasks, "redis_lease", losing_lease)
    container = SimpleNamespace(redis_client=lambda: object())

    publication_finished = False
    async with upload_tasks._knowledge_original_publication_claim(
        container=container,
        group_id=UUID(int=1),
        original_sha256=b"a" * 32,
    ):
        await claim_lost.wait()
        await asyncio.sleep(0)
        publication_finished = True

    assert publication_finished
