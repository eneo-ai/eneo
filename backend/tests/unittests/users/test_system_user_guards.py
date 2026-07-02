"""Unit tests for the system-user guards on ``UsersRepository``.

System users (``users.is_system_user = true``) are seeded per tenant to own
the Help Assistant rows that live in each org-space. They must never:

  * appear in any list-returning user query (admin lists, search, etc.); or
  * be hard- or soft-deleted by any admin path or cleanup job.

These tests pin the behavior at the repo boundary without a real database:
the SQL behavior is additionally exercised in
``tests/integration/repositories/test_user_repo_system_user_guards.py``.

PRD §2; mirrors the helper-exclusion testing style from step 013.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.users_table import Users
from eneo.main.exceptions import SystemUserProtected
from eneo.users.user_repo import UsersRepository


def _make_repo() -> UsersRepository:
    """Build a repo with a MagicMock session — sufficient for guard logic."""
    session = MagicMock()
    session.scalar = AsyncMock()
    session.execute = AsyncMock()
    repo = UsersRepository(session=session)
    # Replace the delegate so we observe what queries the repo would issue
    # without touching the BaseRepositoryDelegate plumbing.
    repo.delegate = AsyncMock()
    return repo


def _captures_query() -> tuple[list[sa.Select[tuple]], AsyncMock]:
    """Helper that wires ``delegate.get_models_from_query`` to record args."""
    captured: list[sa.Select[tuple]] = []

    async def _record(query):
        captured.append(query)
        return []

    return captured, AsyncMock(side_effect=_record)


def _has_system_user_filter(query: sa.Select[tuple]) -> bool:
    """True iff the rendered SQL filters on ``users.is_system_user IS false``."""
    rendered = str(query.compile(compile_kwargs={"literal_binds": True})).lower()
    return "is_system_user is false" in rendered


class TestIsSystemUser:
    async def test_returns_true_when_session_returns_true(self):
        repo = _make_repo()
        repo.session.scalar.return_value = True

        assert await repo.is_system_user(uuid4()) is True

    async def test_returns_false_when_session_returns_false(self):
        repo = _make_repo()
        repo.session.scalar.return_value = False

        assert await repo.is_system_user(uuid4()) is False

    async def test_returns_false_when_user_does_not_exist(self):
        repo = _make_repo()
        repo.session.scalar.return_value = None  # SELECT returned no row

        assert await repo.is_system_user(uuid4()) is False


class TestDeleteGuards:
    """``hard_delete`` / ``soft_delete`` / ``delete`` all raise on system users."""

    async def test_hard_delete_raises_for_system_user(self):
        repo = _make_repo()
        repo.session.scalar.return_value = True  # is_system_user => True

        with pytest.raises(SystemUserProtected, match="system account"):
            await repo.hard_delete(uuid4())

        repo.delegate.delete.assert_not_awaited()

    async def test_soft_delete_raises_for_system_user(self):
        repo = _make_repo()
        repo.session.scalar.return_value = True

        with pytest.raises(SystemUserProtected, match="system account"):
            await repo.soft_delete(uuid4())

        # The DELETE on Spaces and UPDATE on Users must not have been issued.
        repo.session.execute.assert_not_awaited()
        repo.delegate.get_model_from_query.assert_not_awaited()

    async def test_delete_wrapper_raises_for_system_user_soft_path(self):
        repo = _make_repo()
        repo.session.scalar.return_value = True

        with pytest.raises(SystemUserProtected):
            await repo.delete(uuid4(), soft_delete=True)

    async def test_delete_wrapper_raises_for_system_user_hard_path(self):
        repo = _make_repo()
        repo.session.scalar.return_value = True

        with pytest.raises(SystemUserProtected):
            await repo.delete(uuid4(), soft_delete=False)

    async def test_hard_delete_proceeds_for_regular_user(self):
        repo = _make_repo()
        repo.session.scalar.return_value = False  # not a system user
        repo.delegate.delete.return_value = None

        await repo.hard_delete(uuid4())

        repo.delegate.delete.assert_awaited_once()


class TestListExclusion:
    """Default list helper hides system users; opt-in includes them."""

    async def test_default_excludes_system_user(self):
        repo = _make_repo()
        captured, recorder = _captures_query()
        repo.delegate.get_models_from_query = recorder

        await repo._get_models_from_query(sa.select(Users))

        assert len(captured) == 1
        assert _has_system_user_filter(captured[0])

    async def test_include_system_user_does_not_add_filter(self):
        repo = _make_repo()
        captured, recorder = _captures_query()
        repo.delegate.get_models_from_query = recorder

        await repo._get_models_from_query(sa.select(Users), include_system_user=True)

        assert len(captured) == 1
        assert not _has_system_user_filter(captured[0])

    async def test_default_still_filters_when_with_deleted_true(self):
        """`with_deleted=True` drops soft-delete filter, NOT system-user filter."""
        repo = _make_repo()
        captured, recorder = _captures_query()
        repo.delegate.get_models_from_query = recorder

        await repo._get_models_from_query(sa.select(Users), with_deleted=True)

        rendered = str(
            captured[0].compile(compile_kwargs={"literal_binds": True})
        ).lower()
        assert "deleted_at is null" not in rendered
        assert _has_system_user_filter(captured[0])
