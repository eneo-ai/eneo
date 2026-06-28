from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.main.exceptions import (
    BadRequestException,
    NameCollisionException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.prompt_library.application.prompt_library_service import (
    PromptLibraryService,
)
from eneo.prompt_library.domain.prompt_library import PromptLibraryEntry
from eneo.roles.permissions import Permission


def _admin_user(tenant_id):
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = tenant_id
    user.permissions = {Permission.ADMIN}
    return user


def _non_admin_user(tenant_id):
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = tenant_id
    user.permissions = set()
    return user


def _entry(tenant_id, name="Standard"):
    return PromptLibraryEntry(
        id=uuid4(),
        tenant_id=tenant_id,
        name=name,
        description=None,
        text="text",
        current_version=1,
        created_by_user_id=uuid4(),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_list_requires_admin():
    tenant_id = uuid4()
    repo = AsyncMock()
    service = PromptLibraryService(user=_non_admin_user(tenant_id), repo=repo)
    with pytest.raises(UnauthorizedException):
        await service.list_entries()


@pytest.mark.asyncio
async def test_list_returns_repo_entries():
    tenant_id = uuid4()
    entry = _entry(tenant_id)
    repo = AsyncMock()
    repo.list_by_tenant.return_value = [entry]
    service = PromptLibraryService(user=_admin_user(tenant_id), repo=repo)

    result = await service.list_entries()
    assert result == [entry]
    repo.list_by_tenant.assert_awaited_once_with(tenant_id)


@pytest.mark.asyncio
async def test_create_rejects_duplicate_name():
    tenant_id = uuid4()
    repo = AsyncMock()
    repo.exists_by_name.return_value = True
    service = PromptLibraryService(user=_admin_user(tenant_id), repo=repo)

    with pytest.raises(BadRequestException):
        await service.create_entry(name="Standard", description=None, text="t")


@pytest.mark.asyncio
async def test_create_translates_name_collision_integrity_error():
    # Two admins racing the same name: exists_by_name passes for both, the
    # second insert hits uq_prompt_library_tenant_name. It must surface as the
    # same 400 the pre-check raises, not a raw 500.
    from sqlalchemy.exc import IntegrityError

    tenant_id = uuid4()
    repo = AsyncMock()
    repo.exists_by_name.return_value = False
    repo.add.side_effect = IntegrityError(
        statement="INSERT",
        params={},
        orig=Exception(
            "duplicate key value violates unique constraint "
            '"uq_prompt_library_tenant_name"'
        ),
    )
    service = PromptLibraryService(user=_admin_user(tenant_id), repo=repo)

    with pytest.raises(BadRequestException):
        await service.create_entry(name="Standard", description=None, text="t")


@pytest.mark.asyncio
async def test_create_reraises_unrelated_integrity_error():
    from sqlalchemy.exc import IntegrityError

    tenant_id = uuid4()
    repo = AsyncMock()
    repo.exists_by_name.return_value = False
    repo.add.side_effect = IntegrityError(
        statement="INSERT",
        params={},
        orig=Exception("some_fk_constraint violated"),
    )
    service = PromptLibraryService(user=_admin_user(tenant_id), repo=repo)

    with pytest.raises(IntegrityError):
        await service.create_entry(name="Standard", description=None, text="t")


@pytest.mark.asyncio
async def test_create_calls_repo_with_user_id_and_tenant_id():
    tenant_id = uuid4()
    user = _admin_user(tenant_id)
    repo = AsyncMock()
    repo.exists_by_name.return_value = False
    captured: list[PromptLibraryEntry] = []

    async def fake_add(entry):
        captured.append(entry)
        entry.id = uuid4()
        entry.created_at = datetime.now(timezone.utc)
        entry.updated_at = datetime.now(timezone.utc)
        return entry

    repo.add.side_effect = fake_add
    service = PromptLibraryService(user=user, repo=repo)

    await service.create_entry(name="N", description="d", text="t")

    assert len(captured) == 1
    assert captured[0].tenant_id == tenant_id
    assert captured[0].created_by_user_id == user.id
    assert captured[0].current_version == 1


@pytest.mark.asyncio
async def test_get_entry_returns_404_when_missing():
    tenant_id = uuid4()
    repo = AsyncMock()
    repo.get.return_value = None
    service = PromptLibraryService(user=_admin_user(tenant_id), repo=repo)

    with pytest.raises(NotFoundException):
        await service.get_entry(uuid4())


@pytest.mark.asyncio
async def test_update_rejects_duplicate_name():
    tenant_id = uuid4()
    target = _entry(tenant_id, name="Old")
    repo = AsyncMock()
    repo.get_for_update.return_value = target
    repo.exists_by_name.return_value = True
    service = PromptLibraryService(user=_admin_user(tenant_id), repo=repo)

    with pytest.raises(BadRequestException):
        await service.update_entry(target.id, name="New")


@pytest.mark.asyncio
async def test_update_creates_new_version_when_text_changes():
    tenant_id = uuid4()
    target = _entry(tenant_id, name="Old")
    user = _admin_user(tenant_id)
    repo = AsyncMock()
    repo.get_for_update.return_value = target
    repo.exists_by_name.return_value = False
    repo.update.side_effect = lambda entry, **_: entry
    service = PromptLibraryService(user=user, repo=repo)

    result = await service.update_entry(target.id, text="new text")

    assert result.current_version == 2
    repo.get_for_update.assert_awaited_once_with(id=target.id, tenant_id=tenant_id)
    repo.update.assert_awaited_once_with(
        target,
        create_version=True,
        version_created_by_user_id=user.id,
    )


@pytest.mark.asyncio
async def test_update_creates_new_version_when_metadata_changes():
    tenant_id = uuid4()
    target = _entry(tenant_id, name="Old")
    user = _admin_user(tenant_id)
    repo = AsyncMock()
    repo.get_for_update.return_value = target
    repo.exists_by_name.return_value = False
    repo.update.side_effect = lambda entry, **_: entry
    service = PromptLibraryService(user=user, repo=repo)

    result = await service.update_entry(target.id, description="description")

    assert result.current_version == 2
    repo.update.assert_awaited_once_with(
        target,
        create_version=True,
        version_created_by_user_id=user.id,
    )


@pytest.mark.asyncio
async def test_delete_blocked_when_policy_uses_prompt():
    tenant_id = uuid4()
    target = _entry(tenant_id)
    repo = AsyncMock()
    repo.get.return_value = target
    policy_repo = AsyncMock()
    policy_repo.get_by_prompt_library_id.return_value = object()  # any non-None
    service = PromptLibraryService(
        user=_admin_user(tenant_id),
        repo=repo,
        governance_policy_repo=policy_repo,
    )

    with pytest.raises(NameCollisionException):
        await service.delete_entry(target.id)
    repo.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_proceeds_when_policy_repo_not_wired():
    tenant_id = uuid4()
    target = _entry(tenant_id)
    repo = AsyncMock()
    repo.get.return_value = target
    service = PromptLibraryService(user=_admin_user(tenant_id), repo=repo)

    await service.delete_entry(target.id)
    repo.delete.assert_awaited_once_with(id=target.id, tenant_id=tenant_id)
