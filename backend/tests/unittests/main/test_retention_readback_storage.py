"""The storage readback confirms removal only after the store was listed in
full by a listing that began after the readback started, and only when no
removal is left: bytes no content names any more are known only from a
listing."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from eneo.main import retention_readback
from eneo.object_content.reconciliation import ReconciliationResult, RemovalReadback
from eneo.object_content.reconciliation_repository import InventoryListing

_STARTED = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


def _at(passes: int) -> datetime:
    return _STARTED + timedelta(minutes=passes)


class _Store:
    """A store listed in one page, so each pass completes the listing under
    way and begins the next. The listing under way when the readback starts
    began before it. Once listed, `waiting` objects no content names wait in
    their grace period."""

    object_store_configured = True

    def __init__(self, *, lists: bool = True, waiting: int = 0) -> None:
        self.service = SimpleNamespace(check_object_store_ready=AsyncMock())
        self.refresh_object_store_configuration = AsyncMock()
        self._lists = lists
        self._waiting = waiting
        self.passes = 0
        self.counts = 0

    async def reconcile_once(self) -> ReconciliationResult:
        self.passes += 1
        return ReconciliationResult.empty()

    async def removal_readback(self) -> RemovalReadback:
        self.counts += 1
        return RemovalReadback(
            held=0, retrying=0, waiting=self._waiting if self.passes >= 2 else 0
        )

    async def inventory_listing(self) -> InventoryListing:
        # Pass n runs at _at(n), completes the cycle under way and begins the
        # next one then. The cycle under way at the start began at _at(-1).
        n = self.passes if self._lists else 0
        return InventoryListing(
            observed_at=_at(self.passes),
            last_completed_object_cycle_started_at=_at(n - 1 if n > 1 else n - 2),
            multipart_cycle_started_at=_at(n if n else -1),
            last_multipart_cycle_completed_at=_at(n if n else -1),
        )


@pytest.mark.asyncio
async def test_an_object_no_listing_has_seen_keeps_storage_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _Store(waiting=1)
    monkeypatch.setattr(retention_readback, "object_content_runtime", store)
    lines: list[str] = []

    assert await retention_readback._read_back_storage(lines.append) is True

    assert "storage: confirmed" not in lines
    assert "storage: pending 1 (held 0, retrying 0, waiting 1)" in lines


@pytest.mark.asyncio
async def test_storage_is_confirmed_after_a_listing_begun_after_the_readback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first pass completes the listing that was under way, which began
    before the readback; only the second completes one that began after."""
    store = _Store()
    monkeypatch.setattr(retention_readback, "object_content_runtime", store)
    lines: list[str] = []

    assert await retention_readback._read_back_storage(lines.append) is True

    assert lines == ["storage: confirmed"]
    assert store.passes == 2


@pytest.mark.asyncio
async def test_a_store_not_listed_within_the_ceiling_ends_as_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The readback bounds its work and never confirms without a listing."""
    store = _Store(lists=False)
    monkeypatch.setattr(retention_readback, "object_content_runtime", store)
    monkeypatch.setattr(retention_readback, "_STORAGE_PASSES", 3)
    lines: list[str] = []

    assert await retention_readback._read_back_storage(lines.append) is True

    assert store.passes == 3
    assert lines == [
        "storage: pending 0 (held 0, retrying 0, waiting 0), store not listed in full"
    ]


@pytest.mark.asyncio
async def test_what_is_left_is_counted_once_the_store_is_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Counting what is left reads every candidate. Until a listing that
    began after the readback is complete, the count cannot end it, so the
    readback counts only when it reports."""
    store = _Store(lists=False)
    monkeypatch.setattr(retention_readback, "object_content_runtime", store)
    monkeypatch.setattr(retention_readback, "_STORAGE_PASSES", 3)

    assert await retention_readback._read_back_storage(lambda _line: None) is True

    assert store.passes == 3
    assert store.counts == 1
