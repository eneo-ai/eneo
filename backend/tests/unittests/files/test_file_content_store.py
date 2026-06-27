from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.files.file_content_store import DbBlobContentStore
from intric.files.file_service import FileService


def _service(content_store=None):
    return FileService(
        user=MagicMock(),
        repo=MagicMock(),
        protocol=MagicMock(),
        content_store=content_store,
    )


# --- DbBlobContentStore (default backend) ---


def test_make_key_is_deterministic_and_tenant_scoped():
    store = DbBlobContentStore(session=MagicMock())
    tenant_id, file_id = uuid4(), uuid4()
    assert (
        store.make_key(tenant_id=tenant_id, file_id=file_id) == f"{tenant_id}/{file_id}"
    )
    assert store.backend_name == "db"


@pytest.mark.asyncio
async def test_db_store_read_returns_blob_from_session():
    session = MagicMock()
    session.scalar = AsyncMock(return_value=b"bytes")
    store = DbBlobContentStore(session=session)

    assert await store.read(key=f"{uuid4()}/{uuid4()}") == b"bytes"
    session.scalar.assert_awaited_once()


@pytest.mark.asyncio
async def test_db_store_write_issues_update():
    session = MagicMock()
    session.execute = AsyncMock()
    store = DbBlobContentStore(session=session)

    await store.write(key=f"{uuid4()}/{uuid4()}", data=b"x")
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_db_store_delete_is_noop():
    store = DbBlobContentStore(session=MagicMock())
    # Row delete already removes the bytes for the db backend.
    assert await store.delete(key=f"{uuid4()}/{uuid4()}") is None


# --- FileService.read_blob dual-read ---


@pytest.mark.asyncio
async def test_read_blob_prefers_inline_blob():
    store = MagicMock()
    store.read = AsyncMock(return_value=b"from-store")
    svc = _service(content_store=store)

    file = SimpleNamespace(blob=b"inline", storage_key="t/f", storage_backend="db")
    assert await svc.read_blob(file) == b"inline"
    store.read.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_blob_falls_back_to_store():
    store = MagicMock()
    store.read = AsyncMock(return_value=b"from-store")
    svc = _service(content_store=store)

    file = SimpleNamespace(blob=None, storage_key="t/f", storage_backend="s3")
    assert await svc.read_blob(file) == b"from-store"
    store.read.assert_awaited_once_with(key="t/f", backend="s3")


@pytest.mark.asyncio
async def test_read_blob_returns_none_when_no_content():
    svc = _service(content_store=MagicMock())
    file = SimpleNamespace(blob=None, storage_key=None, storage_backend=None)
    assert await svc.read_blob(file) is None


@pytest.mark.asyncio
async def test_read_blob_without_store_only_serves_inline():
    # No store wired (e.g. a lightweight caller): a store-backed file can't be
    # resolved, but inline content still works.
    svc = _service(content_store=None)
    file = SimpleNamespace(blob=None, storage_key="t/f", storage_backend="s3")
    assert await svc.read_blob(file) is None
