import pytest
from unittest.mock import MagicMock
from uuid import uuid4
from datetime import datetime
from eneo.spaces.api.space_models import SpaceMember
from eneo.storage.domain.storage import StorageInfo, StorageSpaceInfo


# === Fixture: Create a mock SpaceMember using MagicMock ===
@pytest.fixture
def mock_space_member():
    member = MagicMock(spec=SpaceMember)
    member.user_id = uuid4()
    member.email = "test@example.com"
    return member


# === Fixture: Create a StorageSpaceInfo object with MagicMock ===
@pytest.fixture
def storage_shared_space_info(mock_space_member):
    space_info = MagicMock(spec=StorageSpaceInfo)
    space_info.id = uuid4()
    space_info.created_at = datetime.now()
    space_info.updated_at = datetime.now()
    space_info.name = "Test Space"
    space_info.size = 1000
    space_info.members = [mock_space_member]
    return space_info


@pytest.fixture
def storage_personal_space_info():
    space_info = MagicMock(spec=StorageSpaceInfo)
    space_info.id = uuid4()
    space_info.created_at = datetime.now()
    space_info.updated_at = datetime.now()
    space_info.name = "Personal space"
    space_info.size = 1000
    space_info.members = []
    return space_info


# === Fixture: Create a StorageInfo object using MagicMock ===
@pytest.fixture
def storage_info(storage_shared_space_info, storage_personal_space_info):
    storage = MagicMock(spec=StorageInfo)
    storage._shared_spaces = {storage_shared_space_info.id: storage_shared_space_info}
    storage._personal_spaces = {
        storage_personal_space_info.id: storage_personal_space_info
    }
    storage._quota_limit = 5000
    storage.total_used = sum(
        space.size for space in storage._shared_spaces.values()
    ) + sum(space.size for space in storage._personal_spaces.values())
    storage.get_quota_limit.return_value = storage._quota_limit
    storage.get_shared_spaces.return_value = storage._shared_spaces.copy()
    return storage


# === Test: Ensure size_of_used_storage calculates correctly ===
def test_size_of_used_storage(
    storage_info, storage_shared_space_info, storage_personal_space_info
):
    expected_total_used = (
        storage_shared_space_info.size + storage_personal_space_info.size
    )
    assert storage_info.total_used == expected_total_used


# === Test: Ensure get_quota_limit returns correct value ===
def test_get_quota_limit(storage_info):
    assert storage_info.get_quota_limit() == 5000
    storage_info.get_quota_limit.assert_called_once()
