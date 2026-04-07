from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.files.file_service import FileService
from intric.sessions.session_service import SessionService


@pytest.mark.asyncio
async def test_session_service_create_session_starts_short_transaction_when_needed():
    entered = 0

    @asynccontextmanager
    async def _begin():
        nonlocal entered
        entered += 1
        yield

    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = _begin()

    session_repo = SimpleNamespace(session=session, add=AsyncMock(return_value=SimpleNamespace()))
    service = SessionService(
        session_repo=session_repo,
        question_repo=AsyncMock(),
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
    )

    await service.create_session(name="new-session", assistant_id=uuid4())

    assert entered == 1
    session_repo.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_service_create_session_reuses_existing_transaction():
    session = MagicMock()
    session.in_transaction.return_value = True
    session.begin = MagicMock()

    session_repo = SimpleNamespace(session=session, add=AsyncMock(return_value=SimpleNamespace()))
    service = SessionService(
        session_repo=session_repo,
        question_repo=AsyncMock(),
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
    )

    await service.create_session(name="existing-tx", assistant_id=uuid4())

    session.begin.assert_not_called()
    session_repo.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_file_service_save_image_starts_short_transaction_when_needed():
    entered = 0

    @asynccontextmanager
    async def _begin():
        nonlocal entered
        entered += 1
        yield

    session = MagicMock()
    session.in_transaction.return_value = False
    session.begin.return_value = _begin()

    repo = SimpleNamespace(session=session, add=AsyncMock(return_value=SimpleNamespace()))
    service = FileService(
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
        repo=repo,
        protocol=AsyncMock(),
    )

    await service.save_image_from_bytes(b"image-bytes")

    assert entered == 1
    repo.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_file_service_save_image_reuses_existing_transaction():
    session = MagicMock()
    session.in_transaction.return_value = True
    session.begin = MagicMock()

    repo = SimpleNamespace(session=session, add=AsyncMock(return_value=SimpleNamespace()))
    service = FileService(
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
        repo=repo,
        protocol=AsyncMock(),
    )

    await service.save_image_from_bytes(b"image-bytes")

    session.begin.assert_not_called()
    repo.add.assert_awaited_once()
