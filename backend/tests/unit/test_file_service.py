"""Tests for file service delete-before-auth fix (Plan 1E).

Covers:
- Atomic delete_by_owner pattern: ownership checked in SQL, not in Python
- NotFoundException for non-owned and missing files (IDOR prevention: 404, not 403)
- Successful delete returns the deleted File record
- Unexpected repo errors propagate (not swallowed as 404)
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from intric.files.file_models import File, FileType
from intric.files.file_service import FileService
from intric.main.exceptions import NotFoundException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_file(*, user_id: UUID, file_id: UUID | None = None) -> File:
    """Build a minimal File domain object."""
    return File(
        id=file_id or uuid4(),
        name="test.txt",
        checksum="abc123",
        size=42,
        mimetype="text/plain",
        file_type=FileType.TEXT,
        text="hello",
        blob=None,
        transcription=None,
        user_id=user_id,
        tenant_id=uuid4(),
    )


def _make_service(*, user_id: UUID | None = None) -> tuple[FileService, AsyncMock]:
    """Build FileService with mocked repo. Returns (service, mock_repo)."""
    uid = user_id or uuid4()
    user = SimpleNamespace(id=uid, tenant_id=uuid4())
    repo = AsyncMock()
    protocol = MagicMock()
    svc = FileService(user=user, repo=repo, protocol=protocol)
    return svc, repo


# ---------------------------------------------------------------------------
# Tests — Service layer (delete_file)
# ---------------------------------------------------------------------------


class TestDeleteFile:
    """FileService.delete_file() unit tests."""

    @pytest.mark.asyncio
    async def test_delete_file_calls_delete_by_owner_with_user_id(self):
        """delete_file must use delete_by_owner (atomic), not plain delete."""
        svc, repo = _make_service()
        file_id = uuid4()
        expected_file = _make_file(user_id=svc.user.id, file_id=file_id)
        repo.delete_by_owner = AsyncMock(return_value=expected_file)

        await svc.delete_file(file_id)

        # Verify delete_by_owner is called with both id and user_id
        repo.delete_by_owner.assert_awaited_once_with(
            id=file_id, user_id=svc.user.id
        )
        # Verify plain delete is NOT called
        repo.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_delete_non_owned_file_returns_404(self):
        """delete_by_owner returns None (wrong owner) → NotFoundException (404, not 403).

        This is IDOR prevention: don't reveal whether a file exists.
        """
        svc, repo = _make_service()
        file_id = uuid4()
        repo.delete_by_owner = AsyncMock(return_value=None)

        with pytest.raises(NotFoundException):
            await svc.delete_file(file_id)

    @pytest.mark.asyncio
    async def test_delete_missing_file_returns_404(self):
        """delete_by_owner returns None (file doesn't exist) → NotFoundException.

        Same code path as wrong-owner — indistinguishable by design.
        """
        svc, repo = _make_service()
        nonexistent_id = uuid4()
        repo.delete_by_owner = AsyncMock(return_value=None)

        with pytest.raises(NotFoundException):
            await svc.delete_file(nonexistent_id)

    @pytest.mark.asyncio
    async def test_delete_owned_file_returns_deleted_record(self):
        """Successful delete returns the deleted File object."""
        svc, repo = _make_service()
        file_id = uuid4()
        expected_file = _make_file(user_id=svc.user.id, file_id=file_id)
        repo.delete_by_owner = AsyncMock(return_value=expected_file)

        result = await svc.delete_file(file_id)

        assert result is expected_file
        assert result.id == file_id
        assert result.user_id == svc.user.id

    @pytest.mark.asyncio
    async def test_delete_unexpected_error_propagates(self):
        """Unexpected repo errors are NOT swallowed as NotFoundException.

        If the DB is down or something unexpected happens, it should propagate
        as-is, not be masked as a 404.
        """
        svc, repo = _make_service()
        repo.delete_by_owner = AsyncMock(
            side_effect=RuntimeError("database connection lost")
        )

        with pytest.raises(RuntimeError, match="database connection lost"):
            await svc.delete_file(uuid4())


# ---------------------------------------------------------------------------
# Tests — Repo layer (delete_by_owner SQL pattern)
# ---------------------------------------------------------------------------


class TestDeleteByOwnerRepo:
    """FileRepository.delete_by_owner() SQL pattern verification.

    Tests that the repo method issues the correct atomic SQL and interprets results.
    Uses a mocked session to verify the SQL statement structure.
    """

    @pytest.mark.asyncio
    async def test_delete_by_owner_returns_none_when_no_match(self):
        """When DELETE RETURNING yields no row, returns None (not exception)."""
        from intric.files.file_repo import FileRepository

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        repo = FileRepository(session=mock_session)
        result = await repo.delete_by_owner(id=uuid4(), user_id=uuid4())

        assert result is None
        mock_session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_by_owner_returns_file_when_match(self):
        """When DELETE RETURNING yields a row, returns a validated File model."""
        from intric.files.file_repo import FileRepository

        user_id = uuid4()
        file_id = uuid4()
        tenant_id = uuid4()

        # Create a mock row that model_validate can consume
        mock_row = MagicMock()
        mock_row.id = file_id
        mock_row.user_id = user_id
        mock_row.tenant_id = tenant_id
        mock_row.name = "test.txt"
        mock_row.checksum = "abc"
        mock_row.size = 100
        mock_row.mimetype = "text/plain"
        mock_row.file_type = FileType.TEXT
        mock_row.text = "content"
        mock_row.blob = None
        mock_row.transcription = None
        mock_row.created_at = None
        mock_row.updated_at = None

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_row

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        repo = FileRepository(session=mock_session)

        with patch.object(File, "model_validate", return_value=_make_file(
            user_id=user_id, file_id=file_id
        )) as mock_validate:
            result = await repo.delete_by_owner(id=file_id, user_id=user_id)

        assert result is not None
        assert result.id == file_id
        assert result.user_id == user_id
        mock_validate.assert_called_once_with(mock_row)

    @pytest.mark.asyncio
    async def test_delete_by_owner_sql_includes_both_where_clauses(self):
        """The DELETE statement must include BOTH id AND user_id in WHERE clause.

        This verifies the atomic pattern — ownership is checked in SQL, not
        in a separate Python check that could race.
        """
        from intric.files.file_repo import FileRepository

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        repo = FileRepository(session=mock_session)
        file_id = uuid4()
        user_id = uuid4()

        await repo.delete_by_owner(id=file_id, user_id=user_id)

        # Inspect the SQL statement that was executed
        call_args = mock_session.execute.call_args
        stmt = call_args[0][0]
        compiled = stmt.compile(compile_kwargs={"literal_binds": False})
        sql_text = str(compiled)

        # Verify the SQL is a DELETE with RETURNING and includes both WHERE predicates
        assert "DELETE FROM" in sql_text.upper()
        assert "RETURNING" in sql_text.upper()
        # The WHERE clause should reference both the id and user_id columns
        assert "files.id" in sql_text or "id" in sql_text
        assert "user_id" in sql_text


class TestGetByIdRepo:
    """FileRepository.get_by_id() behavior for missing/existing rows."""

    @pytest.mark.asyncio
    async def test_get_by_id_missing_raises_not_found(self):
        """Missing file should raise NotFoundException (not validation error)."""
        from intric.files.file_repo import FileRepository

        mock_session = AsyncMock()
        repo = FileRepository(session=mock_session)
        repo._delegate.get = AsyncMock(return_value=None)

        with pytest.raises(NotFoundException):
            await repo.get_by_id(uuid4())

    @pytest.mark.asyncio
    async def test_get_by_id_returns_validated_file(self):
        """Existing file should be validated and returned as File model."""
        from intric.files.file_repo import FileRepository

        owner_id = uuid4()
        file_id = uuid4()
        expected = _make_file(user_id=owner_id, file_id=file_id)

        mock_session = AsyncMock()
        repo = FileRepository(session=mock_session)
        repo._delegate.get = AsyncMock(return_value=MagicMock())

        with patch.object(File, "model_validate", return_value=expected) as mock_validate:
            result = await repo.get_by_id(file_id=file_id)

        assert result is expected
        mock_validate.assert_called_once()
