"""
Unit tests for IntegrationKnowledgeService.

Tests cover:
- Creating integration knowledge with different auth types (user_oauth, tenant_app, service_account)
- Renaming integration knowledge items
- Permission enforcement for rename operations
- Authorization checks for cross-space operations
- Remove knowledge with different auth types (user_oauth, tenant_app, service_account)
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.integration.application.integration_knowledge_service import (
    IntegrationKnowledgeService,
)
from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.main.exceptions import BadRequestException, UnauthorizedException
from intric.roles.permissions import Permission
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
    knowledge = MagicMock(spec=IntegrationKnowledge)
    knowledge.id = uuid4()
    knowledge.name = "Original Name"
    knowledge.original_name = "Original Name"
    knowledge.space_id = space.id
    knowledge.tenant_id = space.tenant_id
    knowledge.created_at = datetime.now()
    knowledge.updated_at = datetime.now()
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
        user_integration_repo=AsyncMock(),
        actor_manager=actor_manager,
        sharepoint_subscription_service=AsyncMock(),
        tenant_sharepoint_app_repo=AsyncMock(),
        tenant_app_auth_service=AsyncMock(),
    )

    return service


class TestUpdateKnowledgeName:
    """Tests for the update_knowledge_name method."""

    async def test_rename_knowledge_success(
        self,
        service: IntegrationKnowledgeService,
        actor: MagicMock,
        integration_knowledge: MagicMock,
    ):
        """Test successful rename of integration knowledge."""
        actor.can_edit_integration_knowledge_list.return_value = True
        new_name = "New Knowledge Name"

        await service.update_knowledge_name(
            space_id=integration_knowledge.space_id,
            integration_knowledge_id=integration_knowledge.id,
            name=new_name,
        )

        # Verify the name was updated
        assert integration_knowledge.name == new_name
        # Verify repo.update was called
        service.integration_knowledge_repo.update.assert_called_once_with(
            integration_knowledge
        )

    async def test_rename_knowledge_unauthorized_without_edit_permission(
        self,
        service: IntegrationKnowledgeService,
        actor: MagicMock,
        integration_knowledge: MagicMock,
    ):
        """Test that users without edit permission cannot rename."""
        actor.can_edit_integration_knowledge_list.return_value = False

        with pytest.raises(UnauthorizedException):
            await service.update_knowledge_name(
                space_id=integration_knowledge.space_id,
                integration_knowledge_id=integration_knowledge.id,
                name="New Name",
            )

        # Verify update was not called
        service.integration_knowledge_repo.update.assert_not_called()

    async def test_rename_knowledge_unauthorized_from_different_space(
        self,
        service: IntegrationKnowledgeService,
        actor: MagicMock,
        space: MagicMock,
        integration_knowledge: MagicMock,
    ):
        """Test that knowledge cannot be renamed from a different space."""
        actor.can_edit_integration_knowledge_list.return_value = True
        # Knowledge belongs to a different space
        integration_knowledge.space_id = uuid4()

        with pytest.raises(UnauthorizedException) as exc_info:
            await service.update_knowledge_name(
                space_id=space.id,
                integration_knowledge_id=integration_knowledge.id,
                name="New Name",
            )

        assert "Cannot rename knowledge from this space" in str(exc_info.value)
        # Verify update was not called
        service.integration_knowledge_repo.update.assert_not_called()

    async def test_rename_preserves_original_name(
        self,
        service: IntegrationKnowledgeService,
        actor: MagicMock,
        integration_knowledge: MagicMock,
    ):
        """Test that renaming does not change the original_name field."""
        actor.can_edit_integration_knowledge_list.return_value = True
        original = integration_knowledge.original_name
        new_name = "New Knowledge Name"

        await service.update_knowledge_name(
            space_id=integration_knowledge.space_id,
            integration_knowledge_id=integration_knowledge.id,
            name=new_name,
        )

        # original_name should remain unchanged
        assert integration_knowledge.original_name == original
        # name should be updated
        assert integration_knowledge.name == new_name

    async def test_rename_fetches_knowledge_from_repo(
        self,
        service: IntegrationKnowledgeService,
        actor: MagicMock,
        integration_knowledge: MagicMock,
    ):
        """Test that knowledge is fetched from repo for update (to get created_at)."""
        actor.can_edit_integration_knowledge_list.return_value = True

        await service.update_knowledge_name(
            space_id=integration_knowledge.space_id,
            integration_knowledge_id=integration_knowledge.id,
            name="New Name",
        )

        # Verify knowledge was fetched from repo
        service.integration_knowledge_repo.one.assert_called_once_with(
            id=integration_knowledge.id
        )


class TestRemoveKnowledge:
    """Tests for the remove_knowledge method with different auth types."""

    @pytest.fixture
    def user_integration_user_oauth(self):
        """Create a mock user_oauth integration."""
        user_integration = MagicMock()
        user_integration.id = uuid4()
        user_integration.auth_type = "user_oauth"
        user_integration.tenant_app_id = None
        return user_integration

    @pytest.fixture
    def user_integration_tenant_app(self):
        """Create a mock tenant_app integration (app oauth)."""
        user_integration = MagicMock()
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

    async def test_remove_knowledge_user_oauth_uses_oauth_token(
        self, actor, space, sharepoint_knowledge_user_oauth
    ):
        """Test that user_oauth integration uses oauth_token_repo for token."""
        actor.can_delete_integration_knowledge_list.return_value = True
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
            user_integration_repo=AsyncMock(),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
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
        actor.can_delete_integration_knowledge_list.return_value = True
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
            user_integration_repo=AsyncMock(),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=tenant_app_auth_service,
            service_account_auth_service=AsyncMock(),
        )

        await service.remove_knowledge(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_tenant_app.id,
        )

        # Verify tenant_app_auth_service was called (not service_account)
        tenant_app_auth_service.get_access_token.assert_called_once_with(
            tenant_app_client_credentials
        )

    async def test_remove_knowledge_service_account_uses_service_account_auth(
        self, actor, space, sharepoint_knowledge_tenant_app, tenant_app_service_account
    ):
        """Test that service account integration uses service_account_auth_service for token."""
        actor.can_delete_integration_knowledge_list.return_value = True
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
            user_integration_repo=AsyncMock(),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=service_account_auth_service,
        )

        await service.remove_knowledge(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_tenant_app.id,
        )

        # Verify service_account_auth_service was called
        service_account_auth_service.refresh_access_token.assert_called_once_with(
            tenant_app_service_account
        )
        tenant_app_service_account.update_refresh_token.assert_called_once_with(
            "new-refresh-token"
        )
        tenant_sharepoint_app_repo.update.assert_called_once_with(
            tenant_app_service_account
        )

    async def test_remove_knowledge_service_account_without_auth_service_logs_warning(
        self, actor, space, sharepoint_knowledge_tenant_app, tenant_app_service_account
    ):
        """Test that service account without auth service logs warning but completes.

        The subscription cleanup failure is caught and logged, but does not
        prevent the knowledge from being deleted.
        """
        actor.can_delete_integration_knowledge_list.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_tenant_app
        space.tenant_space_id = uuid4()  # Not an org space

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        space_repo = AsyncMock()
        space_repo.one.return_value = space

        tenant_sharepoint_app_repo = AsyncMock()
        tenant_sharepoint_app_repo.one.return_value = tenant_app_service_account

        integration_knowledge_repo = AsyncMock()

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=integration_knowledge_repo,
            embedding_model_repo=AsyncMock(),
            user_integration_repo=AsyncMock(),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=None,  # No service account auth configured
        )

        # Should complete without raising (error is caught and logged)
        await service.remove_knowledge(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_tenant_app.id,
        )

        # Verify the knowledge was still removed despite subscription cleanup failure
        integration_knowledge_repo.remove.assert_called_once_with(
            id=sharepoint_knowledge_tenant_app.id
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
        return space

    @pytest.fixture
    def user_integration_user_oauth(self):
        """Create a mock user_oauth integration."""
        user_integration = MagicMock()
        user_integration.id = uuid4()
        user_integration.auth_type = "user_oauth"
        user_integration.integration_type = "sharepoint"
        user_integration.tenant_app_id = None
        return user_integration

    @pytest.fixture
    def user_integration_tenant_app(self):
        """Create a mock tenant_app integration."""
        user_integration = MagicMock()
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
            user_integration_repo=user_integration_repo,
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
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
            user_integration_repo=user_integration_repo,
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=tenant_app_auth_service,
            service_account_auth_service=AsyncMock(),
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
            tenant_app_client_credentials
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
            user_integration_repo=user_integration_repo,
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=service_account_auth_service,
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
            tenant_app_service_account
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
        from intric.users.user import UserInDB

        non_admin_user = MagicMock(spec=UserInDB)
        non_admin_user.id = uuid4()
        non_admin_user.tenant_id = TEST_USER.tenant_id
        non_admin_user.permissions = [Permission.COLLECTIONS]  # No ADMIN

        space_repo = AsyncMock()
        space_repo.one.return_value = space_with_embedding_model

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
            user_integration_repo=user_integration_repo,
            actor_manager=MagicMock(),
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
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
            user_integration_repo=user_integration_repo,
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
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
            user_integration_repo=user_integration_repo,
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
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
            user_integration_repo=user_integration_repo,
            actor_manager=MagicMock(),
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
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
        user_integration.id = uuid4()
        user_integration.auth_type = "tenant_app"
        user_integration.tenant_app_id = uuid4()
        knowledge.user_integration = user_integration
        return knowledge

    async def test_trigger_full_sync_user_oauth_queues_job(
        self, actor, space, sharepoint_knowledge_user_oauth
    ):
        actor.can_edit_integration_knowledge_list.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_user_oauth

        space_repo = AsyncMock()
        space_repo.one.return_value = space

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
            user_integration_repo=AsyncMock(),
            actor_manager=actor_manager,
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
        )

        result = await service.trigger_full_sync(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_user_oauth.id,
        )

        assert result == queued_job
        oauth_token_repo.one.assert_called_once_with(
            user_integration_id=sharepoint_knowledge_user_oauth.user_integration.id
        )
        sharepoint_subscription_service.ensure_subscription_for_site.assert_called_once_with(
            user_integration_id=sharepoint_knowledge_user_oauth.user_integration.id,
            site_id=sharepoint_knowledge_user_oauth.site_id,
            token=oauth_token,
            is_onedrive=False,
        )
        integration_knowledge_repo.update.assert_called_once()
        job_service.queue_job.assert_called_once()
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
        actor.can_edit_integration_knowledge_list.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_user_oauth

        space_repo = AsyncMock()
        space_repo.one.return_value = space

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
            user_integration_repo=AsyncMock(),
            actor_manager=actor_manager,
            sharepoint_subscription_service=sharepoint_subscription_service,
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
        )

        result = await service.trigger_full_sync(
            space_id=space.id,
            integration_knowledge_id=sharepoint_knowledge_user_oauth.id,
        )

        assert result == queued_job
        sharepoint_subscription_service.ensure_subscription_for_site.assert_called_once()
        job_service.queue_job.assert_called_once()

    async def test_trigger_full_sync_tenant_app_requires_admin_permission(
        self, actor, space, sharepoint_knowledge_tenant_app
    ):
        actor.can_edit_integration_knowledge_list.return_value = True
        space.get_integration_knowledge.return_value = sharepoint_knowledge_tenant_app

        non_admin_user = MagicMock()
        non_admin_user.id = uuid4()
        non_admin_user.tenant_id = TEST_USER.tenant_id
        non_admin_user.permissions = [Permission.COLLECTIONS]

        space_repo = AsyncMock()
        space_repo.one.return_value = space

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
            user_integration_repo=AsyncMock(),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=tenant_sharepoint_app_repo,
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
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
        actor.can_edit_integration_knowledge_list.return_value = True

        knowledge = MagicMock(spec=IntegrationKnowledge)
        knowledge.id = uuid4()
        knowledge.name = "Confluence Knowledge"
        knowledge.space_id = space.id
        knowledge.integration_type = "confluence"
        knowledge.user_integration = MagicMock()
        space.get_integration_knowledge.return_value = knowledge

        space_repo = AsyncMock()
        space_repo.one.return_value = space

        actor_manager = MagicMock()
        actor_manager.get_space_actor_from_space.return_value = actor

        service = IntegrationKnowledgeService(
            job_service=AsyncMock(),
            user=TEST_USER,
            oauth_token_repo=AsyncMock(),
            space_repo=space_repo,
            integration_knowledge_repo=AsyncMock(),
            embedding_model_repo=AsyncMock(),
            user_integration_repo=AsyncMock(),
            actor_manager=actor_manager,
            sharepoint_subscription_service=AsyncMock(),
            tenant_sharepoint_app_repo=AsyncMock(),
            tenant_app_auth_service=AsyncMock(),
            service_account_auth_service=AsyncMock(),
        )

        with pytest.raises(BadRequestException):
            await service.trigger_full_sync(
                space_id=space.id,
                integration_knowledge_id=knowledge.id,
            )
