from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from intric.groups_legacy.group_service import GroupService
from intric.info_blobs.info_blob_repo import InfoBlobRepository
from intric.info_blobs.info_blob_service import InfoBlobService
from intric.main.exceptions import NameCollisionException, NotFoundException


@dataclass
class Setup:
    repo: InfoBlobRepository
    service: InfoBlobService
    group_service: GroupService


@pytest.fixture
def setup():
    repo = AsyncMock()
    group_service = AsyncMock()

    service = InfoBlobService(
        repo=repo,
        space_repo=AsyncMock(),
        user=MagicMock(),
        quota_service=AsyncMock(),
        group_service=group_service,
        update_website_size_service=AsyncMock(),
        space_service=AsyncMock(),
        actor_manager=MagicMock(),
    )

    setup = Setup(repo=repo, service=service, group_service=group_service)

    return setup


async def test_get_info_blob_does_not_exist(setup: Setup):
    setup.repo.get.return_value = None

    with pytest.raises(NotFoundException, match="InfoBlob not found"):
        await setup.service.get_by_id("non-existant id 1")


async def test_update_info_blob_does_not_exist(setup: Setup):
    setup.repo.update.return_value = None
    setup.repo.get_by_title_and_group.return_value = None

    with pytest.raises(NotFoundException, match="InfoBlob not found"):
        await setup.service.update_info_blob(MagicMock())


async def test_delete_info_blob_does_not_exist(setup: Setup):
    # With secure delete, we fetch the blob first to validate authorization
    setup.repo.get.return_value = None

    with pytest.raises(NotFoundException, match="InfoBlob not found"):
        await setup.service.delete("UUID")


async def test_get_by_user_empty_list_when_no_info_blobs(setup: Setup):
    info_blobs_by_user = await setup.service.get_by_user()

    assert info_blobs_by_user == []


async def test_update_fails_if_info_blob_with_same_name_exists(setup: Setup):
    setup.repo.get_by_title_and_group.return_value = MagicMock()

    with pytest.raises(NameCollisionException):
        await setup.service.update_info_blob(MagicMock())
