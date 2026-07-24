from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.files.file_repo import FileRepository
from eneo.files.file_service import FileService
from eneo.main.exceptions import NotFoundException


def _service() -> tuple[FileService, AsyncMock, SimpleNamespace]:
    user = SimpleNamespace(id=uuid4(), tenant_id=uuid4())
    repo = AsyncMock()
    repo.session = MagicMock()
    service = FileService(
        user=user,
        repo=repo,
        protocol=AsyncMock(),
        object_content=AsyncMock(),
    )
    service._usage = AsyncMock()
    return service, repo, user


@pytest.mark.asyncio
async def test_delete_non_owned_and_missing_files_share_the_404_path() -> None:
    service, repo, _user = _service()
    repo.get_by_id_and_owner.return_value = None

    with pytest.raises(NotFoundException):
        await service.delete_file(uuid4())

    service._usage.lock_family.assert_not_awaited()
    repo.delete_by_owner.assert_not_awaited()


@pytest.mark.asyncio
async def test_deletion_preview_returns_404_if_the_file_disappears_during_read() -> (
    None
):
    service, repo, user = _service()
    file_id = uuid4()
    repo.get_by_id_and_owner.return_value = SimpleNamespace(id=file_id)
    service._usage.list_family.return_value = []

    with pytest.raises(NotFoundException):
        await service.get_deletion_preview(file_id)

    service._usage.list_family.assert_awaited_once_with(
        root_file_id=file_id,
        tenant_id=user.tenant_id,
    )
    service._usage.count_product_usage.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_rechecks_usage_under_the_family_lock() -> None:
    service, repo, user = _service()
    file_id = uuid4()
    metadata = SimpleNamespace(id=file_id)
    public_info = SimpleNamespace(id=file_id)
    repo.get_by_id_and_owner.return_value = metadata
    repo.delete_by_owner.return_value = metadata
    service._usage.lock_family.return_value = [file_id]
    service._usage.count_product_usage.return_value = []
    service._file_info = AsyncMock(return_value=public_info)

    result = await service.delete_file(file_id)

    assert result is public_info
    repo.get_by_id_and_owner.assert_awaited_once_with(
        file_id=file_id,
        user_id=user.id,
        tenant_id=user.tenant_id,
    )
    service._usage.lock_family.assert_awaited_once_with(
        root_file_id=file_id,
        tenant_id=user.tenant_id,
    )
    service._usage.count_product_usage.assert_awaited_once_with([file_id])
    repo.delete_by_owner.assert_awaited_once_with(
        id=file_id,
        user_id=user.id,
        tenant_id=user.tenant_id,
    )


@pytest.mark.asyncio
async def test_delete_does_not_mask_database_failures() -> None:
    service, repo, _user = _service()
    repo.get_by_id_and_owner.side_effect = RuntimeError("database unavailable")

    with pytest.raises(RuntimeError, match="database unavailable"):
        await service.delete_file(uuid4())


@pytest.mark.asyncio
async def test_repository_delete_contains_all_owner_predicates() -> None:
    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = AsyncMock()
    session.execute.return_value = result
    repository = FileRepository(session=session)

    await repository.delete_by_owner(
        id=uuid4(),
        user_id=uuid4(),
        tenant_id=uuid4(),
    )

    statement = session.execute.call_args.args[0]
    sql = str(statement.compile(compile_kwargs={"literal_binds": False}))
    assert "DELETE FROM files" in sql
    assert "files.id" in sql
    assert "files.user_id" in sql
    assert "files.tenant_id" in sql
    assert "RETURNING" in sql
