from types import SimpleNamespace
from uuid import uuid4

import pytest

from intric.spaces.space_repo import (
    SpaceRepositoryTenantMismatchError,
    SpaceRepositoryUserRequiredError,
)
from intric.users.user import UserState


def _tenant(tenant_id):
    return SimpleNamespace(id=tenant_id)


def _user(*, tenant_id):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        tenant=_tenant(tenant_id),
        user_groups_ids=[],
        state=UserState.ACTIVE,
    )


def _repo(*, tenant_id=None, user=None):
    from intric.spaces.space_repo import SpaceRepository

    return SpaceRepository(
        session=SimpleNamespace(),
        tenant=_tenant(tenant_id or uuid4()),
        user=user,
        factory=SimpleNamespace(),
        app_repo=SimpleNamespace(),
        assistant_repo=SimpleNamespace(),
        completion_model_repo=SimpleNamespace(),
        transcription_model_repo=SimpleNamespace(),
        embedding_model_repo=SimpleNamespace(),
        http_auth_encryption=SimpleNamespace(),
    )


def test_space_repository_rejects_user_from_different_tenant():
    tenant_id = uuid4()
    user = _user(tenant_id=uuid4())

    with pytest.raises(SpaceRepositoryTenantMismatchError):
        _repo(tenant_id=tenant_id, user=user)


@pytest.mark.asyncio
async def test_tenant_scoped_space_repository_rejects_member_listing_without_user():
    repo = _repo()

    with pytest.raises(SpaceRepositoryUserRequiredError):
        await repo.get_spaces_for_member()
