"""
Unit tests for IntegrationKnowledgeService.

Tests cover:
- Creating integration knowledge with different auth types (user_oauth, tenant_app, service_account)
- Renaming integration knowledge items
- Permission enforcement for rename operations
- Authorization checks for cross-space operations
- Remove knowledge with different auth types (user_oauth, tenant_app, service_account)
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import sqlalchemy as sa

from eneo.integration.application.integration_knowledge_service import (
    IntegrationKnowledgeService,
)
from eneo.integration.application.user_integration_service import UserIntegrationService
from eneo.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from eneo.integration.infrastructure.auth_service.org_token_provider import (
    OrgTokenProvider,
    SharePointCredentialsInvalidError,
)
from eneo.integration.infrastructure.detached_tasks import pending_detached_tasks
from eneo.integration.infrastructure.sharepoint_subscription_service import (
    SharePointSubscriptionService,
)
from eneo.main.container.container import Container
from eneo.main.exceptions import (
    BadRequestException,
    NotFoundException,
    UnauthorizedException,
)
from eneo.roles.permissions import Permission
from tests.fixtures import TEST_USER


@pytest.fixture
def actor():
    return MagicMock()


@pytest.fixture
def space():
    space = MagicMock()
    space.id = uuid4()
    space.tenant_id = TEST_USER.tenant_id
    return space


@pytest.fixture
def integration_knowledge(space):
    """Create a mock integration knowledge entity."""
    user_integration = MagicMock()
    user_integration.user_id = TEST_USER.id
    user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
    user_integration.authenticated = True
    user_integration.id = uuid4()
    user_integration.auth_type = "user_oauth"
    user_integration.tenant_app_id = None

    knowledge = MagicMock(spec=IntegrationKnowledge)
    knowledge.id = uuid4()
    knowledge.name = "Original Name"
    knowledge.original_name = "Original Name"
    knowledge.space_id = space.id
    knowledge.tenant_id = space.tenant_id
    knowledge.created_at = datetime.now()
    knowledge.updated_at = datetime.now()
    knowledge.user_integration = user_integration
    return knowledge


@pytest.fixture
def service(actor: MagicMock, space: MagicMock, integration_knowledge: MagicMock):
    actor_manager = MagicMock()
    actor_manager.get_space_actor_from_space.return_value = actor

    space_repo = AsyncMock()
    space_repo.one.return_value = space
    space.get_integration_knowledge.return_value = integration_knowledge

    integration_knowledge_repo = AsyncMock()
    integration_knowledge_repo.one.return_value = integration_knowledge
    integration_knowledge_repo.update.return_value = integration_knowledge

    service = IntegrationKnowledgeService(
        job_service=AsyncMock(),
        user=TEST_USER,
        oauth_token_repo=AsyncMock(),
        space_repo=space_repo,
        integration_knowledge_repo=integration_knowledge_repo,
        embedding_model_repo=AsyncMock(),
        user_integration_service=UserIntegrationService(
            user_integration_repo=AsyncMock(),
            tenant_integration_repo=AsyncMock(),
            user=TEST_USER,
            actor_manager=actor_manager,
            tenant_sharepoint_app_repo=AsyncMock(),
        ),
        actor_manager=actor_manager,
        sharepoint_subscription_service=AsyncMock(),
        tenant_sharepoint_app_repo=AsyncMock(),
        tenant_app_auth_service=AsyncMock(),
        org_token_provider=OrgTokenProvider(
            tenant_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
        ),
    )

    return service


@pytest.mark.parametrize(
    "method, permission, kwargs",
    [
        pytest.param("remove_knowledge", "can_delete_integrations", {}, id="remove"),
        pytest.param("trigger_full_sync", "can_edit_integrations", {}, id="sync"),
        pytest.param(
            "update_knowledge_name",
            "can_edit_integrations",
            {"name": "New"},
            id="rename",
        ),
    ],
)
async def test_a_non_member_cannot_probe_item_ids_through_mutations(
    service: IntegrationKnowledgeService,
    actor: MagicMock,
    space: MagicMock,
    method: str,
    permission: str,
    kwargs: dict[str, str],
):
    """Membership is refused before the lookup, so an unknown id is a 403, not a 404."""
    getattr(actor, permission).return_value = False
    space.get_integration_knowledge.side_effect = NotFoundException()

    with pytest.raises(UnauthorizedException):
        await getattr(service, method)(
            space_id=space.id, integration_knowledge_id=uuid4(), **kwargs
        )

    space.get_integration_knowledge.assert_not_called()


class TestTenantAppAdminPermission:
    """Tests for admin permission enforcement on tenant_app integrations.

    Verifies that non-admin users (e.g. editors with space-level permissions)
    cannot delete or rename organization-wide SharePoint integrations that
    use tenant_app authentication.
    """

    @pytest.fixture
    def non_admin_user(self):
        from eneo.users.user import UserInDB

        user = MagicMock(spec=UserInDB)
        user.id = uuid4()
        user.tenant_id = TEST_USER.tenant_id
        user.permissions = [Permission.INTEGRATIONS]  # Has integrations but NOT ADMIN
        return user

    @pytest.fixture
    def tenant_app_knowledge(self, space):
        """Knowledge item backed by tenant_app auth."""
        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.id = uuid4()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()

        knowledge = MagicMock(spec=IntegrationKnowledge)
        knowledge.id = uuid4()
        knowledge.name = "Org SharePoint Site"
        knowledge.space_id = space.id
        knowledge.tenant_id = space.tenant_id
        knowledge.user_integration = user_integration
        knowledge.integration_type = "sharepoint"
        knowledge.sharepoint_subscription_id = None
        return knowledge

    @pytest.fixture
    def user_oauth_knowledge(self, space):
        """Knowledge item backed by user_oauth auth."""
        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.id = uuid4()
        user_integration.auth_type = "user_oauth"
        user_integration.tenant_app_id = None

        knowledge = MagicMock(spec=IntegrationKnowledge)
        knowledge.id = uuid4()
        knowledge.name = "Personal SharePoint Site"
        knowledge.space_id = space.id
        knowledge.tenant_id = space.tenant_id
        knowledge.user_integration = user_integration
        knowledge.integration_type = "sharepoint"
        knowledge.sharepoint_subscription_id = None
        return knowledge

    def _make_service(self, user, actor, space, knowledge):
        actor.can_edit_integrations.return_value = True
        actor.can_delete_integrations.return_value = True

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space.get_integration_knowledge.return_value = knowledge
        space.tenant_space_id = uuid4()

        space_repo = AsyncMock()
        space_repo.one.return_value = space

        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.one.return_value = knowledge
        integration_knowledge_repo.update.return_value = knowledge

        return IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=user,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=user,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

    # --- remove_knowledge ---

    async def test_remove_knowledge_tenant_app_requires_admin(
        self, non_admin_user, actor, space, tenant_app_knowledge
    ):
        service = self._make_service(non_admin_user, actor, space, tenant_app_knowledge)

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.remove_knowledge(
                space_id=space.id,
                integration_knowledge_id=tenant_app_knowledge.id,
            )
        assert "Admin permission is required" in str(exc_info.value)

    async def test_remove_knowledge_tenant_app_admin_succeeds(
        self, actor, space, tenant_app_knowledge
    ):
        service = self._make_service(TEST_USER, actor, space, tenant_app_knowledge)

        await service.remove_knowledge(
            space_id=space.id,
            integration_knowledge_id=tenant_app_knowledge.id,
        )
        service.integration_knowledge_repo.remove.assert_called_once_with(
            id=tenant_app_knowledge.id
        )

    async def test_remove_knowledge_user_oauth_no_admin_required(
        self, non_admin_user, actor, space, user_oauth_knowledge
    ):
        service = self._make_service(non_admin_user, actor, space, user_oauth_knowledge)

        await service.remove_knowledge(
            space_id=space.id,
            integration_knowledge_id=user_oauth_knowledge.id,
        )
        service.integration_knowledge_repo.remove.assert_called_once_with(
            id=user_oauth_knowledge.id
        )

    # --- update_knowledge_name ---

    async def test_rename_knowledge_tenant_app_requires_admin(
        self, non_admin_user, actor, space, tenant_app_knowledge
    ):
        service = self._make_service(non_admin_user, actor, space, tenant_app_knowledge)

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.update_knowledge_name(
                space_id=space.id,
                integration_knowledge_id=tenant_app_knowledge.id,
                name="New Name",
            )
        assert "Admin permission is required" in str(exc_info.value)

    async def test_rename_knowledge_tenant_app_admin_succeeds(
        self, actor, space, tenant_app_knowledge
    ):
        service = self._make_service(TEST_USER, actor, space, tenant_app_knowledge)

        await service.update_knowledge_name(
            space_id=space.id,
            integration_knowledge_id=tenant_app_knowledge.id,
            name="New Name",
        )
        service.integration_knowledge_repo.rename.assert_awaited_once_with(
            tenant_app_knowledge.id, "New Name"
        )

    async def test_rename_knowledge_user_oauth_no_admin_required(
        self, non_admin_user, actor, space, user_oauth_knowledge
    ):
        service = self._make_service(non_admin_user, actor, space, user_oauth_knowledge)

        await service.update_knowledge_name(
            space_id=space.id,
            integration_knowledge_id=user_oauth_knowledge.id,
            name="New Name",
        )
        service.integration_knowledge_repo.rename.assert_awaited_once_with(
            user_oauth_knowledge.id, "New Name"
        )

    # --- update_wrapper_name ---

    async def test_update_wrapper_name_tenant_app_requires_admin(
        self, non_admin_user, actor, space, tenant_app_knowledge
    ):
        wrapper_id = uuid4()
        tenant_app_knowledge.wrapper_id = wrapper_id
        space.integration_knowledge_list = [tenant_app_knowledge]

        service = self._make_service(non_admin_user, actor, space, tenant_app_knowledge)

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.update_wrapper_name(
                space_id=space.id,
                wrapper_id=wrapper_id,
                name="New Wrapper Name",
            )
        assert "Admin permission is required" in str(exc_info.value)

    # --- remove_wrapper_knowledge ---

    async def test_remove_wrapper_knowledge_tenant_app_requires_admin(
        self, non_admin_user, actor, space, tenant_app_knowledge
    ):
        wrapper_id = uuid4()
        tenant_app_knowledge.wrapper_id = wrapper_id
        space.integration_knowledge_list = [tenant_app_knowledge]

        service = self._make_service(non_admin_user, actor, space, tenant_app_knowledge)

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.remove_wrapper_knowledge(
                space_id=space.id,
                wrapper_id=wrapper_id,
            )
        assert "Admin permission is required" in str(exc_info.value)


class TestUpdateKnowledgeName:
    """Tests for the update_knowledge_name method."""

    async def test_rename_knowledge_success(
        self,
        service: IntegrationKnowledgeService,
        actor: MagicMock,
        integration_knowledge: MagicMock,
    ):
        """Only the name column is written; the item is re-read for the response."""
        actor.can_edit_integrations.return_value = True
        new_name = "New Knowledge Name"

        updated = await service.update_knowledge_name(
            space_id=integration_knowledge.space_id,
            integration_knowledge_id=integration_knowledge.id,
            name=new_name,
        )

        service.integration_knowledge_repo.rename.assert_awaited_once_with(
            integration_knowledge.id, new_name
        )
        # A full-row write would put back the sync state of a stale copy.
        service.integration_knowledge_repo.update.assert_not_called()
        # The renamed item is served back to the UI, so it carries its count.
        assert updated is integration_knowledge
        service.integration_knowledge_repo.attach_document_counts.assert_awaited_once_with(
            [integration_knowledge]
        )

    async def test_rename_knowledge_unauthorized_without_edit_permission(
        self,
        service: IntegrationKnowledgeService,
        actor: MagicMock,
        integration_knowledge: MagicMock,
    ):
        """Test that users without edit permission cannot rename."""
        actor.can_edit_integrations.return_value = False

        with pytest.raises(UnauthorizedException):
            await service.update_knowledge_name(
                space_id=integration_knowledge.space_id,
                integration_knowledge_id=integration_knowledge.id,
                name="New Name",
            )

        service.integration_knowledge_repo.rename.assert_not_called()

    async def test_rename_knowledge_unauthorized_from_different_space(
        self,
        service: IntegrationKnowledgeService,
        actor: MagicMock,
        space: MagicMock,
        integration_knowledge: MagicMock,
    ):
        """Test that knowledge cannot be renamed from a different space."""
        actor.can_edit_integrations.return_value = True
        # Knowledge belongs to a different space
        integration_knowledge.space_id = uuid4()

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.update_knowledge_name(
                space_id=space.id,
                integration_knowledge_id=integration_knowledge.id,
                name="New Name",
            )

        assert "Cannot rename knowledge from this space" in str(exc_info.value)
        service.integration_knowledge_repo.rename.assert_not_called()

    async def test_rename_reads_the_item_after_writing_the_name(
        self,
        service: IntegrationKnowledgeService,
        actor: MagicMock,
        integration_knowledge: MagicMock,
    ):
        """The response shows what the row holds after the rename, including a
        sync's state committed while the rename waited for its row lock."""
        actor.can_edit_integrations.return_value = True
        calls = MagicMock()
        calls.attach_mock(service.integration_knowledge_repo.rename, "rename")
        calls.attach_mock(service.integration_knowledge_repo.one, "one")

        await service.update_knowledge_name(
            space_id=integration_knowledge.space_id,
            integration_knowledge_id=integration_knowledge.id,
            name="New Name",
        )

        assert [call[0] for call in calls.mock_calls] == ["rename", "one"]
        service.integration_knowledge_repo.one.assert_called_once_with(
            id=integration_knowledge.id
        )


class TestWrapperOperations:
    async def test_update_wrapper_name_updates_all_owned_items(self, actor, space):
        actor.can_edit_integrations.return_value = True

        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.auth_type = "user_oauth"

        wrapper_id = uuid4()
        first = MagicMock(spec=IntegrationKnowledge)
        first.id = uuid4()
        first.space_id = space.id
        first.wrapper_id = wrapper_id
        first.wrapper_name = "Old"
        first.user_integration = user_integration

        second = MagicMock(spec=IntegrationKnowledge)
        second.id = uuid4()
        second.space_id = space.id
        second.wrapper_id = wrapper_id
        second.wrapper_name = "Old"
        second.user_integration = user_integration

        space.integration_knowledge_list = [first, second]

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space_repo = AsyncMock()
        space_repo.one.return_value = space

        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.get_by_ids.return_value = [second, first]

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        result = await service.update_wrapper_name(
            space_id=space.id,
            wrapper_id=wrapper_id,
            name="  New wrapper name  ",
        )

        integration_knowledge_repo.rename_wrapper.assert_awaited_once_with(
            [first.id, second.id], "New wrapper name"
        )
        integration_knowledge_repo.update.assert_not_called()
        assert result == [first, second]
        integration_knowledge_repo.attach_document_counts.assert_awaited_once_with(
            [first, second]
        )

    async def test_remove_wrapper_knowledge_deletes_all_owned_items(self, actor, space):
        actor.can_delete_integrations.return_value = True

        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.auth_type = "user_oauth"

        wrapper_id = uuid4()
        first = MagicMock(spec=IntegrationKnowledge)
        first.id = uuid4()
        first.space_id = space.id
        first.wrapper_id = wrapper_id
        first.user_integration = user_integration

        second = MagicMock(spec=IntegrationKnowledge)
        second.id = uuid4()
        second.space_id = space.id
        second.wrapper_id = wrapper_id
        second.user_integration = user_integration

        space.integration_knowledge_list = [first, second]

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space_repo = AsyncMock()
        space_repo.one.return_value = space

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )
        first.sharepoint_subscription_id = None
        second.sharepoint_subscription_id = None
        space.tenant_space_id = uuid4()

        await service.remove_wrapper_knowledge(
            space_id=space.id,
            wrapper_id=wrapper_id,
        )

        assert [
            call.kwargs["id"]
            for call in service.integration_knowledge_repo.remove.await_args_list
        ] == [first.id, second.id]
        # The space aggregate loads every member, assistant and source; one
        # load serves the whole wrapper.
        space_repo.one.assert_awaited_once_with(id=space.id)


class TestRemoveKnowledge:
    """Tests for the remove_knowledge method with different auth types."""

    @pytest.fixture
    def user_integration_user_oauth(self):
        """Create a mock user_oauth integration."""
        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.id = uuid4()
        user_integration.auth_type = "user_oauth"
        user_integration.tenant_app_id = None
        return user_integration

    @pytest.fixture
    def user_integration_tenant_app(self):
        """Create a mock tenant_app integration (app oauth)."""
        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.id = uuid4()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        return user_integration

    @pytest.fixture
    def tenant_app_client_credentials(self):
        """Create a mock tenant app with client credentials (not service account)."""
        tenant_app = MagicMock()
        tenant_app.id = uuid4()
        tenant_app.is_service_account.return_value = False
        return tenant_app

    @pytest.fixture
    def tenant_app_service_account(self):
        """Create a mock tenant app with service account auth."""
        tenant_app = MagicMock()
        tenant_app.id = uuid4()
        tenant_app.is_service_account.return_value = True
        tenant_app.service_account_refresh_token = "old-refresh-token"
        return tenant_app

    @pytest.fixture
    def sharepoint_knowledge_user_oauth(self, space, user_integration_user_oauth):
        """Create mock SharePoint knowledge with user_oauth auth."""
        knowledge = MagicMock(spec=IntegrationKnowledge)
        knowledge.id = uuid4()
        knowledge.name = "SharePoint Site"
        knowledge.space_id = space.id
        knowledge.tenant_id = space.tenant_id
        knowledge.integration_type = "sharepoint"
        knowledge.sharepoint_subscription_id = uuid4()
        knowledge.user_integration = user_integration_user_oauth
        return knowledge

    @pytest.fixture
    def sharepoint_knowledge_tenant_app(self, space, user_integration_tenant_app):
        """Create mock SharePoint knowledge with tenant_app auth."""
        knowledge = MagicMock(spec=IntegrationKnowledge)
        knowledge.id = uuid4()
        knowledge.name = "SharePoint Site"
        knowledge.space_id = space.id
        knowledge.tenant_id = space.tenant_id
        knowledge.integration_type = "sharepoint"
        knowledge.sharepoint_subscription_id = uuid4()
        knowledge.user_integration = user_integration_tenant_app
        return knowledge

    async def test_remove_knowledge_cleans_up_the_subscription_on_its_own_session(
        self,
        actor,
        space,
        sharepoint_knowledge_tenant_app,
        tenant_app_client_credentials,
    ):
        """The Graph cleanup runs past the response, so it must not reuse the
        request session or its repositories."""
        actor.can_delete_integrations.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_tenant_app
        space.tenant_space_id = uuid4()
        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor
        space_repo = AsyncMock()
        space_repo.one.return_value = space
        tenant_sharepoint_app_repo = AsyncMock()
        tenant_sharepoint_app_repo.one.return_value = tenant_app_client_credentials
        tenant_app_auth_service = AsyncMock()
        tenant_app_auth_service.get_access_token.return_value = "tenant-app-token"

        request_scoped_repo = AsyncMock()
        subscription_service = SharePointSubscriptionService(request_scoped_repo)
        own_session = MagicMock()
        count = MagicMock()
        count.scalar_one.return_value = 0
        own_session.execute = AsyncMock(return_value=count)
        own_session.scalar = AsyncMock(return_value=None)

        @asynccontextmanager
        async def begin():
            yield

        own_session.begin = begin
        sessions = MagicMock()

        @asynccontextmanager
        async def session():
            yield own_session

        sessions.session = session

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=subscription_service,
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=tenant_app_auth_service,
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=tenant_sharepoint_app_repo,
                tenant_app_auth_service=tenant_app_auth_service,
                service_account_auth_service=AsyncMock(),
            ),
        )

        with patch("eneo.database.database.sessionmanager", sessions):
            await service.remove_knowledge(
                space_id=space.id,
                integration_knowledge_id=sharepoint_knowledge_tenant_app.id,
            )
            while pending_detached_tasks():
                await asyncio.gather(*pending_detached_tasks())

        own_session.execute.assert_awaited()
        request_scoped_repo.count_references.assert_not_called()
        request_scoped_repo.one_or_none.assert_not_called()
        space_repo.session.execute.assert_not_awaited()

    async def test_remove_knowledge_user_oauth_uses_oauth_token(
        self, actor, space, sharepoint_knowledge_user_oauth
    ):
        """Test that user_oauth integration uses oauth_token_repo for token."""
        actor.can_delete_integrations.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_user_oauth
        space.tenant_space_id = uuid4()  # Not an org space

        oauth_token = MagicMock()
        oauth_token.access_token = "user-oauth-token"

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space_repo = AsyncMock()
        space_repo.one.return_value = space

        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=oauth_token_repo,
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        await service.remove_knowledge(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_user_oauth.id,
        )

        # Verify oauth_token_repo was called for user_oauth
        oauth_token_repo.one.assert_called_once_with(
            user_integration_id=sharepoint_knowledge_user_oauth.user_integration.id
        )

    async def test_remove_knowledge_tenant_app_uses_tenant_app_auth(
        self,
        actor,
        space,
        sharepoint_knowledge_tenant_app,
        tenant_app_client_credentials,
    ):
        """Test that tenant_app integration uses tenant_app_auth_service for token."""
        actor.can_delete_integrations.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_tenant_app
        space.tenant_space_id = uuid4()  # Not an org space

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space_repo = AsyncMock()
        space_repo.one.return_value = space

        tenant_sharepoint_app_repo = AsyncMock()
        tenant_sharepoint_app_repo.one.return_value = tenant_app_client_credentials

        tenant_app_auth_service = AsyncMock()
        tenant_app_auth_service.get_access_token.return_value = "tenant-app-token"

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=tenant_app_auth_service,
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=tenant_sharepoint_app_repo,
                tenant_app_auth_service=tenant_app_auth_service,
                service_account_auth_service=AsyncMock(),
            ),
        )

        await service.remove_knowledge(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_tenant_app.id,
        )

        # Verify tenant_app_auth_service was called (not service_account)
        tenant_app_auth_service.get_access_token.assert_called_once_with(
            tenant_app_client_credentials, force_refresh=False
        )

    async def test_remove_knowledge_service_account_uses_service_account_auth(
        self, actor, space, sharepoint_knowledge_tenant_app, tenant_app_service_account
    ):
        """Test that service account integration uses service_account_auth_service for token."""
        actor.can_delete_integrations.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_tenant_app
        space.tenant_space_id = uuid4()  # Not an org space

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space_repo = AsyncMock()
        space_repo.one.return_value = space

        tenant_sharepoint_app_repo = AsyncMock()
        tenant_sharepoint_app_repo.one.return_value = tenant_app_service_account

        service_account_auth_service = AsyncMock()
        service_account_auth_service.refresh_access_token.return_value = {
            "access_token": "service-account-token",
            "refresh_token": "new-refresh-token",
        }

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=service_account_auth_service,
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=tenant_sharepoint_app_repo,
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=service_account_auth_service,
            ),
        )

        await service.remove_knowledge(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_tenant_app.id,
        )

        # Verify service_account_auth_service was called
        service_account_auth_service.refresh_access_token.assert_called_once_with(
            tenant_app_service_account, force_refresh=False
        )
        tenant_app_service_account.update_refresh_token.assert_called_once_with(
            "new-refresh-token"
        )
        tenant_sharepoint_app_repo.update.assert_called_once_with(
            tenant_app_service_account
        )


class TestCreateSpaceIntegrationKnowledge:
    """Tests for the create_space_integration_knowledge method with different auth types."""

    @pytest.fixture
    def embedding_model(self):
        """Create a mock embedding model."""
        model = MagicMock()
        model.id = uuid4()
        return model

    @pytest.fixture
    def space_with_embedding_model(self, embedding_model):
        """Create a mock space with embedding model."""
        space = MagicMock()
        space.id = uuid4()
        space.tenant_id = TEST_USER.tenant_id
        space.tenant_space_id = uuid4()  # Not an org space (skip distribution)
        space.is_embedding_model_in_space.return_value = True
        space.is_personal.return_value = False
        return space

    @pytest.fixture
    def user_integration_user_oauth(self, space_with_embedding_model):
        """Create a mock user_oauth integration, used from a personal space."""
        space_with_embedding_model.is_personal.return_value = True
        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.id = uuid4()
        user_integration.auth_type = "user_oauth"
        user_integration.integration_type = "sharepoint"
        user_integration.tenant_app_id = None
        return user_integration

    @pytest.fixture
    def user_integration_tenant_app(self):
        """Create a mock tenant_app integration."""
        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.id = uuid4()
        user_integration.auth_type = "tenant_app"
        user_integration.integration_type = "sharepoint"
        user_integration.tenant_app_id = uuid4()
        return user_integration

    @pytest.fixture
    def tenant_app_client_credentials(self):
        """Create a mock tenant app with client credentials."""
        tenant_app = MagicMock()
        tenant_app.id = uuid4()
        tenant_app.is_service_account.return_value = False
        return tenant_app

    @pytest.fixture
    def tenant_app_service_account(self):
        """Create a mock tenant app with service account auth."""
        tenant_app = MagicMock()
        tenant_app.id = uuid4()
        tenant_app.is_service_account.return_value = True
        tenant_app.service_account_refresh_token = "old-refresh-token"
        return tenant_app

    @pytest.fixture
    def oauth_token(self):
        """Create a mock oauth token."""
        token = MagicMock()
        token.id = uuid4()
        token.access_token = "user-oauth-token"
        token.token_type = MagicMock()
        token.token_type.is_confluence = False
        return token

    @pytest.fixture
    def created_knowledge(self, space_with_embedding_model, embedding_model):
        """Create a mock knowledge entity returned from repo.add."""
        knowledge = MagicMock(spec=IntegrationKnowledge)
        knowledge.id = uuid4()
        knowledge.name = "SharePoint Site"
        knowledge.original_name = "SharePoint Site"
        knowledge.space_id = space_with_embedding_model.id
        knowledge.sharepoint_subscription_id = None
        return knowledge

    @pytest.fixture
    def job(self):
        """Create a mock job."""
        job = MagicMock()
        job.id = uuid4()
        return job

    async def test_create_knowledge_user_oauth_uses_oauth_token(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_user_oauth,
        oauth_token,
        created_knowledge,
        job,
    ):
        """Test that user_oauth integration uses oauth_token_repo for token."""
        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model
        space_repo.session = _Savepoints()

        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration_user_oauth

        embedding_model_repo = AsyncMock()
        embedding_model_repo.one.return_value = embedding_model

        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token

        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.add.return_value = created_knowledge

        job_service = AsyncMock()
        job_service.queue_job.return_value = job

        sharepoint_subscription_service = AsyncMock()
        sharepoint_subscription_service.ensure_subscription_for_site.return_value = None

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,
            oauth_token_repo=oauth_token_repo,
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=embedding_model_repo,
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=MagicMock(),
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        result, result_job = await service.create_space_integration_knowledge(
            user_integration_id=user_integration_user_oauth.id,
            name="SharePoint Site",
            embedding_model_id=embedding_model.id,
            space_id=space_with_embedding_model.id,
            key="site-123",
            url="https://sharepoint.example.com",
        )

        # Verify oauth_token_repo was called
        oauth_token_repo.one.assert_called_once_with(
            user_integration_id=user_integration_user_oauth.id
        )
        # Verify job was queued with token_id
        job_service.queue_job.assert_called_once()
        call_kwargs = job_service.queue_job.call_args
        assert call_kwargs.kwargs["task_params"].token_id == oauth_token.id
        assert call_kwargs.kwargs["task_params"].tenant_app_id is None

    async def test_create_knowledge_tenant_app_uses_tenant_app_auth(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_tenant_app,
        tenant_app_client_credentials,
        created_knowledge,
        job,
    ):
        """Test that tenant_app integration uses tenant_app_auth_service."""
        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model
        space_repo.session = _Savepoints()

        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration_tenant_app

        embedding_model_repo = AsyncMock()
        embedding_model_repo.one.return_value = embedding_model

        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.add.return_value = created_knowledge

        job_service = AsyncMock()
        job_service.queue_job.return_value = job

        tenant_sharepoint_app_repo = AsyncMock()
        tenant_sharepoint_app_repo.one.return_value = tenant_app_client_credentials

        tenant_app_auth_service = AsyncMock()
        tenant_app_auth_service.get_access_token.return_value = "tenant-app-token"

        sharepoint_subscription_service = AsyncMock()
        sharepoint_subscription_service.ensure_subscription_for_site.return_value = None

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,  # TEST_USER has all permissions including ADMIN
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=embedding_model_repo,
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=MagicMock(),
                tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            ),
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=tenant_app_auth_service,
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=tenant_sharepoint_app_repo,
                tenant_app_auth_service=tenant_app_auth_service,
                service_account_auth_service=AsyncMock(),
            ),
        )

        result, result_job = await service.create_space_integration_knowledge(
            user_integration_id=user_integration_tenant_app.id,
            name="SharePoint Site",
            embedding_model_id=embedding_model.id,
            space_id=space_with_embedding_model.id,
            key="site-123",
            url="https://sharepoint.example.com",
        )

        # Verify tenant_app_auth_service was called
        tenant_app_auth_service.get_access_token.assert_called_once_with(
            tenant_app_client_credentials, force_refresh=False
        )
        # Verify job was queued with tenant_app_id
        job_service.queue_job.assert_called_once()
        call_kwargs = job_service.queue_job.call_args
        assert call_kwargs.kwargs["task_params"].token_id is None
        assert (
            call_kwargs.kwargs["task_params"].tenant_app_id
            == tenant_app_client_credentials.id
        )

    async def test_create_knowledge_service_account_uses_service_account_auth(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_tenant_app,
        tenant_app_service_account,
        created_knowledge,
        job,
    ):
        """Test that service account uses service_account_auth_service."""
        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model
        space_repo.session = _Savepoints()

        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration_tenant_app

        embedding_model_repo = AsyncMock()
        embedding_model_repo.one.return_value = embedding_model

        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.add.return_value = created_knowledge

        job_service = AsyncMock()
        job_service.queue_job.return_value = job

        tenant_sharepoint_app_repo = AsyncMock()
        tenant_sharepoint_app_repo.one.return_value = tenant_app_service_account

        service_account_auth_service = AsyncMock()
        service_account_auth_service.refresh_access_token.return_value = {
            "access_token": "service-account-token",
            "refresh_token": "new-refresh-token",
        }

        sharepoint_subscription_service = AsyncMock()
        sharepoint_subscription_service.ensure_subscription_for_site.return_value = None

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,  # TEST_USER has all permissions including ADMIN
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=embedding_model_repo,
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=MagicMock(),
                tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            ),
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=service_account_auth_service,
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=tenant_sharepoint_app_repo,
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=service_account_auth_service,
            ),
        )

        result, result_job = await service.create_space_integration_knowledge(
            user_integration_id=user_integration_tenant_app.id,
            name="SharePoint Site",
            embedding_model_id=embedding_model.id,
            space_id=space_with_embedding_model.id,
            key="site-123",
            url="https://sharepoint.example.com",
        )

        # Verify service_account_auth_service was called
        service_account_auth_service.refresh_access_token.assert_called_once_with(
            tenant_app_service_account, force_refresh=False
        )
        tenant_app_service_account.update_refresh_token.assert_called_once_with(
            "new-refresh-token"
        )
        tenant_sharepoint_app_repo.update.assert_called_once_with(
            tenant_app_service_account
        )

    async def test_create_knowledge_tenant_app_requires_admin_permission(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_tenant_app,
    ):
        """Test that tenant_app integration requires ADMIN permission."""
        # Create a user without ADMIN permission
        from eneo.users.user import UserInDB

        non_admin_user = MagicMock(spec=UserInDB)
        non_admin_user.id = uuid4()
        non_admin_user.tenant_id = TEST_USER.tenant_id
        non_admin_user.permissions = [Permission.COLLECTIONS]  # No ADMIN

        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model
        space_repo.session = _Savepoints()

        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration_tenant_app

        embedding_model_repo = AsyncMock()
        embedding_model_repo.one.return_value = embedding_model

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=non_admin_user,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=embedding_model_repo,
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=non_admin_user,
                actor_manager=MagicMock(),
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=MagicMock(),
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.create_space_integration_knowledge(
                user_integration_id=user_integration_tenant_app.id,
                name="SharePoint Site",
                embedding_model_id=embedding_model.id,
                space_id=space_with_embedding_model.id,
                key="site-123",
                url="https://sharepoint.example.com",
            )

        assert "Admin permission is required" in str(exc_info.value)

    async def test_create_knowledge_blocked_when_no_space_permission(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_tenant_app,
    ):
        """Test that a viewer (no create permission) is blocked at the SpaceActor level,
        before reaching the tenant_app admin check."""
        actor = MagicMock()
        actor.can_create_integrations.return_value = False

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model
        space_repo.session = _Savepoints()

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        with pytest.raises(UnauthorizedException):
            await service.create_space_integration_knowledge(
                user_integration_id=user_integration_tenant_app.id,
                name="SharePoint Site",
                embedding_model_id=embedding_model.id,
                space_id=space_with_embedding_model.id,
                key="site-123",
                url="https://sharepoint.example.com",
            )

        # The user_integration_repo should NOT have been called — blocked before reaching it
        service.user_integration_service.user_integration_repo.one.assert_not_called()

    async def test_create_knowledge_editor_without_admin_blocked_for_tenant_app(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_tenant_app,
    ):
        """Test that an editor with space-level create permission but without system
        ADMIN permission is blocked when trying to create tenant_app integrations.
        This is the key security check for shared spaces."""
        from eneo.users.user import UserInDB

        editor_user = MagicMock(spec=UserInDB)
        editor_user.id = uuid4()
        editor_user.tenant_id = TEST_USER.tenant_id
        editor_user.permissions = [
            Permission.INTEGRATIONS
        ]  # Has integrations but NOT ADMIN

        actor = MagicMock()
        actor.can_create_integrations.return_value = True  # Editor has space permission

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model
        space_repo.session = _Savepoints()

        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration_tenant_app

        embedding_model_repo = AsyncMock()
        embedding_model_repo.one.return_value = embedding_model

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=editor_user,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=embedding_model_repo,
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=editor_user,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.create_space_integration_knowledge(
                user_integration_id=user_integration_tenant_app.id,
                name="SharePoint Site",
                embedding_model_id=embedding_model.id,
                space_id=space_with_embedding_model.id,
                key="site-123",
                url="https://sharepoint.example.com",
            )

        assert "Admin permission is required" in str(exc_info.value)

    async def test_create_knowledge_sets_original_name(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_user_oauth,
        oauth_token,
        job,
    ):
        """Test that original_name is set to name at creation time."""
        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model
        space_repo.session = _Savepoints()

        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration_user_oauth

        embedding_model_repo = AsyncMock()
        embedding_model_repo.one.return_value = embedding_model

        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token

        # Capture the object passed to repo.add
        captured_knowledge = None

        async def capture_add(obj):
            nonlocal captured_knowledge
            captured_knowledge = obj
            # Return a mock with the same attributes
            result = MagicMock(spec=IntegrationKnowledge)
            result.id = uuid4()
            result.name = obj.name
            result.original_name = obj.original_name
            result.space_id = obj.space_id
            result.sharepoint_subscription_id = None
            return result

        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.add.side_effect = capture_add

        job_service = AsyncMock()
        job_service.queue_job.return_value = job

        sharepoint_subscription_service = AsyncMock()
        sharepoint_subscription_service.ensure_subscription_for_site.return_value = None

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,
            oauth_token_repo=oauth_token_repo,
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=embedding_model_repo,
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=MagicMock(),
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        await service.create_space_integration_knowledge(
            user_integration_id=user_integration_user_oauth.id,
            name="My SharePoint Site",
            embedding_model_id=embedding_model.id,
            space_id=space_with_embedding_model.id,
            key="site-123",
            url="https://sharepoint.example.com",
        )

        # Verify original_name was set to name
        assert captured_knowledge is not None
        assert captured_knowledge.name == "My SharePoint Site"
        assert captured_knowledge.original_name == "My SharePoint Site"

    async def test_create_knowledge_onedrive_sets_drive_id(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_user_oauth,
        oauth_token,
        job,
    ):
        """Test that OneDrive resource_type sets drive_id instead of site_id."""
        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model
        space_repo.session = _Savepoints()

        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration_user_oauth

        embedding_model_repo = AsyncMock()
        embedding_model_repo.one.return_value = embedding_model

        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token

        # Capture the object passed to repo.add
        captured_knowledge = None

        async def capture_add(obj):
            nonlocal captured_knowledge
            captured_knowledge = obj
            result = MagicMock(spec=IntegrationKnowledge)
            result.id = uuid4()
            result.name = obj.name
            result.space_id = obj.space_id
            result.sharepoint_subscription_id = None
            return result

        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.add.side_effect = capture_add

        job_service = AsyncMock()
        job_service.queue_job.return_value = job

        sharepoint_subscription_service = AsyncMock()
        sharepoint_subscription_service.ensure_subscription_for_site.return_value = None

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,
            oauth_token_repo=oauth_token_repo,
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=embedding_model_repo,
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=MagicMock(),
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        await service.create_space_integration_knowledge(
            user_integration_id=user_integration_user_oauth.id,
            name="My OneDrive",
            embedding_model_id=embedding_model.id,
            space_id=space_with_embedding_model.id,
            key="drive-abc-123",  # For OneDrive, key is the drive_id
            url="https://onedrive.example.com",
            resource_type="onedrive",
        )

        # Verify drive_id was set and site_id is None
        assert captured_knowledge is not None
        assert captured_knowledge.drive_id == "drive-abc-123"
        assert captured_knowledge.site_id is None
        assert captured_knowledge.resource_type == "onedrive"

    async def test_create_knowledge_sharepoint_sets_site_id(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_user_oauth,
        oauth_token,
        job,
    ):
        """Test that SharePoint resource_type sets site_id instead of drive_id."""
        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model
        space_repo.session = _Savepoints()

        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration_user_oauth

        embedding_model_repo = AsyncMock()
        embedding_model_repo.one.return_value = embedding_model

        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token

        # Capture the object passed to repo.add
        captured_knowledge = None

        async def capture_add(obj):
            nonlocal captured_knowledge
            captured_knowledge = obj
            result = MagicMock(spec=IntegrationKnowledge)
            result.id = uuid4()
            result.name = obj.name
            result.space_id = obj.space_id
            result.sharepoint_subscription_id = None
            return result

        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.add.side_effect = capture_add

        job_service = AsyncMock()
        job_service.queue_job.return_value = job

        sharepoint_subscription_service = AsyncMock()
        sharepoint_subscription_service.ensure_subscription_for_site.return_value = None

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,
            oauth_token_repo=oauth_token_repo,
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=embedding_model_repo,
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=MagicMock(),
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        await service.create_space_integration_knowledge(
            user_integration_id=user_integration_user_oauth.id,
            name="SharePoint Site",
            embedding_model_id=embedding_model.id,
            space_id=space_with_embedding_model.id,
            key="site-xyz-789",  # For SharePoint, key is the site_id
            url="https://sharepoint.example.com",
            resource_type="site",
        )

        # Verify site_id was set and drive_id is None
        assert captured_knowledge is not None
        assert captured_knowledge.site_id == "site-xyz-789"
        assert captured_knowledge.drive_id is None
        assert captured_knowledge.resource_type == "site"

    def _user_oauth_service(
        self,
        space,
        embedding_model,
        user_integration,
        oauth_token_repo,
        created_knowledge,
        job,
        subscription_service,
    ) -> IntegrationKnowledgeService:
        space_repo = AsyncMock()
        space_repo.one.return_value = space
        space_repo.session = _Savepoints()
        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration
        embedding_model_repo = AsyncMock()
        embedding_model_repo.one.return_value = embedding_model
        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.add.return_value = created_knowledge
        job_service = AsyncMock()
        job_service.queue_job.return_value = job
        return IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,
            oauth_token_repo=oauth_token_repo,
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=embedding_model_repo,
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=MagicMock(),
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=MagicMock(),
            sharepoint_subscription_service=subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            org_token_provider=AsyncMock(),
        )

    async def test_a_missing_token_is_refused_before_the_item_is_written(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_user_oauth,
        created_knowledge,
        job,
    ):
        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.side_effect = NotFoundException("OauthToken not found")
        service = self._user_oauth_service(
            space_with_embedding_model,
            embedding_model,
            user_integration_user_oauth,
            oauth_token_repo,
            created_knowledge,
            job,
            AsyncMock(),
        )

        with pytest.raises(NotFoundException):
            await service.create_space_integration_knowledge(
                user_integration_id=user_integration_user_oauth.id,
                name="SharePoint Site",
                embedding_model_id=embedding_model.id,
                space_id=space_with_embedding_model.id,
                key="site-123",
                url="https://sharepoint.example.com",
            )

        service.integration_knowledge_repo.add.assert_not_awaited()
        service.job_service.queue_job.assert_not_awaited()

    async def test_the_subscription_is_linked_by_its_column_only(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_user_oauth,
        oauth_token,
        created_knowledge,
        job,
    ):
        oauth_token.is_sharepoint = True
        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token
        subscription_service = AsyncMock()
        subscription = MagicMock(id=uuid4())
        subscription_service.ensure_subscription_for_site.return_value = subscription
        service = self._user_oauth_service(
            space_with_embedding_model,
            embedding_model,
            user_integration_user_oauth,
            oauth_token_repo,
            created_knowledge,
            job,
            subscription_service,
        )

        knowledge, _ = await service.create_space_integration_knowledge(
            user_integration_id=user_integration_user_oauth.id,
            name="SharePoint Site",
            embedding_model_id=embedding_model.id,
            space_id=space_with_embedding_model.id,
            key="site-123",
            url="https://sharepoint.example.com",
        )

        service.integration_knowledge_repo.link_subscription.assert_awaited_once_with(
            created_knowledge.id, subscription.id
        )
        service.integration_knowledge_repo.update.assert_not_called()
        assert knowledge.sharepoint_subscription_id == subscription.id
        assert service.space_repo.session.outcomes == ["released"]

    async def test_a_failed_subscription_link_is_rolled_back_and_the_import_kept(
        self,
        space_with_embedding_model,
        embedding_model,
        user_integration_user_oauth,
        oauth_token,
        created_knowledge,
        job,
    ):
        """A failed statement in the link would otherwise abort the transaction
        the item was written in."""
        oauth_token.is_sharepoint = True
        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token
        subscription_service = AsyncMock()
        subscription_service.ensure_subscription_for_site.return_value = MagicMock(
            id=uuid4()
        )
        service = self._user_oauth_service(
            space_with_embedding_model,
            embedding_model,
            user_integration_user_oauth,
            oauth_token_repo,
            created_knowledge,
            job,
            subscription_service,
        )
        service.integration_knowledge_repo.link_subscription.side_effect = (
            sa.exc.OperationalError("UPDATE", {}, Exception("lock timeout"))
        )

        knowledge, queued = await service.create_space_integration_knowledge(
            user_integration_id=user_integration_user_oauth.id,
            name="SharePoint Site",
            embedding_model_id=embedding_model.id,
            space_id=space_with_embedding_model.id,
            key="site-123",
            url="https://sharepoint.example.com",
        )

        assert (knowledge, queued) == (created_knowledge, job)
        assert service.space_repo.session.outcomes == ["rolled back"]


class _Savepoints:
    """A session whose savepoints record whether they were released or rolled
    back; the ones numbered in ``fail_release`` (in opening order) fail at
    RELEASE."""

    def __init__(self) -> None:
        self.outcomes: list[str] = []
        self.fail_release: set[int] = set()
        self._opened = 0

    def begin_nested(self):
        number = self._opened
        self._opened += 1

        @asynccontextmanager
        async def savepoint():
            try:
                yield
            except BaseException:
                self.outcomes.append("rolled back")
                raise
            if number in self.fail_release:
                self.outcomes.append("release failed")
                raise RuntimeError("Connection error")
            self.outcomes.append("released")

        return savepoint()


def _batch_item(name: str) -> dict[str, str | None]:
    return {
        "name": name,
        "key": "site-1",
        "url": f"https://contoso.sharepoint.com/sites/KS/{name}",
        "folder_id": f"folder-{name}",
        "folder_path": f"/{name}",
        "selected_item_type": "folder",
        "resource_type": "site",
    }


class TestCreateSpaceIntegrationKnowledgeBatch:
    """Every item of a batch is either created whole or leaves nothing behind."""

    @pytest.fixture
    def batch(self):
        space = MagicMock()
        space.id = uuid4()
        space.tenant_id = TEST_USER.tenant_id
        space.tenant_space_id = uuid4()
        space.is_embedding_model_in_space.return_value = True
        space.is_personal.return_value = True

        user_integration = MagicMock()
        user_integration.id = uuid4()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.auth_type = "user_oauth"
        user_integration.integration_type = "sharepoint"
        user_integration.tenant_app_id = None

        actor = MagicMock()
        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space_repo = AsyncMock()
        space_repo.one.return_value = space
        space_repo.session = _Savepoints()
        user_integration_repo = AsyncMock()
        user_integration_repo.one.return_value = user_integration
        oauth_token = MagicMock()
        oauth_token.id = uuid4()
        oauth_token.token_type.is_confluence = False
        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token

        def added(obj):
            knowledge = MagicMock(spec=IntegrationKnowledge)
            knowledge.id = uuid4()
            knowledge.name = obj.name
            knowledge.wrapper_id = obj.wrapper_id
            knowledge.wrapper_name = obj.wrapper_name
            return knowledge

        integration_knowledge_repo = AsyncMock()
        integration_knowledge_repo.add.side_effect = added
        job_service = AsyncMock()
        job_service.queue_job.side_effect = lambda **_: MagicMock(id=uuid4())
        subscription_service = AsyncMock()
        subscription_service.ensure_subscription_for_site.return_value = None
        tenant_sharepoint_app_repo = AsyncMock()

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,
            oauth_token_repo=oauth_token_repo,
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=user_integration_repo,
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=subscription_service,
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=AsyncMock(),
            org_token_provider=AsyncMock(),
        )
        return service

    async def _create(self, service, items, wrapper_name="Kommunstyrelsen"):
        return await service.create_space_integration_knowledge_batch(
            user_integration_id=uuid4(),
            embedding_model_id=uuid4(),
            space_id=uuid4(),
            wrapper_name=wrapper_name,
            items=[_batch_item(name) for name in items],
        )

    async def test_items_share_one_wrapper_and_one_preflight(self, batch):
        results = await self._create(batch, ["Protokoll", "Rutiner"])

        assert [result["status"] for result in results] == ["created", "created"]
        added = [
            call.kwargs["obj"]
            for call in batch.integration_knowledge_repo.add.await_args_list
        ]
        assert [obj.name for obj in added] == ["Protokoll", "Rutiner"]
        assert added[0].wrapper_id is not None
        assert added[1].wrapper_id == added[0].wrapper_id
        assert {obj.wrapper_name for obj in added} == {"Kommunstyrelsen"}
        assert [result["integration_knowledge_id"] for result in results] == [
            result["knowledge"].id for result in results
        ]
        # Access, embedding model and token are resolved once for the batch.
        batch.space_repo.one.assert_awaited_once()
        batch.oauth_token_repo.one.assert_awaited_once()

    async def test_a_single_item_gets_no_wrapper(self, batch):
        await self._create(batch, ["Protokoll"], wrapper_name="Single Wrapper")

        (obj,) = [
            call.kwargs["obj"]
            for call in batch.integration_knowledge_repo.add.await_args_list
        ]
        assert obj.wrapper_id is None
        assert obj.wrapper_name is None

    async def test_an_item_that_fails_after_its_write_is_rolled_back_alone(self, batch):
        batch.job_service.queue_job.side_effect = [
            MagicMock(id=uuid4()),
            RuntimeError("Connection error"),
            MagicMock(id=uuid4()),
        ]

        results = await self._create(batch, ["Protokoll", "Rutiner", "Budget"])

        assert [result["status"] for result in results] == [
            "created",
            "failed",
            "created",
        ]
        assert results[1]["integration_knowledge_id"] is None
        assert results[1]["job"] is None
        assert results[1]["error"] == "Connection error"
        # Item two was written before its job failed; only its savepoint is
        # rolled back, so its row and distribution go and the others stay.
        assert batch.integration_knowledge_repo.add.await_count == 3
        assert batch.space_repo.session.outcomes.count("rolled back") == 1

    async def test_a_job_is_dispatched_only_after_its_item_is_kept(self, batch):
        """Enqueueing inside the savepoint left the worker a job for an item
        whose RELEASE then failed."""

        async def record(task, job_id, params):
            batch.space_repo.session.outcomes.append("dispatch")

        batch.job_service.dispatch_after_commit = AsyncMock(side_effect=record)
        # Each item opens its own savepoint and then one for its subscription.
        batch.space_repo.session.fail_release = {2}

        results = await self._create(batch, ["Protokoll", "Rutiner", "Budget"])

        assert [result["status"] for result in results] == [
            "created",
            "failed",
            "created",
        ]
        assert batch.space_repo.session.outcomes == [
            "released",
            "released",
            "dispatch",
            "released",
            "release failed",
            "released",
            "released",
            "dispatch",
        ]
        assert {
            call.kwargs["enqueue"]
            for call in batch.job_service.queue_job.await_args_list
        } == {False}
        assert [
            call.args[1]
            for call in batch.job_service.dispatch_after_commit.await_args_list
        ] == [results[0]["job"].id, results[2]["job"].id]

    async def test_a_name_the_api_cannot_store_fails_only_its_item(self, batch):
        """One long SharePoint name made the whole batch a 422."""
        results = await self._create(
            batch, ["  Protokoll  ", "x" * 256, "   ", "Budget"]
        )

        assert [(result["status"], result["error"]) for result in results] == [
            ("created", None),
            ("failed", "The name must be 1 to 255 characters long"),
            ("failed", "The name must be 1 to 255 characters long"),
            ("created", None),
        ]
        assert [
            call.kwargs["obj"].name
            for call in batch.integration_knowledge_repo.add.await_args_list
        ] == ["Protokoll", "Budget"]

    async def test_a_database_failure_is_reported_without_sql(self, batch):
        batch.integration_knowledge_repo.add.side_effect = sa.exc.IntegrityError(
            "INSERT INTO integration_knowledge (name, url) VALUES (%(name)s, %(url)s)",
            {"name": "Lönelista", "url": "https://contoso.sharepoint.com/x"},
            Exception("duplicate key value violates unique constraint"),
        )

        results = await self._create(batch, ["Lönelista"])

        assert results[0]["status"] == "failed"
        assert results[0]["error"] == "Database error"
        assert batch.space_repo.session.outcomes == ["rolled back"]

    async def test_a_missing_personal_token_fails_the_request_before_any_write(
        self, batch
    ):
        """Every item reported the same failure with a 202 before."""
        batch.oauth_token_repo.one.side_effect = NotFoundException(
            "OauthToken not found"
        )

        with pytest.raises(NotFoundException):
            await self._create(batch, ["Protokoll", "Rutiner", "Budget"])

        batch.integration_knowledge_repo.add.assert_not_awaited()
        batch.job_service.queue_job.assert_not_awaited()
        assert batch.space_repo.session.outcomes == []

    async def test_refused_organization_credentials_fail_the_request_before_any_write(
        self, batch
    ):
        user_integration = (
            batch.user_integration_service.user_integration_repo.one.return_value
        )
        user_integration.auth_type = "tenant_app"
        user_integration.user_id = None
        user_integration.tenant_app_id = uuid4()
        batch.space_repo.one.return_value.is_personal.return_value = False
        batch.user_integration_service.tenant_sharepoint_app_repo.one.return_value = (
            MagicMock(id=uuid4(), is_active=True)
        )
        batch.org_token_provider.get_access_token.side_effect = (
            SharePointCredentialsInvalidError("invalid_client")
        )

        with pytest.raises(SharePointCredentialsInvalidError):
            await self._create(batch, ["Protokoll", "Rutiner", "Budget"])

        batch.integration_knowledge_repo.add.assert_not_awaited()
        batch.job_service.queue_job.assert_not_awaited()
        batch.oauth_token_repo.one.assert_not_awaited()


class TestTriggerFullSync:
    @pytest.fixture
    def sharepoint_knowledge_user_oauth(self, space):
        knowledge = MagicMock(spec=IntegrationKnowledge)
        knowledge.id = uuid4()
        knowledge.name = "SharePoint Site"
        knowledge.space_id = space.id
        knowledge.integration_type = "sharepoint"
        knowledge.site_id = "site-123"
        knowledge.drive_id = None
        knowledge.folder_id = None
        knowledge.folder_path = None
        knowledge.resource_type = None
        knowledge.sharepoint_subscription_id = None

        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.id = uuid4()
        user_integration.auth_type = "user_oauth"
        user_integration.tenant_app_id = None
        knowledge.user_integration = user_integration
        return knowledge

    @pytest.fixture
    def sharepoint_knowledge_tenant_app(self, space):
        knowledge = MagicMock(spec=IntegrationKnowledge)
        knowledge.id = uuid4()
        knowledge.name = "Org SharePoint Site"
        knowledge.space_id = space.id
        knowledge.integration_type = "sharepoint"
        knowledge.site_id = "site-456"
        knowledge.drive_id = None
        knowledge.folder_id = None
        knowledge.folder_path = None
        knowledge.resource_type = "site"
        knowledge.sharepoint_subscription_id = None

        user_integration = MagicMock()
        user_integration.user_id = TEST_USER.id
        user_integration.tenant_integration.tenant_id = TEST_USER.tenant_id
        user_integration.authenticated = True
        user_integration.id = uuid4()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        knowledge.user_integration = user_integration
        return knowledge

    async def test_trigger_full_sync_user_oauth_queues_job(
        self, actor, space, sharepoint_knowledge_user_oauth
    ):
        actor.can_edit_integrations.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_user_oauth

        space_repo = AsyncMock()
        space_repo.one.return_value = space
        space_repo.session = _Savepoints()

        oauth_token = MagicMock()
        oauth_token.id = uuid4()

        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token

        job_service = AsyncMock()
        queued_job = MagicMock()
        job_service.queue_job.return_value = queued_job
        sharepoint_subscription_service = AsyncMock()
        subscription = MagicMock()
        subscription.id = uuid4()
        sharepoint_subscription_service.ensure_subscription_for_site.return_value = (
            subscription
        )
        integration_knowledge_repo = AsyncMock()

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,
            oauth_token_repo=oauth_token_repo,
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        job, synced = await service.trigger_full_sync(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_user_oauth.id,
        )

        assert job == queued_job
        assert synced == (space, sharepoint_knowledge_user_oauth)
        oauth_token_repo.one.assert_called_once_with(
            user_integration_id=sharepoint_knowledge_user_oauth.user_integration.id
        )
        sharepoint_subscription_service.ensure_subscription_for_site.assert_called_once_with(
            user_integration_id=sharepoint_knowledge_user_oauth.user_integration.id,
            site_id=sharepoint_knowledge_user_oauth.site_id,
            token=oauth_token,
            is_onedrive=False,
        )
        # Only the subscription column: the sync this queues may already be
        # writing the row's sync state.
        integration_knowledge_repo.link_subscription.assert_awaited_once_with(
            sharepoint_knowledge_user_oauth.id, subscription.id
        )
        integration_knowledge_repo.update.assert_not_called()
        job_service.queue_job.assert_called_once()
        # A worker that picked the job up before the commit would not see it.
        assert job_service.queue_job.call_args.kwargs["after_commit"] is True
        assert space_repo.session.outcomes == ["released"]
        task_params = job_service.queue_job.call_args.kwargs["task_params"]
        assert task_params.token_id == oauth_token.id
        assert task_params.tenant_app_id is None
        assert (
            task_params.integration_knowledge_id == sharepoint_knowledge_user_oauth.id
        )
        assert task_params.resource_type == "site"

    async def test_trigger_full_sync_continues_if_subscription_ensure_fails(
        self, actor, space, sharepoint_knowledge_user_oauth
    ):
        actor.can_edit_integrations.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_user_oauth

        space_repo = AsyncMock()
        space_repo.one.return_value = space
        space_repo.session = _Savepoints()

        oauth_token = MagicMock()
        oauth_token.id = uuid4()

        oauth_token_repo = AsyncMock()
        oauth_token_repo.one.return_value = oauth_token

        job_service = AsyncMock()
        queued_job = MagicMock()
        job_service.queue_job.return_value = queued_job
        sharepoint_subscription_service = AsyncMock()
        sharepoint_subscription_service.ensure_subscription_for_site.side_effect = (
            RuntimeError("Graph failed")
        )

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=TEST_USER,
            oauth_token_repo=oauth_token_repo,
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        job, synced = await service.trigger_full_sync(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_user_oauth.id,
        )

        assert job == queued_job
        assert synced == (space, sharepoint_knowledge_user_oauth)
        sharepoint_subscription_service.ensure_subscription_for_site.assert_called_once()
        job_service.queue_job.assert_called_once()
        # The failure is rolled back to its savepoint before the job is queued.
        assert space_repo.session.outcomes == ["rolled back"]

    async def test_trigger_full_sync_tenant_app_requires_admin_permission(
        self, actor, space, sharepoint_knowledge_tenant_app
    ):
        actor.can_edit_integrations.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_tenant_app

        non_admin_user = MagicMock()
        non_admin_user.id = uuid4()
        non_admin_user.tenant_id = TEST_USER.tenant_id
        non_admin_user.permissions = [Permission.COLLECTIONS]

        space_repo = AsyncMock()
        space_repo.one.return_value = space
        space_repo.session = _Savepoints()

        job_service = AsyncMock()
        tenant_sharepoint_app_repo = AsyncMock()

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        service = IntegrationKnowledgeService(
            job_service=job_service,
            user=non_admin_user,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=non_admin_user,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=tenant_sharepoint_app_repo,
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.trigger_full_sync(
                space_id=space.id,
                integration_knowledge_id=sharepoint_knowledge_tenant_app.id,
            )

        assert "Admin permission is required" in str(exc_info.value)
        tenant_sharepoint_app_repo.one.assert_not_called()
        job_service.queue_job.assert_not_called()

    async def test_trigger_full_sync_rejects_non_sharepoint_knowledge(
        self, actor, space
    ):
        actor.can_edit_integrations.return_value = True

        knowledge = MagicMock(spec=IntegrationKnowledge)
        knowledge.id = uuid4()
        knowledge.name = "Confluence Knowledge"
        knowledge.space_id = space.id
        knowledge.integration_type = "confluence"
        knowledge.user_integration = MagicMock()
        space.get_integration_knowledge.return_value = knowledge

        space_repo = AsyncMock()
        space_repo.one.return_value = space
        space_repo.session = _Savepoints()

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=UserIntegrationService(
                user_integration_repo=AsyncMock(),
                tenant_integration_repo=AsyncMock(),
                user=TEST_USER,
                actor_manager=actor_manager,
                tenant_sharepoint_app_repo=AsyncMock(),
            ),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
            org_token_provider=OrgTokenProvider(
                tenant_app_repo=AsyncMock(),
                tenant_app_auth_service=AsyncMock(),
                service_account_auth_service=AsyncMock(),
            ),
        )

        with pytest.raises(BadRequestException):
            await service.trigger_full_sync(
                space_id=space.id,
                integration_knowledge_id=knowledge.id,
            )


class TestOrgTokenProviderWiring:
    def _service(self, **overrides):
        fields = dict(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=AsyncMock(),
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_service=AsyncMock(),
            actor_manager=MagicMock(),
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            org_token_provider=AsyncMock(),
        )
        fields.update(overrides)
        return IntegrationKnowledgeService(**fields)

    async def test_container_provided_token_provider_is_used(self):
        provider = AsyncMock()
        provider.get_access_token.return_value = "from-provider"
        tenant_app_auth_service = AsyncMock()
        service = self._service(
            tenant_app_auth_service=tenant_app_auth_service,
            org_token_provider=provider,
        )
        app = MagicMock()

        assert await service._get_tenant_app_access_token(app) == "from-provider"

        provider.get_access_token.assert_awaited_once_with(app)
        tenant_app_auth_service.get_access_token.assert_not_awaited()

    def test_container_wires_the_token_provider(self):
        assert "org_token_provider" in Container.integration_knowledge_service.kwargs
        assert "encryption_service" in Container.org_token_provider.kwargs
