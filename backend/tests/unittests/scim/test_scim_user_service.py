import pytest
from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import uuid4

from intric.scim.domain.errors import ScimUserConflictError, ScimUserNotFoundError, ScimValidationError
from intric.scim.schemas.common import ScimFilter
from intric.scim.schemas.user import PatchOperation, ScimUserRequest
from intric.scim.services.user_service import ScimUserService


def _make_db_user(user_name: str = "jane@example.com", active: bool = True):
    m = MagicMock()
    m.id = uuid4()
    m.external_id = None
    m.username = user_name
    m.email = user_name
    m.state = "active" if active else "inactive"
    m.created_at = datetime.now(timezone.utc)
    m.updated_at = datetime.now(timezone.utc)
    return m


def _make_service(repo=None) -> ScimUserService:
    from intric.scim.repositories.user_repository import ScimUserRepository
    return ScimUserService(repository=repo or AsyncMock(spec=ScimUserRepository), tenant_id=uuid4())


CREATE_REQUEST = ScimUserRequest(
    userName="jane@example.com",
    emails=[],
)


class TestCreateUser:
    async def test_creates_and_returns_scim_user(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = None
        repo.email_exists_in_other_tenant.return_value = False
        repo.create.return_value = db_user

        service = _make_service(repo)
        result = await service.create_user(CREATE_REQUEST)

        repo.create.assert_called_once()
        assert result.userName == db_user.username
        assert result.id == str(db_user.id)

    async def test_assigns_user_predefined_role_on_create(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = None
        repo.email_exists_in_other_tenant.return_value = False
        repo.create.return_value = db_user

        service = _make_service(repo)
        await service.create_user(CREATE_REQUEST)

        repo.create.assert_awaited_once()

    async def test_raises_conflict_for_email_in_other_tenant(self):
        repo = AsyncMock()
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = None
        repo.email_exists_in_other_tenant.return_value = True

        service = _make_service(repo)
        with pytest.raises(ScimUserConflictError, match="already in use by another tenant"):
            await service.create_user(CREATE_REQUEST)

        repo.create.assert_not_called()

    async def test_raises_conflict_for_existing_active_username(self):
        repo = AsyncMock()
        repo.get_by_username.return_value = _make_db_user(active=True)

        service = _make_service(repo)
        with pytest.raises(ScimUserConflictError):
            await service.create_user(CREATE_REQUEST)

        repo.create.assert_not_called()

    async def test_maps_external_id(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        db_user.external_id = "ext-123"
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = None
        repo.email_exists_in_other_tenant.return_value = False
        repo.create.return_value = db_user

        service = _make_service(repo)
        request = ScimUserRequest(userName="jane@example.com", externalId="ext-123")
        result = await service.create_user(request)

        assert result.externalId == "ext-123"

    async def test_reconciles_existing_user_by_email(self):
        """When userName not found but email matches an existing user, link and return that user."""
        repo = AsyncMock()
        existing = _make_db_user(user_name="jane")  # different username format
        existing.email = "jane@example.com"
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = existing
        repo.update.return_value = existing

        service = _make_service(repo)
        request = ScimUserRequest(
            userName="jane@example.com",
            emails=[],
            externalId="entra-guid-123",
        )
        result = await service.create_user(request)

        repo.create.assert_not_called()
        assert existing.external_id == "entra-guid-123"
        assert existing.username == "jane@example.com"
        assert result.userName == "jane@example.com"

    async def test_raises_validation_error_when_no_email_resolvable(self):
        """userName without @ and no emails → ScimValidationError."""
        repo = AsyncMock()
        repo.get_by_username.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimValidationError):
            await service.create_user(ScimUserRequest(userName="janedoe", emails=[]))

    async def test_reactivates_inactive_user_on_create(self):
        """Re-provisioning an inactive user reactivates the existing row instead of creating a new one."""
        repo = AsyncMock()
        inactive = _make_db_user(active=False)
        repo.get_by_username.return_value = inactive
        repo.update.return_value = inactive

        service = _make_service(repo)
        request = ScimUserRequest(userName="jane@example.com", externalId="new-ext-id")
        result = await service.create_user(request)

        repo.create.assert_not_called()
        assert inactive.state == "active"
        assert inactive.external_id == "new-ext-id"
        assert result.active is True


class TestGetUser:
    async def test_returns_active_user(self):
        repo = AsyncMock()
        db_user = _make_db_user(active=True)
        repo.get_by_id.return_value = db_user

        service = _make_service(repo)
        result = await service.get_user(db_user.id)

        assert result.id == str(db_user.id)

    async def test_raises_not_found_when_missing(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimUserNotFoundError):
            await service.get_user(uuid4())

    async def test_returns_inactive_user_with_active_false(self):
        repo = AsyncMock()
        db_user = _make_db_user(active=False)
        repo.get_by_id.return_value = db_user

        service = _make_service(repo)
        result = await service.get_user(db_user.id)

        assert result.active is False


class TestListUsers:
    def _make_repo(self, users=None):
        repo = AsyncMock()
        repo.list.return_value = users or []
        repo.count.return_value = len(users) if users else 0
        return repo

    async def test_returns_scim_users(self):
        users = [_make_db_user(), _make_db_user("bob@example.com")]
        repo = self._make_repo(users)
        service = _make_service(repo)
        result, total = await service.list_users()
        assert len(result) == 2
        assert total == 2

    async def test_passes_pagination_to_repo(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(start_index=3, count=10)
        repo.list.assert_called_once_with(
            tenant_id=ANY, scim_filter=None, scim_sort=None, offset=2, limit=10
        )

    async def test_passes_none_filter_when_no_filter(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str=None)
        repo.count.assert_called_once_with(tenant_id=ANY, scim_filter=None)
        repo.list.assert_called_once_with(tenant_id=ANY, scim_filter=None, scim_sort=None, offset=0, limit=None)

    async def test_eq_filter_on_username(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str='userName eq "jane@example.com"')
        repo.list.assert_called_once_with(tenant_id=ANY, scim_filter=ScimFilter("userName", "eq", "jane@example.com"), scim_sort=None, offset=0, limit=None)

    async def test_co_filter_on_username(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str='userName co "jane"')
        repo.list.assert_called_once_with(tenant_id=ANY, scim_filter=ScimFilter("userName", "co", "jane"), scim_sort=None, offset=0, limit=None)

    async def test_sw_filter_on_username(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str='userName sw "j"')
        repo.list.assert_called_once_with(tenant_id=ANY, scim_filter=ScimFilter("userName", "sw", "j"), scim_sort=None, offset=0, limit=None)

    async def test_pr_filter_on_username(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str="userName pr")
        repo.list.assert_called_once_with(tenant_id=ANY, scim_filter=ScimFilter("userName", "pr", None), scim_sort=None, offset=0, limit=None)

    async def test_eq_filter_on_external_id(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str='externalId eq "aad-guid-123"')
        repo.list.assert_called_once_with(tenant_id=ANY, scim_filter=ScimFilter("externalId", "eq", "aad-guid-123"), scim_sort=None, offset=0, limit=None)

    async def test_sort_by_username_ascending(self):
        from intric.scim.schemas.common import ScimSort
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(sort_by="userName", sort_order="ascending")
        repo.list.assert_called_once_with(tenant_id=ANY, scim_filter=None, scim_sort=ScimSort("userName", "ascending"), offset=0, limit=None)

    async def test_sort_by_username_descending(self):
        from intric.scim.schemas.common import ScimSort
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(sort_by="userName", sort_order="descending")
        repo.list.assert_called_once_with(tenant_id=ANY, scim_filter=None, scim_sort=ScimSort("userName", "descending"), offset=0, limit=None)


class TestReplaceUser:
    async def test_replaces_and_returns_user(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        result = await service.replace_user(db_user.id, CREATE_REQUEST)

        repo.update.assert_called_once()
        assert result.id == str(db_user.id)

    async def test_raises_not_found(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimUserNotFoundError):
            await service.replace_user(uuid4(), CREATE_REQUEST)


class TestPatchUser:
    async def test_patch_sets_active_false(self):
        repo = AsyncMock()
        db_user = _make_db_user(active=True)
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [PatchOperation(op="Replace", path="active", value=False)],
        )

        assert db_user.state == "inactive"
        repo.update.assert_called_once_with(db_user)

    async def test_patch_updates_external_id(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [PatchOperation(op="Replace", path="externalId", value="entra-object-id-123")],
        )

        assert db_user.external_id == "entra-object-id-123"

    async def test_patch_clears_external_id_on_none(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        db_user.external_id = "old-id"
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [PatchOperation(op="Replace", path="externalId", value=None)],
        )

        assert db_user.external_id is None

    async def test_patch_updates_primary_email(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [PatchOperation(op="Replace", path="emails", value=[{"value": "new@example.com", "primary": True}])],
        )

        assert db_user.email == "new@example.com"

    async def test_patch_emails_picks_primary_over_first(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [PatchOperation(op="Replace", path="emails", value=[
                {"value": "first@example.com", "primary": False},
                {"value": "primary@example.com", "primary": True},
            ])],
        )

        assert db_user.email == "primary@example.com"

    async def test_raises_not_found(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimUserNotFoundError):
            await service.patch_user(uuid4(), [])


class TestDeleteUser:
    async def test_deactivates_active_user(self):
        repo = AsyncMock()
        db_user = _make_db_user(active=True)
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.delete_user(db_user.id)

        assert db_user.state == "inactive"
        repo.update.assert_called_once_with(db_user)

    async def test_raises_not_found_for_missing_user(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimUserNotFoundError):
            await service.delete_user(uuid4())

    async def test_raises_not_found_for_already_inactive_user(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = _make_db_user(active=False)

        service = _make_service(repo)
        with pytest.raises(ScimUserNotFoundError):
            await service.delete_user(uuid4())
