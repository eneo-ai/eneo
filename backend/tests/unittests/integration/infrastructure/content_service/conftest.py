"""Mocks the SharePoint content service and its collaborators are built on."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.integration.infrastructure.content_service.sharepoint_content_service import (
    SharePointContentService,
)
from eneo.integration.infrastructure.content_service.sharepoint_index import (
    SharePointIndex,
)
from eneo.integration.infrastructure.content_service.sharepoint_reconciliation import (
    SharePointReconciliation,
)
from tests.unittests.integration.infrastructure.content_service.helpers import (
    org_token_provider,
)


@pytest.fixture
def mock_user():
    """Create a mock user."""
    user = MagicMock()
    user.id = uuid4()
    user.tenant_id = uuid4()
    return user


@pytest.fixture
def mock_integration_knowledge():
    """Create a mock integration knowledge object."""
    ik = MagicMock()
    ik.id = uuid4()
    ik.site_id = "site-123"
    ik.drive_id = "drive-456"
    ik.folder_id = None
    ik.folder_path = None
    ik.resource_type = "site"
    ik.delta_token = None
    ik.size = 0
    ik.last_sync_summary = None
    ik.last_synced_at = None
    ik.selected_item_type = None
    ik.embedding_model = MagicMock()
    return ik


@pytest.fixture
def mock_oauth_token():
    """Create a mock OAuth token."""
    token = MagicMock()
    token.id = uuid4()
    token.access_token = "personal-oauth-access-token"
    token.refresh_token = "personal-oauth-refresh-token"
    token.base_url = "https://graph.microsoft.com"
    return token


@pytest.fixture
def mock_tenant_app():
    """Create a mock tenant SharePoint app."""
    app = MagicMock()
    app.id = uuid4()
    app.tenant_id = uuid4()
    app.client_id = "tenant-app-client-id"
    app.client_secret = "tenant-app-client-secret"
    app.tenant_domain = "contoso.onmicrosoft.com"
    app.is_service_account.return_value = False
    app.is_active = True
    return app


@pytest.fixture
def mock_dependencies(mock_user, mock_integration_knowledge):
    """Create all mock dependencies for SharePointContentService."""
    integration_knowledge_repo = AsyncMock()

    async def adjust_size(id, delta):
        return max(0, mock_integration_knowledge.size + delta)

    integration_knowledge_repo.adjust_size = AsyncMock(side_effect=adjust_size)
    return {
        "oauth_token_repo": AsyncMock(),
        "user": mock_user,
        "info_blob_service": AsyncMock(),
        "integration_knowledge_repo": integration_knowledge_repo,
        "oauth_token_service": AsyncMock(),
        "session": AsyncMock(),
        "tenant_sharepoint_app_repo": AsyncMock(),
        "org_token_provider": org_token_provider(),
        "sync_log_repo": AsyncMock(),
        "change_key_service": AsyncMock(),
    }


@pytest.fixture
def service(mock_dependencies):
    """Create SharePointContentService with mocked dependencies."""
    return SharePointContentService(**mock_dependencies)


@pytest.fixture
def index(mock_dependencies):
    """The index the service writes through, built on the same mocks."""
    return SharePointIndex(
        mock_dependencies["info_blob_service"],
        mock_dependencies["integration_knowledge_repo"],
        mock_dependencies["user"],
        mock_dependencies["change_key_service"],
    )


@pytest.fixture
def reconciliation(index):
    return SharePointReconciliation(index)
