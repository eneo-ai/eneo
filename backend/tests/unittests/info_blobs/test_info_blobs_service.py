from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from eneo.groups_legacy.group_service import GroupService
from eneo.info_blobs.info_blob_repo import InfoBlobRepository
from eneo.info_blobs.info_blob_service import InfoBlobService
from eneo.main.exceptions import NameCollisionException, NotFoundException


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
        datastore=AsyncMock(),
        object_content=AsyncMock(),
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
    setup.repo.get_by_user.return_value = []
    setup.repo.hydrate_original_availability.return_value = []

    info_blobs_by_user = await setup.service.get_by_user()

    assert info_blobs_by_user == []


async def test_get_by_user_projects_original_availability_after_filtering(setup: Setup):
    included = MagicMock()
    included.model_dump.return_value = {"title": "included"}
    excluded = MagicMock()
    excluded.model_dump.return_value = {"title": "excluded"}
    metadata_filter = MagicMock()
    metadata_filter.model_dump.return_value = {"title": "included"}
    setup.repo.get_by_user.return_value = [included, excluded]
    setup.repo.hydrate_original_availability.return_value = [included]

    result = await setup.service.get_by_user(metadata_filter=metadata_filter)

    assert result == [included]
    setup.repo.hydrate_original_availability.assert_awaited_once_with([included])


async def test_update_fails_if_info_blob_with_same_name_exists(setup: Setup):
    setup.repo.get_by_title_and_group.return_value = MagicMock()

    with pytest.raises(NameCollisionException):
        await setup.service.update_info_blob(MagicMock())


async def test_update_projects_original_availability_before_returning(setup: Setup):
    current = MagicMock(group_id=None)
    updated = MagicMock()
    projected = MagicMock(original_available=True)
    update = MagicMock(id="blob-id", title=None)
    setup.repo.get.return_value = current
    setup.repo.update.return_value = updated
    setup.repo.hydrate_original_availability.return_value = [projected]
    setup.service._validate = AsyncMock()

    result = await setup.service.update_info_blob(update)

    assert result is projected
    setup.repo.hydrate_original_availability.assert_awaited_once_with([updated])


async def test_add_info_blobs_projects_original_availability_once(setup: Setup):
    published = [MagicMock(), MagicMock()]
    projected = [
        MagicMock(original_available=False),
        MagicMock(original_available=False),
    ]
    setup.service._can_perform_action = AsyncMock()
    setup.service.publish_info_blob_without_validation = AsyncMock(
        side_effect=published
    )
    setup.repo.hydrate_original_availability.return_value = projected

    result = await setup.service.add_info_blobs(
        "group-id",
        [MagicMock(), MagicMock()],
        embedding_model=MagicMock(),
    )

    assert result == projected
    setup.repo.hydrate_original_availability.assert_awaited_once_with(published)


async def test_delete_projects_unavailable_after_reference_removal(setup: Setup):
    current = MagicMock()
    deleted = MagicMock()
    projected = MagicMock(original_available=False)
    setup.repo.get.return_value = current
    setup.repo.delete.return_value = deleted
    setup.repo.hydrate_original_availability.return_value = [projected]
    setup.service._validate = AsyncMock()

    result = await setup.service.delete("blob-id")

    assert result is projected
    setup.repo.hydrate_original_availability.assert_awaited_once_with([deleted])
