from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import eneo.sessions.session_service as session_service_module
from eneo.files.file_service import FileService
from eneo.sessions.session_service import SessionService


@pytest.mark.asyncio
async def test_session_service_create_session_commits_independently(
    monkeypatch: pytest.MonkeyPatch,
):
    fresh_session = MagicMock()
    request_session = MagicMock()
    request_session.in_transaction.return_value = True
    request_repo = SimpleNamespace(session=request_session, add=AsyncMock())
    fresh_repo = SimpleNamespace(add=AsyncMock(return_value=SimpleNamespace()))

    @asynccontextmanager
    async def _fresh_session_scope():
        yield fresh_session

    @asynccontextmanager
    async def _begin():
        yield

    fresh_session.begin.return_value = _begin()
    monkeypatch.setattr(
        session_service_module.sessionmanager,
        "session",
        _fresh_session_scope,
    )
    session_repo_factory = MagicMock(return_value=fresh_repo)
    monkeypatch.setattr(
        session_service_module,
        "SessionRepository",
        session_repo_factory,
    )
    service = SessionService(
        session_repo=request_repo,
        question_repo=AsyncMock(),
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
    )

    await service.create_session(name="new-session", assistant_id=uuid4())

    session_repo_factory.assert_called_once_with(fresh_session)
    fresh_repo.add.assert_awaited_once()
    request_repo.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_question_placeholder_commits_independently(
    monkeypatch: pytest.MonkeyPatch,
):
    fresh_session = MagicMock()
    request_session = MagicMock()
    request_session.in_transaction.return_value = True
    request_session_repo = SimpleNamespace(session=request_session)
    request_question_repo = SimpleNamespace(add=AsyncMock())
    fresh_question_repo = SimpleNamespace(
        add=AsyncMock(return_value=SimpleNamespace(id=uuid4()))
    )

    @asynccontextmanager
    async def _fresh_session_scope():
        yield fresh_session

    @asynccontextmanager
    async def _begin():
        yield

    fresh_session.begin.return_value = _begin()
    monkeypatch.setattr(
        session_service_module.sessionmanager,
        "session",
        _fresh_session_scope,
    )
    question_repo_factory = MagicMock(return_value=fresh_question_repo)
    monkeypatch.setattr(
        session_service_module,
        "QuestionRepository",
        question_repo_factory,
    )
    service = SessionService(
        session_repo=request_session_repo,
        question_repo=request_question_repo,
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
    )

    await service.create_question_placeholder(
        question="Keep this question",
        session=SimpleNamespace(id=uuid4()),
    )

    question_repo_factory.assert_called_once_with(fresh_session)
    fresh_question_repo.add.assert_awaited_once()
    request_question_repo.add.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_session_and_first_question_share_one_short_transaction(
    monkeypatch: pytest.MonkeyPatch,
):
    fresh_session = MagicMock()
    created_session = SimpleNamespace(id=uuid4(), questions=[])
    created_question = SimpleNamespace(id=uuid4())
    fresh_session_repo = SimpleNamespace(add=AsyncMock(return_value=created_session))
    fresh_question_repo = SimpleNamespace(add=AsyncMock(return_value=created_question))

    @asynccontextmanager
    async def _fresh_session_scope():
        yield fresh_session

    @asynccontextmanager
    async def _begin():
        yield

    fresh_session.begin.return_value = _begin()
    monkeypatch.setattr(
        session_service_module.sessionmanager,
        "session",
        _fresh_session_scope,
    )
    session_repo_factory = MagicMock(return_value=fresh_session_repo)
    question_repo_factory = MagicMock(return_value=fresh_question_repo)
    monkeypatch.setattr(
        session_service_module, "SessionRepository", session_repo_factory
    )
    monkeypatch.setattr(
        session_service_module, "QuestionRepository", question_repo_factory
    )
    service = SessionService(
        session_repo=SimpleNamespace(session=MagicMock()),
        question_repo=AsyncMock(),
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
    )

    session, question_id = await service.create_session_with_question_placeholder(
        name="new-session",
        question="first question",
    )

    assert session is created_session
    assert question_id == created_question.id
    session_repo_factory.assert_called_once_with(fresh_session)
    question_repo_factory.assert_called_once_with(fresh_session)
    fresh_session_repo.add.assert_awaited_once()
    fresh_question_repo.add.assert_awaited_once()


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

    repo = SimpleNamespace(session=session)
    service = FileService(
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
        repo=repo,
        protocol=AsyncMock(),
        object_content=AsyncMock(),
    )
    file_id = uuid4()
    service._persist_prepared_file = AsyncMock(return_value=file_id)
    service.get_file_by_id = AsyncMock(
        return_value=SimpleNamespace(
            model_dump=lambda: {
                "id": file_id,
                "name": "generated_image.jpeg",
                "checksum": "unused-by-transaction-test",
                "size": len(b"image-bytes"),
                "mimetype": "image/jpeg",
                "file_type": "image",
                "user_id": service.user.id,
                "tenant_id": service.user.tenant_id,
            }
        )
    )

    await service.save_image_from_bytes(b"image-bytes")

    assert entered == 1
    service._persist_prepared_file.assert_awaited_once()


@pytest.mark.asyncio
async def test_file_service_save_image_reuses_existing_transaction():
    session = MagicMock()
    session.in_transaction.return_value = True
    session.begin = MagicMock()

    repo = SimpleNamespace(session=session)
    service = FileService(
        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
        repo=repo,
        protocol=AsyncMock(),
        object_content=AsyncMock(),
    )
    file_id = uuid4()
    service._persist_prepared_file = AsyncMock(return_value=file_id)
    service.get_file_by_id = AsyncMock(
        return_value=SimpleNamespace(
            model_dump=lambda: {
                "id": file_id,
                "name": "generated_image.jpeg",
                "checksum": "unused-by-transaction-test",
                "size": len(b"image-bytes"),
                "mimetype": "image/jpeg",
                "file_type": "image",
                "user_id": service.user.id,
                "tenant_id": service.user.tenant_id,
            }
        )
    )

    await service.save_image_from_bytes(b"image-bytes")

    session.begin.assert_not_called()
    service._persist_prepared_file.assert_awaited_once()
