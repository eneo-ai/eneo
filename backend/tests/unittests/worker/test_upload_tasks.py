from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest

from eneo.object_content.content import ObjectContentBusyError
from eneo.worker import upload_tasks


@pytest.mark.asyncio
async def test_publication_claim_loss_cancels_protected_remote_work(
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

    with pytest.raises(asyncio.CancelledError, match="test lease loss"):
        async with upload_tasks._knowledge_original_publication_claim(
            container=container,
            group_id=UUID(int=1),
            original_sha256=b"a" * 32,
        ):
            await claim_lost.wait()
            await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_publication_claim_timeout_fails_without_logging_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @asynccontextmanager
    async def held_lease(*args, **kwargs):
        del args, kwargs
        yield False

    group_id = UUID(int=7)
    digest = b"sensitive digest" * 2
    logger = MagicMock()
    monkeypatch.setattr(upload_tasks, "redis_lease", held_lease)
    monkeypatch.setattr(
        upload_tasks,
        "_KNOWLEDGE_PUBLICATION_CLAIM_MAX_WAIT_SECONDS",
        0,
    )
    monkeypatch.setattr(upload_tasks, "logger", logger)
    container = SimpleNamespace(redis_client=lambda: object())

    entered_publication = False
    with pytest.raises(ObjectContentBusyError):
        async with upload_tasks._knowledge_original_publication_claim(
            container=container,
            group_id=group_id,
            original_sha256=digest,
        ):
            entered_publication = True

    assert not entered_publication
    diagnostics = repr(logger.method_calls)
    assert str(group_id) not in diagnostics
    assert digest.hex() not in diagnostics
