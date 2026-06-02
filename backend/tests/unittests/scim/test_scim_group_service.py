from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.scim.constants import SCIM_FILTER_MAX_RESULTS
from intric.scim.domain.errors import (
    ScimGroupConflictError,
    ScimGroupNotFoundError,
    ScimValidationError,
)
from intric.scim.schemas.group import ScimGroupMember, ScimGroupRequest
from intric.scim.schemas.user import PatchOperation
from intric.scim.services.group_service import ScimGroupService


def _make_db_group(display_name: str = "Engineering"):
    m = MagicMock()
    m.id = uuid4()
    m.external_id = None
    m.name = display_name
    m.users = []
    m.created_at = datetime.now(timezone.utc)
    m.updated_at = datetime.now(timezone.utc)
    return m


def _make_service(repo=None) -> ScimGroupService:
    from intric.scim.repositories.group_repository import ScimGroupRepository

    repo = repo or AsyncMock(spec=ScimGroupRepository)
    if isinstance(repo.get_by_name.return_value, AsyncMock):
        repo.get_by_name.return_value = None
    if isinstance(repo.get_user_ids_in_tenant.return_value, AsyncMock):
        repo.get_user_ids_in_tenant.return_value = set()
    return ScimGroupService(repository=repo, tenant_id=uuid4())


CREATE_REQUEST = ScimGroupRequest(displayName="Engineering")


class TestCreateGroup:
    async def test_creates_and_returns_scim_group(self):
        repo = AsyncMock()
        db_group = _make_db_group()
        repo.get_by_name.return_value = None
        repo.create.return_value = db_group
        repo.get_by_id.return_value = db_group

        service = _make_service(repo)
        result = await service.create_group(CREATE_REQUEST)

        repo.create.assert_called_once()
        assert result.displayName == db_group.name
        assert result.id == str(db_group.id)

    async def test_raises_conflict_for_existing_display_name(self):
        repo = AsyncMock()
        repo.get_by_name.return_value = _make_db_group()

        service = _make_service(repo)
        with pytest.raises(ScimGroupConflictError):
            await service.create_group(CREATE_REQUEST)

        repo.create.assert_not_called()

    async def test_creates_with_members(self):
        repo = AsyncMock()
        user_id = uuid4()
        db_group = _make_db_group()
        db_group.users = [MagicMock(id=user_id, username="jane@example.com")]
        repo.get_by_name.return_value = None
        repo.create.return_value = db_group
        repo.get_by_id.return_value = db_group
        repo.get_user_ids_in_tenant.return_value = {user_id}

        service = _make_service(repo)
        request = ScimGroupRequest(
            displayName="Engineering",
            members=[ScimGroupMember(value=str(user_id))],
        )
        result = await service.create_group(request)

        assert len(result.members) == 1
        assert result.members[0].value == str(user_id)

    async def test_rejects_members_outside_tenant(self):
        repo = AsyncMock()
        user_id = uuid4()
        repo.get_by_name.return_value = None
        repo.get_user_ids_in_tenant.return_value = set()

        service = _make_service(repo)
        request = ScimGroupRequest(
            displayName="Engineering",
            members=[ScimGroupMember(value=str(user_id))],
        )

        with pytest.raises(ScimValidationError):
            await service.create_group(request)

        repo.create.assert_not_called()
        repo.set_members.assert_not_called()


class TestGetGroup:
    async def test_returns_group(self):
        repo = AsyncMock()
        db_group = _make_db_group()
        repo.get_by_id.return_value = db_group

        service = _make_service(repo)
        result = await service.get_group(db_group.id)

        assert result.id == str(db_group.id)

    async def test_raises_not_found_when_missing(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimGroupNotFoundError):
            await service.get_group(uuid4())


class TestListGroups:
    def _make_repo(self, groups=None):
        repo = AsyncMock()
        repo.list.return_value = groups or []
        repo.count.return_value = len(groups) if groups else 0
        return repo

    async def test_returns_scim_groups(self):
        groups = [_make_db_group(), _make_db_group("Backend")]
        repo = self._make_repo(groups)
        service = _make_service(repo)
        result, total = await service.list_groups()
        assert len(result) == 2
        assert total == 2

    async def test_passes_pagination_to_repo(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_groups(start_index=3, count=10)
        repo.list.assert_called_once_with(
            tenant_id=ANY, scim_filter=None, scim_sort=None, offset=2, limit=10
        )

    async def test_count_above_max_is_clamped_to_advertised_max(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_groups(count=SCIM_FILTER_MAX_RESULTS + 5000)
        _, kwargs = repo.list.call_args
        assert kwargs["limit"] == SCIM_FILTER_MAX_RESULTS

    async def test_omitted_count_defaults_to_max_not_unbounded(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_groups()
        _, kwargs = repo.list.call_args
        assert kwargs["limit"] == SCIM_FILTER_MAX_RESULTS

    async def test_passes_none_filter_when_no_filter(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_groups(filter_str=None)
        repo.count.assert_called_once_with(tenant_id=ANY, scim_filter=None)
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=None,
            scim_sort=None,
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_passes_filter_to_repo(self):
        from intric.scim.schemas.common import ScimFilter

        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_groups(filter_str='displayName eq "Engineering"')
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=ScimFilter("displayName", "eq", "Engineering"),
            scim_sort=None,
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_eq_filter_on_external_id(self):
        from intric.scim.schemas.common import ScimFilter

        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_groups(filter_str='externalId eq "aad-group-guid"')
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=ScimFilter("externalId", "eq", "aad-group-guid"),
            scim_sort=None,
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_sort_by_displayname(self):
        from intric.scim.schemas.common import ScimSort

        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_groups(sort_by="displayName", sort_order="descending")
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=None,
            scim_sort=ScimSort("displayName", "descending"),
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )


class TestReplaceGroup:
    async def test_replaces_and_returns_group(self):
        repo = AsyncMock()
        db_group = _make_db_group()
        repo.get_by_id.return_value = db_group
        repo.set_members.return_value = None
        repo.update.return_value = db_group
        repo.get_user_ids_in_tenant.return_value = set()

        service = _make_service(repo)
        result = await service.replace_group(db_group.id, CREATE_REQUEST)

        repo.update.assert_called_once()
        assert result.id == str(db_group.id)

    async def test_raises_not_found(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimGroupNotFoundError):
            await service.replace_group(uuid4(), CREATE_REQUEST)

    async def test_raises_conflict_when_display_name_belongs_to_another_group(self):
        repo = AsyncMock()
        db_group = _make_db_group("Engineering")
        other_group = _make_db_group("Taken")
        repo.get_by_id.return_value = db_group
        repo.get_by_name.return_value = other_group

        service = _make_service(repo)
        request = ScimGroupRequest(displayName="Taken")

        with pytest.raises(ScimGroupConflictError):
            await service.replace_group(db_group.id, request)

        repo.update.assert_not_called()

    async def test_rejects_members_outside_tenant(self):
        repo = AsyncMock()
        db_group = _make_db_group()
        user_id = uuid4()
        repo.get_by_id.return_value = db_group
        repo.get_user_ids_in_tenant.return_value = set()

        service = _make_service(repo)
        request = ScimGroupRequest(
            displayName="Engineering",
            members=[ScimGroupMember(value=str(user_id))],
        )

        with pytest.raises(ScimValidationError):
            await service.replace_group(db_group.id, request)

        repo.set_members.assert_not_called()
        repo.update.assert_not_called()


class TestPatchGroup:
    async def test_add_member(self):
        repo = AsyncMock()
        db_group = _make_db_group()
        user_id = uuid4()
        repo.get_by_id.return_value = db_group
        repo.update.return_value = db_group
        repo.get_user_ids_in_tenant.return_value = {user_id}

        service = _make_service(repo)
        await service.patch_group(
            db_group.id,
            [PatchOperation(op="Add", path="members", value=[{"value": str(user_id)}])],
        )

        repo.add_member.assert_called_once_with(db_group.id, user_id, tenant_id=ANY)

    async def test_rejects_add_member_outside_tenant(self):
        repo = AsyncMock()
        db_group = _make_db_group()
        user_id = uuid4()
        repo.get_by_id.return_value = db_group
        repo.get_user_ids_in_tenant.return_value = set()

        service = _make_service(repo)

        with pytest.raises(ScimValidationError):
            await service.patch_group(
                db_group.id,
                [
                    PatchOperation(
                        op="Add", path="members", value=[{"value": str(user_id)}]
                    )
                ],
            )

        repo.add_member.assert_not_called()
        repo.update.assert_not_called()

    async def test_remove_member(self):
        repo = AsyncMock()
        db_group = _make_db_group()
        user_id = uuid4()
        repo.get_by_id.return_value = db_group
        repo.update.return_value = db_group

        service = _make_service(repo)
        await service.patch_group(
            db_group.id,
            [PatchOperation(op="Remove", path=f'members[value eq "{user_id}"]')],
        )

        repo.remove_member.assert_called_once_with(db_group.id, user_id, tenant_id=ANY)

    async def test_raises_conflict_when_display_name_belongs_to_another_group(self):
        repo = AsyncMock()
        db_group = _make_db_group("Engineering")
        other_group = _make_db_group("Taken")
        repo.get_by_id.return_value = db_group
        repo.get_by_name.return_value = other_group

        service = _make_service(repo)

        with pytest.raises(ScimGroupConflictError):
            await service.patch_group(
                db_group.id,
                [PatchOperation(op="Replace", path="displayName", value="Taken")],
            )

        repo.update.assert_not_called()

    async def test_raises_not_found(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimGroupNotFoundError):
            await service.patch_group(uuid4(), [])


class TestDeleteGroup:
    async def test_soft_deletes_group(self):
        repo = AsyncMock()
        db_group = _make_db_group()
        repo.get_by_id.return_value = db_group

        service = _make_service(repo)
        await service.delete_group(db_group.id)

        repo.delete.assert_called_once_with(db_group.id, tenant_id=ANY)

    async def test_raises_not_found(self):
        repo = AsyncMock()
        repo.get_by_id_including_deleted.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimGroupNotFoundError):
            await service.delete_group(uuid4())
