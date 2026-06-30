from unittest.mock import AsyncMock

import pytest

from eneo.admin.quota_service import QuotaService
from eneo.main.exceptions import QuotaExceededException
from eneo.tenants.tenant import TenantInDB
from eneo.users.user import UserInDB


@pytest.fixture
async def quota_service(user: UserInDB):
    info_blobs_repo = AsyncMock()
    info_blobs_repo.get_total_size_of_user.return_value = 5
    info_blobs_repo.get_total_size_of_tenant.return_value = 5
    return QuotaService(user, info_blobs_repo)


def _size_of_text(text: str):
    return len(text.encode("utf-8"))


async def test_add_fails_when_exceeding_quota_for_user(
    quota_service: QuotaService, user: UserInDB, tenant: TenantInDB
):
    user.quota_limit = 10
    tenant.quota_limit = 100
    text_to_add = "This is a string of bigger size than 5"

    assert _size_of_text(text_to_add) > 5

    with pytest.raises(QuotaExceededException, match="User quota limit exceeded."):
        await quota_service.add_text(text_to_add)


async def test_add_fails_when_exceeding_quota_for_tenant(
    quota_service: QuotaService, user: UserInDB, tenant: TenantInDB
):
    user.quota_limit = 100
    tenant.quota_limit = 10
    text_to_add = "This is a string of bigger size than 5"

    assert _size_of_text(text_to_add) > 5

    with pytest.raises(QuotaExceededException, match="Tenant quota limit exceeded."):
        await quota_service.add_text(text_to_add)


async def test_add_blob_is_fine(
    quota_service: QuotaService, user: UserInDB, tenant: TenantInDB
):
    user.quota_limit = 100
    tenant.quota_limit = 100
    text_to_add = "This is a string"
    size_of_text = _size_of_text(text_to_add)

    assert size_of_text < 100

    gotten_size = await quota_service.add_text(text_to_add)

    assert gotten_size == size_of_text
