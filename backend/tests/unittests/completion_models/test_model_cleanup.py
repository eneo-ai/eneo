"""
Tests for lifecycle cleanup of completion models.

The cleanup worker may hard-delete models once they are no longer referenced by
historical questions or active configuration entities. These tests focus on the
candidate query, shared reference semantics, and worker error classification.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from intric.completion_models.infrastructure.model_cleanup_worker import (
    _find_removable_models,
    _has_active_entity_references,
    cleanup_orphaned_models,
)

# `cleanup_orphaned_models` is the @worker.cron_job-wrapped callable, which
# expects an arq `ctx` and would try to open a real sessionmaker. The
# unit tests target the cleanup logic itself, not the cron wrapper, so we
# reach past it via `__wrapped__` (set by functools.wraps in the decorator).
_cleanup_fn = cleanup_orphaned_models.__wrapped__


class _AsyncContextManager:
    def __init__(self, value=None):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _MockSession:
    def __init__(self, execute=None):
        self.execute = execute or AsyncMock()

    def begin(self):
        return _AsyncContextManager()


class TestFindRemovableModels:
    """Verify the SQL query that identifies lifecycle cleanup candidates."""

    @pytest.mark.asyncio
    async def test_returns_model_when_fully_orphaned(self):
        model_id = uuid4()
        target_id = uuid4()
        session = AsyncMock()
        mock_result = MagicMock()
        mock_row = MagicMock()
        mock_row.id = model_id
        mock_row.name = "old-model"
        mock_row.deleted_at = None
        mock_row.migrated_to_model_id = target_id
        mock_result.all.return_value = [mock_row]
        session.execute.return_value = mock_result

        result = await _find_removable_models(session)

        assert len(result) == 1
        assert result[0]["id"] == model_id
        assert result[0]["name"] == "old-model"
        assert result[0]["migrated_to_model_id"] == target_id

    @pytest.mark.asyncio
    async def test_query_targets_soft_deleted_or_migrated_models(self):
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute.return_value = mock_result

        await _find_removable_models(session)

        stmt = session.execute.call_args.args[0]
        sql = " ".join(str(stmt).split())

        assert (
            "completion_models.deleted_at IS NOT NULL OR completion_models.migrated_to_model_id IS NOT NULL"
            in sql
        )
        assert "coalesce(anon_1.cnt, :coalesce_1) = :coalesce_2" in sql
        assert "coalesce(anon_2.cnt, :coalesce_3) = :coalesce_4" in sql


class TestActiveReferenceSemantics:
    """Verify the worker reuses the shared reference rules."""

    @pytest.mark.asyncio
    async def test_reference_check_delegates_to_shared_repository(self, monkeypatch):
        repo = MagicMock()
        repo.has_active_references = AsyncMock(return_value=True)

        repo_cls = MagicMock(return_value=repo)
        monkeypatch.setattr(
            "intric.completion_models.infrastructure.model_cleanup_worker.CompletionModelsRepository",
            repo_cls,
        )

        session = object()
        model_id = uuid4()

        result = await _has_active_entity_references(session, model_id)

        assert result is True
        repo_cls.assert_called_once_with(session=session)
        repo.has_active_references.assert_awaited_once_with(model_id)


def _make_container(session: _MockSession) -> SimpleNamespace:
    """Stand-in container that returns ``session`` from ``.session()``.

    Matches the new cleanup-worker contract: the cron wrapper hands the
    job a configured container; the job calls ``container.session()`` to
    get the session it then manages transactions on. The old override
    dance with ``cast(Any, container.session).override(...)`` is gone, so
    tests no longer need to monkeypatch ``sessionmanager``."""
    return SimpleNamespace(session=lambda: session)


class TestCleanupWorker:
    """Verify worker behavior around skips, deletes, and error handling."""

    @pytest.mark.asyncio
    async def test_integrity_error_is_classified_as_db_restrict(self, monkeypatch):
        model_id = uuid4()
        mock_session = _MockSession(
            execute=AsyncMock(
                side_effect=[
                    IntegrityError("delete", {}, Exception("restrict")),
                ]
            )
        )
        container = _make_container(mock_session)

        monkeypatch.setattr(
            "intric.completion_models.infrastructure.model_cleanup_worker._find_removable_models",
            AsyncMock(
                return_value=[
                    {
                        "id": model_id,
                        "name": "old-model",
                        "deleted_at": datetime.now(timezone.utc),
                        "migrated_to_model_id": None,
                    }
                ]
            ),
        )
        monkeypatch.setattr(
            "intric.completion_models.infrastructure.model_cleanup_worker._has_active_entity_references",
            AsyncMock(return_value=False),
        )

        result = await _cleanup_fn(container)

        assert result["success"] is True
        assert result["errors"] == []
        assert result["removed_models"] == []
        assert result["skipped_models"] == [
            {"id": str(model_id), "name": "old-model", "reason": "db_restrict"}
        ]

    @pytest.mark.asyncio
    async def test_active_references_are_skipped_without_delete(self, monkeypatch):
        model_id = uuid4()
        mock_session = _MockSession(execute=AsyncMock())
        container = _make_container(mock_session)

        monkeypatch.setattr(
            "intric.completion_models.infrastructure.model_cleanup_worker._find_removable_models",
            AsyncMock(
                return_value=[
                    {
                        "id": model_id,
                        "name": "referenced-model",
                        "deleted_at": datetime.now(timezone.utc),
                        "migrated_to_model_id": None,
                    }
                ]
            ),
        )
        monkeypatch.setattr(
            "intric.completion_models.infrastructure.model_cleanup_worker._has_active_entity_references",
            AsyncMock(return_value=True),
        )

        result = await _cleanup_fn(container)

        assert result["success"] is True
        assert result["removed_models"] == []
        assert result["errors"] == []
        assert result["skipped_models"] == [
            {
                "id": str(model_id),
                "name": "referenced-model",
                "reason": "active_references",
            }
        ]
        mock_session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_uses_container_provided_session(self, monkeypatch):
        """Regression guard for the session-ownership refactor.

        The job must consume the session from the container — opening a
        new one or trying to override the container's session provider
        was the fragile pattern we replaced. If a future refactor goes
        back to that, this test catches it because the candidate query
        runs on the container's session and nothing else."""
        sentinel_session = _MockSession(execute=AsyncMock())
        container = _make_container(sentinel_session)

        find_mock = AsyncMock(return_value=[])
        monkeypatch.setattr(
            "intric.completion_models.infrastructure.model_cleanup_worker._find_removable_models",
            find_mock,
        )

        result = await _cleanup_fn(container)

        assert result["success"] is True
        find_mock.assert_awaited_once()
        assert find_mock.await_args.args[0] is sentinel_session


class TestCleanupSafetyInvariants:
    """Document critical FK-based invariants for historical attribution."""

    def test_restrict_fk_prevents_accidental_question_loss(self):
        from intric.database.tables.questions_table import Questions

        fk_col = Questions.__table__.c.completion_model_id
        foreign_keys = list(fk_col.foreign_keys)

        assert len(foreign_keys) == 1
        assert foreign_keys[0].ondelete == "RESTRICT"

    def test_migrated_to_model_id_fk_prevents_target_deletion(self):
        from intric.database.tables.ai_models_table import CompletionModels

        fk_col = CompletionModels.__table__.c.migrated_to_model_id
        foreign_keys = list(fk_col.foreign_keys)

        assert len(foreign_keys) == 1
        assert foreign_keys[0].ondelete == "RESTRICT"
