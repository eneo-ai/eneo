from datetime import datetime, timezone
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.scim.constants import SCIM_FILTER_MAX_RESULTS
from eneo.scim.domain.errors import (
    ScimUserConflictError,
    ScimUserNotFoundError,
    ScimValidationError,
)
from eneo.scim.schemas.common import ScimFilter
from eneo.scim.schemas.user import PatchOperation, ScimUserRequest, ScimUserState
from eneo.scim.services.user_service import ScimUserService


def _make_db_user(user_name: str = "jane@example.com", active: bool = True):
    m = MagicMock()
    m.id = uuid4()
    m.external_id = None
    m.username = user_name
    m.email = user_name
    m.state = ScimUserState.ACTIVE if active else ScimUserState.DELETED
    m.deleted_at = None if active else datetime.now(timezone.utc)
    m.created_at = datetime.now(timezone.utc)
    m.updated_at = datetime.now(timezone.utc)
    return m


def _make_service(repo=None) -> ScimUserService:
    from eneo.scim.repositories.user_repository import ScimUserRepository

    repo = repo or AsyncMock(spec=ScimUserRepository)
    if isinstance(repo.get_by_username.return_value, AsyncMock):
        repo.get_by_username.return_value = None
    if isinstance(repo.get_by_email.return_value, AsyncMock):
        repo.get_by_email.return_value = None
    if isinstance(repo.get_by_external_id.return_value, AsyncMock):
        repo.get_by_external_id.return_value = None
    if isinstance(repo.email_exists_in_other_tenant.return_value, AsyncMock):
        repo.email_exists_in_other_tenant.return_value = False
    return ScimUserService(repository=repo, tenant_id=uuid4())


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
        with pytest.raises(
            ScimUserConflictError, match="already in use by another tenant"
        ):
            await service.create_user(CREATE_REQUEST)

        repo.create.assert_not_called()

    async def test_logs_warning_for_email_in_other_tenant(self, caplog):
        """Cross-tenant email collisions (Edge Case 2) must surface as a
        WARNING. Without it, operators only see a 409 in the request log with
        no explanation of why."""
        import logging

        from eneo.scim.services.user_service import logger as svc_logger

        repo = AsyncMock()
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = None
        repo.email_exists_in_other_tenant.return_value = True

        service = _make_service(repo)
        with caplog.at_level(logging.WARNING):
            svc_logger.addHandler(caplog.handler)
            try:
                with pytest.raises(ScimUserConflictError):
                    await service.create_user(CREATE_REQUEST)
            finally:
                svc_logger.removeHandler(caplog.handler)

        matching = [
            r
            for r in caplog.records
            if r.levelname == "WARNING"
            and r.message == "scim.user.cross_tenant_email_conflict"
        ]
        assert matching, (
            f"Expected scim.user.cross_tenant_email_conflict WARNING. Got: "
            f"{[(r.levelname, r.message) for r in caplog.records]}"
        )
        assert matching[0].email == "jane@example.com"

    async def test_raises_conflict_for_existing_email_in_tenant(self):
        repo = AsyncMock()
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = _make_db_user("other@example.com")
        repo.email_exists_in_other_tenant.return_value = False

        service = _make_service(repo)
        request = ScimUserRequest(
            userName="jane",
            emails=[{"value": "other@example.com", "primary": True}],
        )

        with pytest.raises(ScimUserConflictError, match="Email"):
            await service.create_user(request)

        repo.create.assert_not_called()

    async def test_raises_conflict_for_existing_external_id(self):
        repo = AsyncMock()
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = None
        repo.get_by_external_id.return_value = _make_db_user("other@example.com")
        repo.email_exists_in_other_tenant.return_value = False

        service = _make_service(repo)
        request = ScimUserRequest(userName="jane@example.com", externalId="ext-123")

        with pytest.raises(ScimUserConflictError, match="External ID"):
            await service.create_user(request)

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
        """When userName not found but email matches an existing user with no
        external_id (the migration case: claiming a pre-existing local user
        for SCIM management), link and return that user."""
        repo = AsyncMock()
        existing = _make_db_user(user_name="jane")  # different username format
        existing.email = "jane@example.com"
        existing.external_id = None  # explicit: migration case
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

    async def test_reconcile_refuses_when_existing_user_has_external_id(self):
        """If the email-matched user already carries an external_id, silently
        rebinding their identity would let the SCIM client take over an
        account that's already SCIM-managed. Must raise conflict instead."""
        repo = AsyncMock()
        existing = _make_db_user(user_name="jane")
        existing.email = "jane@example.com"
        existing.external_id = "existing-entra-guid-A"  # already SCIM-managed
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = existing

        service = _make_service(repo)
        request = ScimUserRequest(
            userName="jane.new@example.com",
            emails=[],
            externalId="incoming-entra-guid-B",
        )

        with pytest.raises(ScimUserConflictError, match="different external_id"):
            await service.create_user(request)

        repo.update.assert_not_called()
        repo.create.assert_not_called()
        # State untouched — no silent rebind
        assert existing.external_id == "existing-entra-guid-A"
        assert existing.username == "jane"

    async def test_reconcile_logs_warning_with_before_and_after_state(self, caplog):
        """Reconciliation rebinds an existing local account's identity. Even
        in the legitimate migration case, this is a significant state change
        that must surface in operator monitoring (WARNING, not INFO), with
        enough context to reason about what was claimed."""
        import logging

        from eneo.scim.services.user_service import logger as svc_logger

        repo = AsyncMock()
        existing = _make_db_user(user_name="jane_local")
        existing.email = "jane@example.com"
        existing.external_id = None
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = existing
        repo.update.return_value = existing

        service = _make_service(repo)
        request = ScimUserRequest(
            userName="jane.smith@example.com",
            emails=[],
            externalId="entra-guid-123",
        )

        with caplog.at_level(logging.WARNING):
            svc_logger.addHandler(caplog.handler)
            try:
                await service.create_user(request)
            finally:
                svc_logger.removeHandler(caplog.handler)

        warns = [r for r in caplog.records if r.levelname == "WARNING"]
        reconcile_warns = [r for r in warns if r.message == "scim.user.reconciled"]
        assert reconcile_warns, (
            f"Expected scim.user.reconciled WARNING. Got: "
            f"{[(r.levelname, r.message) for r in caplog.records]}"
        )
        rec = reconcile_warns[0]
        assert rec.previous_username == "jane_local"
        assert rec.new_username == "jane.smith@example.com"
        assert rec.new_external_id == "entra-guid-123"
        assert rec.email == "jane@example.com"

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

    async def test_reactivation_raises_conflict_for_existing_external_id(self):
        repo = AsyncMock()
        inactive = _make_db_user(active=False)
        other_user = _make_db_user("taken@example.com")
        repo.get_by_username.return_value = inactive
        repo.get_by_external_id.return_value = other_user

        service = _make_service(repo)
        request = ScimUserRequest(userName="jane@example.com", externalId="ext-123")

        with pytest.raises(ScimUserConflictError, match="External ID"):
            await service.create_user(request)

        repo.update.assert_not_called()

    async def test_create_with_active_false_provisions_inactive_user(self):
        """A SCIM create with active=false must NOT result in an active account.
        The IdP is the source of truth for the activation state, so the new
        row is provisioned soft-deleted."""
        repo = AsyncMock()
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = None
        repo.email_exists_in_other_tenant.return_value = False
        repo.create.side_effect = lambda m: m

        service = _make_service(repo)
        request = ScimUserRequest(userName="jane@example.com", active=False)
        result = await service.create_user(request)

        created = repo.create.call_args.args[0]
        assert created.state == ScimUserState.DELETED
        assert created.deleted_at is not None
        assert result.active is False

    async def test_reconcile_with_active_false_deactivates_existing_user(self):
        """Reconciling (claiming) an active local account with active=false must
        leave it deprovisioned, not silently active."""
        repo = AsyncMock()
        existing = _make_db_user(user_name="jane")  # active local account
        existing.email = "jane@example.com"
        existing.external_id = None  # migration case
        repo.get_by_username.return_value = None
        repo.get_by_email.return_value = existing
        repo.update.return_value = existing

        service = _make_service(repo)
        request = ScimUserRequest(
            userName="jane@example.com",
            externalId="entra-guid-123",
            active=False,
        )
        result = await service.create_user(request)

        repo.create.assert_not_called()
        assert existing.external_id == "entra-guid-123"
        assert existing.state == ScimUserState.DELETED
        assert existing.deleted_at is not None
        assert result.active is False

    async def test_reprovision_inactive_user_with_active_false_stays_deleted(self):
        """A create targeting an already soft-deleted row with active=false must
        rebind the externalId but keep the row deprovisioned — no reactivation."""
        repo = AsyncMock()
        inactive = _make_db_user(active=False)
        original_deleted_at = inactive.deleted_at
        repo.get_by_username.return_value = inactive
        repo.update.return_value = inactive

        service = _make_service(repo)
        request = ScimUserRequest(
            userName="jane@example.com", externalId="new-ext-id", active=False
        )
        result = await service.create_user(request)

        repo.create.assert_not_called()
        assert inactive.state == ScimUserState.DELETED
        # deleted_at preserved (idempotent) — not bumped to now()
        assert inactive.deleted_at == original_deleted_at
        assert inactive.external_id == "new-ext-id"
        assert result.active is False


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

    async def test_count_above_max_is_clamped_to_advertised_max(self):
        """A client requesting more than the advertised maxResults must not get
        more than maxResults — the cap is a contract + performance guarantee."""
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(count=SCIM_FILTER_MAX_RESULTS + 5000)
        _, kwargs = repo.list.call_args
        assert kwargs["limit"] == SCIM_FILTER_MAX_RESULTS

    async def test_omitted_count_defaults_to_max_not_unbounded(self):
        """An omitted count must bound the query to maxResults rather than
        dumping the whole tenant."""
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users()
        _, kwargs = repo.list.call_args
        assert kwargs["limit"] == SCIM_FILTER_MAX_RESULTS

    async def test_passes_none_filter_when_no_filter(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str=None)
        repo.count.assert_called_once_with(tenant_id=ANY, scim_filter=None)
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=None,
            scim_sort=None,
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_eq_filter_on_username(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str='userName eq "jane@example.com"')
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=ScimFilter("userName", "eq", "jane@example.com"),
            scim_sort=None,
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_co_filter_on_username(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str='userName co "jane"')
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=ScimFilter("userName", "co", "jane"),
            scim_sort=None,
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_sw_filter_on_username(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str='userName sw "j"')
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=ScimFilter("userName", "sw", "j"),
            scim_sort=None,
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_pr_filter_on_username(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str="userName pr")
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=ScimFilter("userName", "pr", None),
            scim_sort=None,
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_eq_filter_on_external_id(self):
        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(filter_str='externalId eq "aad-guid-123"')
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=ScimFilter("externalId", "eq", "aad-guid-123"),
            scim_sort=None,
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_sort_by_username_ascending(self):
        from eneo.scim.schemas.common import ScimSort

        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(sort_by="userName", sort_order="ascending")
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=None,
            scim_sort=ScimSort("userName", "ascending"),
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )

    async def test_sort_by_username_descending(self):
        from eneo.scim.schemas.common import ScimSort

        repo = self._make_repo()
        service = _make_service(repo)
        await service.list_users(sort_by="userName", sort_order="descending")
        repo.list.assert_called_once_with(
            tenant_id=ANY,
            scim_filter=None,
            scim_sort=ScimSort("userName", "descending"),
            offset=0,
            limit=SCIM_FILTER_MAX_RESULTS,
        )


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

    async def test_raises_conflict_when_username_belongs_to_another_user(self):
        repo = AsyncMock()
        db_user = _make_db_user("jane@example.com")
        other_user = _make_db_user("taken@example.com")
        repo.get_by_id.return_value = db_user
        repo.get_by_username.return_value = other_user

        service = _make_service(repo)
        request = ScimUserRequest(userName="taken@example.com")

        with pytest.raises(ScimUserConflictError, match="already exists"):
            await service.replace_user(db_user.id, request)

        repo.update.assert_not_called()

    async def test_raises_conflict_when_external_id_belongs_to_another_user(self):
        repo = AsyncMock()
        db_user = _make_db_user("jane@example.com")
        other_user = _make_db_user("taken@example.com")
        repo.get_by_id.return_value = db_user
        repo.get_by_external_id.return_value = other_user

        service = _make_service(repo)
        request = ScimUserRequest(userName="jane@example.com", externalId="ext-123")

        with pytest.raises(ScimUserConflictError, match="External ID"):
            await service.replace_user(db_user.id, request)

        repo.update.assert_not_called()


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

        assert db_user.state == ScimUserState.DELETED
        repo.update.assert_called_once_with(db_user)

    async def test_patch_sets_active_false_with_string_value(self):
        """Azure Entra sends `active` as the STRING "False" in PATCH payloads.

        Regression: Python's `bool("False")` is True, so without explicit
        coercion the user would remain active and Azure (which gets 200 OK
        back) would never retry. `_coerce_active` parses string forms case-
        insensitively.
        """
        repo = AsyncMock()
        db_user = _make_db_user(active=True)
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [PatchOperation(op="Replace", path="active", value="False")],
        )

        assert db_user.state == ScimUserState.DELETED

    async def test_patch_sets_active_false_with_lowercase_string(self):
        """Lowercase "false" must deactivate too (case-insensitive parse)."""
        repo = AsyncMock()
        db_user = _make_db_user(active=True)
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [PatchOperation(op="Replace", path="active", value="false")],
        )

        assert db_user.state == ScimUserState.DELETED

    async def test_patch_sets_active_true_with_string_value(self):
        """The string "True" must reactivate (the symmetric case)."""
        repo = AsyncMock()
        db_user = _make_db_user(active=False)
        db_user.state = ScimUserState.DELETED
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [PatchOperation(op="Replace", path="active", value="True")],
        )

        assert db_user.state == ScimUserState.ACTIVE

    async def test_patch_updates_external_id(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [
                PatchOperation(
                    op="Replace", path="externalId", value="entra-object-id-123"
                )
            ],
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
            [
                PatchOperation(
                    op="Replace",
                    path="emails",
                    value=[{"value": "new@example.com", "primary": True}],
                )
            ],
        )

        assert db_user.email == "new@example.com"

    async def test_patch_emails_with_azure_filter_path(self):
        """Azure Entra ID sends email updates with a filter-expression path.

        Regression: Eneo previously only matched simple paths like "emails";
        the filter form was silently no-op'd because the full path string
        (`emails[type eq "work"].value`) did not match any branch in
        _apply_user_attr. _parse_patch_path now strips the filter and
        sub-attribute selector so the update reaches the email column.
        """
        repo = AsyncMock()
        db_user = _make_db_user()
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [
                PatchOperation(
                    op="Replace",
                    path='emails[type eq "work"].value',
                    value="updated@example.com",
                )
            ],
        )

        assert db_user.email == "updated@example.com"

    async def test_patch_emails_picks_primary_over_first(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.patch_user(
            db_user.id,
            [
                PatchOperation(
                    op="Replace",
                    path="emails",
                    value=[
                        {"value": "first@example.com", "primary": False},
                        {"value": "primary@example.com", "primary": True},
                    ],
                )
            ],
        )

        assert db_user.email == "primary@example.com"

    async def test_raises_not_found(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimUserNotFoundError):
            await service.patch_user(uuid4(), [])

    async def test_raises_conflict_when_external_id_belongs_to_another_user(self):
        repo = AsyncMock()
        db_user = _make_db_user()
        other_user = _make_db_user("taken@example.com")
        repo.get_by_id.return_value = db_user
        repo.get_by_external_id.return_value = other_user

        service = _make_service(repo)

        with pytest.raises(ScimUserConflictError, match="External ID"):
            await service.patch_user(
                db_user.id,
                [PatchOperation(op="Replace", path="externalId", value="ext-123")],
            )

        repo.update.assert_not_called()


class TestDeleteUser:
    async def test_deactivates_active_user(self):
        repo = AsyncMock()
        db_user = _make_db_user(active=True)
        repo.get_by_id.return_value = db_user
        repo.update.return_value = db_user

        service = _make_service(repo)
        await service.delete_user(db_user.id)

        assert db_user.state == ScimUserState.DELETED
        repo.update.assert_called_once_with(db_user)

    async def test_raises_not_found_for_missing_user(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = None

        service = _make_service(repo)
        with pytest.raises(ScimUserNotFoundError):
            await service.delete_user(uuid4())

    async def test_already_deleted_user_is_idempotent_noop(self):
        repo = AsyncMock()
        repo.get_by_id.return_value = _make_db_user(active=False)

        service = _make_service(repo)
        # SCIM DELETE on an already-deprovisioned user is idempotent:
        # it must not raise and must not issue a second write.
        await service.delete_user(uuid4())

        repo.update.assert_not_called()
