"""Unit tests for SharePointAuthRouter - core authentication routing logic.

Tests the authentication routing logic that determines whether to use user OAuth
(delegated permissions) or tenant app (application permissions) based on space type.
"""

from dataclasses import dataclass
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from intric.integration.application.sharepoint_auth_router import SharePointAuthRouter
from intric.integration.domain.entities.oauth_token import SharePointToken


@dataclass
class Setup:
    """Test setup fixture data."""

    router: SharePointAuthRouter
    user_oauth_service: AsyncMock
    tenant_app_service: AsyncMock
    tenant_app_auth_service: AsyncMock
    oauth_token_service: AsyncMock


@pytest.fixture
def setup():
    """Create SharePointAuthRouter with all dependencies mocked."""
    user_oauth_service = AsyncMock()
    tenant_app_service = AsyncMock()
    tenant_app_auth_service = AsyncMock()
    oauth_token_service = AsyncMock()

    router = SharePointAuthRouter(
        user_oauth_service=user_oauth_service,
        tenant_app_service=tenant_app_service,
        tenant_app_auth_service=tenant_app_auth_service,
        oauth_token_service=oauth_token_service,
    )

    return Setup(
        router=router,
        user_oauth_service=user_oauth_service,
        tenant_app_service=tenant_app_service,
        tenant_app_auth_service=tenant_app_auth_service,
        oauth_token_service=oauth_token_service,
    )


@pytest.fixture
def mock_user_integration():
    """Create a mock user integration."""
    integration = MagicMock()
    integration.id = uuid4()
    integration.user_id = uuid4()
    integration.tenant_app_id = None
    integration.auth_type = "user_oauth"

    # Mock tenant_integration for tenant_id access
    tenant_integration = MagicMock()
    tenant_integration.tenant_id = uuid4()
    integration.tenant_integration = tenant_integration

    return integration


@pytest.fixture
def mock_tenant_app_integration():
    """Create a mock tenant app integration (person-independent)."""
    integration = MagicMock()
    integration.id = uuid4()
    integration.user_id = None  # Person-independent
    integration.tenant_app_id = uuid4()
    integration.auth_type = "tenant_app"

    # Mock tenant_integration
    tenant_integration = MagicMock()
    tenant_integration.tenant_id = uuid4()
    tenant_integration.integration.integration_type = "sharepoint"
    integration.tenant_integration = tenant_integration

    # Mock tenant_app relationship
    tenant_app = MagicMock()
    tenant_app.id = integration.tenant_app_id
    tenant_app.client_id = "azure-client-id"
    tenant_app.tenant_id = tenant_integration.tenant_id
    tenant_app.auth_method = "tenant_app"
    tenant_app.is_service_account.return_value = False  # Not a service account
    integration.tenant_app = tenant_app

    return integration


@pytest.fixture
def mock_personal_space():
    """Create a mock personal space."""
    space = MagicMock()
    space.id = uuid4()
    space.user_id = uuid4()  # Personal space has user_id
    space.tenant_space_id = None
    space.is_personal = MagicMock(return_value=True)
    space.is_organization = MagicMock(return_value=False)
    return space


@pytest.fixture
def mock_shared_space():
    """Create a mock shared space (tenant space)."""
    space = MagicMock()
    space.id = uuid4()
    space.user_id = None  # Shared space has no user_id
    space.tenant_space_id = uuid4()  # Has tenant_space_id
    space.is_personal = MagicMock(return_value=False)
    space.is_organization = MagicMock(return_value=False)
    return space


@pytest.fixture
def mock_organization_space():
    """Create a mock organization space."""
    space = MagicMock()
    space.id = uuid4()
    space.user_id = None  # Org space has no user_id
    space.tenant_space_id = None  # Org space has no tenant_space_id
    space.is_personal = MagicMock(return_value=False)
    space.is_organization = MagicMock(return_value=True)
    return space


@pytest.fixture
def mock_oauth_token():
    """Create a mock OAuth token from database."""
    token = MagicMock()
    token.id = uuid4()
    token.access_token = "user-access-token-123"
    token.refresh_token = "user-refresh-token-456"
    token.token_type = "Bearer"
    token.resources = {"resource1": "value1"}
    token.created_at = datetime.utcnow()
    token.updated_at = datetime.utcnow()
    return token


@pytest.fixture
def mock_tenant_app():
    """Create a mock tenant app."""
    app = MagicMock()
    app.id = uuid4()
    app.tenant_id = uuid4()
    app.client_id = "azure-client-id-123"
    app.client_secret = "azure-client-secret-456"
    app.tenant_domain = "contoso.onmicrosoft.com"
    app.is_active = True
    app.auth_method = "tenant_app"
    app.is_service_account.return_value = False  # Not a service account
    return app

async def test_personal_space_always_uses_user_oauth(
    setup: Setup,
    mock_user_integration,
    mock_personal_space,
    mock_oauth_token,
):
    """Personal spaces always route to user OAuth, regardless of tenant app config."""
    # Configure mocks
    setup.oauth_token_service.get_oauth_token_by_user_integration.return_value = mock_oauth_token

    # Execute
    token = await setup.router.get_token_for_integration(
        mock_user_integration, mock_personal_space
    )

    # Assert
    assert token.access_token == "user-access-token-123"
    assert token.refresh_token == "user-refresh-token-456"
    assert token.user_integration == mock_user_integration

    # Verify user OAuth service was used
    setup.oauth_token_service.get_oauth_token_by_user_integration.assert_called_once_with(
        mock_user_integration.id
    )

    # Verify tenant app service was NOT called for personal space
    setup.tenant_app_service.get_active_app_for_tenant.assert_not_called()


async def test_shared_space_with_tenant_app_uses_tenant_app(
    setup: Setup,
    mock_user_integration,
    mock_shared_space,
    mock_tenant_app,
):
    """Shared spaces with configured tenant app use tenant app auth."""
    # Configure mocks
    setup.tenant_app_service.get_active_app_for_tenant.return_value = mock_tenant_app
    setup.tenant_app_auth_service.get_access_token.return_value = "tenant-app-access-token"

    # Execute
    token = await setup.router.get_token_for_integration(
        mock_user_integration, mock_shared_space
    )

    # Assert
    assert token.access_token == "tenant-app-access-token"
    assert token.user_integration == mock_user_integration
    assert token.refresh_token == ""  # Tenant app tokens don't have refresh tokens

    # Verify tenant app service was called
    setup.tenant_app_service.get_active_app_for_tenant.assert_called_once_with(
        mock_user_integration.tenant_integration.tenant_id
    )
    setup.tenant_app_auth_service.get_access_token.assert_called_once_with(
        mock_tenant_app
    )

    # Verify user OAuth service was NOT called
    setup.oauth_token_service.get_oauth_token_by_user_integration.assert_not_called()


async def test_shared_space_without_tenant_app_falls_back_to_user_oauth(
    setup: Setup,
    mock_user_integration,
    mock_shared_space,
    mock_oauth_token,
):
    """Shared spaces without tenant app fall back to user OAuth with warning."""
    # Configure mocks - no tenant app configured
    setup.tenant_app_service.get_active_app_for_tenant.return_value = None
    setup.oauth_token_service.get_oauth_token_by_user_integration.return_value = mock_oauth_token

    # Execute
    token = await setup.router.get_token_for_integration(
        mock_user_integration, mock_shared_space
    )

    # Assert
    assert token.access_token == "user-access-token-123"
    assert token.user_integration == mock_user_integration

    # Verify fallback path was taken
    setup.tenant_app_service.get_active_app_for_tenant.assert_called_once()
    setup.oauth_token_service.get_oauth_token_by_user_integration.assert_called_once_with(
        mock_user_integration.id
    )


async def test_organization_space_with_tenant_app_uses_tenant_app(
    setup: Setup,
    mock_user_integration,
    mock_organization_space,
    mock_tenant_app,
):
    """Organization spaces with configured tenant app use tenant app auth."""
    # Configure mocks
    setup.tenant_app_service.get_active_app_for_tenant.return_value = mock_tenant_app
    setup.tenant_app_auth_service.get_access_token.return_value = "tenant-app-access-token"

    # Execute
    token = await setup.router.get_token_for_integration(
        mock_user_integration, mock_organization_space
    )

    # Assert
    assert token.access_token == "tenant-app-access-token"
    assert token.user_integration == mock_user_integration

    # Verify tenant app auth was used
    setup.tenant_app_service.get_active_app_for_tenant.assert_called_once()
    setup.tenant_app_auth_service.get_access_token.assert_called_once_with(
        mock_tenant_app
    )


async def test_organization_space_without_tenant_app_falls_back_to_user_oauth(
    setup: Setup,
    mock_user_integration,
    mock_organization_space,
    mock_oauth_token,
):
    """Organization spaces without tenant app fall back to user OAuth."""
    # Configure mocks - no tenant app configured
    setup.tenant_app_service.get_active_app_for_tenant.return_value = None
    setup.oauth_token_service.get_oauth_token_by_user_integration.return_value = mock_oauth_token

    # Execute
    token = await setup.router.get_token_for_integration(
        mock_user_integration, mock_organization_space
    )

    # Assert
    assert token.access_token == "user-access-token-123"

    # Verify fallback was used
    setup.tenant_app_service.get_active_app_for_tenant.assert_called_once()
    setup.oauth_token_service.get_oauth_token_by_user_integration.assert_called_once()


async def test_missing_oauth_token_raises_error(
    setup: Setup,
    mock_user_integration,
    mock_personal_space,
):
    """Missing OAuth token raises meaningful error."""
    # Configure mocks - no token found
    setup.oauth_token_service.get_oauth_token_by_user_integration.return_value = None

    # Execute and assert
    with pytest.raises(ValueError, match="No OAuth token found"):
        await setup.router.get_token_for_integration(
            mock_user_integration, mock_personal_space
        )


async def test_oauth_token_fetch_exception_raises_error(
    setup: Setup,
    mock_user_integration,
    mock_personal_space,
):
    """Exception during OAuth token fetch raises meaningful error."""
    # Configure mocks - raise exception
    setup.oauth_token_service.get_oauth_token_by_user_integration.side_effect = (
        Exception("Database error")
    )

    # Execute and assert
    with pytest.raises(ValueError, match="Failed to retrieve OAuth token"):
        await setup.router.get_token_for_integration(
            mock_user_integration, mock_personal_space
        )


async def test_tenant_app_token_acquisition_failure_raises_error(
    setup: Setup,
    mock_user_integration,
    mock_shared_space,
    mock_tenant_app,
):
    """Tenant app token acquisition failure raises meaningful error."""
    # Configure mocks
    setup.tenant_app_service.get_active_app_for_tenant.return_value = mock_tenant_app
    setup.tenant_app_auth_service.get_access_token.side_effect = Exception(
        "Token acquisition failed"
    )

    # Execute and assert
    with pytest.raises(ValueError, match="Failed to acquire access token"):
        await setup.router.get_token_for_integration(
            mock_user_integration, mock_shared_space
        )


async def test_should_use_tenant_app_returns_false_for_personal_space(
    setup: Setup,
    mock_personal_space,
):
    """should_use_tenant_app returns False for personal spaces."""
    tenant_id = uuid4()

    result = await setup.router.should_use_tenant_app(tenant_id, mock_personal_space)

    assert result is False
    # Should not even check for tenant app for personal spaces
    setup.tenant_app_service.get_active_app_for_tenant.assert_not_called()


async def test_should_use_tenant_app_returns_true_when_tenant_app_configured(
    setup: Setup,
    mock_shared_space,
    mock_tenant_app,
):
    """should_use_tenant_app returns True when tenant app configured."""
    tenant_id = uuid4()
    setup.tenant_app_service.get_active_app_for_tenant.return_value = mock_tenant_app

    result = await setup.router.should_use_tenant_app(tenant_id, mock_shared_space)

    assert result is True
    setup.tenant_app_service.get_active_app_for_tenant.assert_called_once_with(
        tenant_id
    )


async def test_should_use_tenant_app_returns_false_when_no_tenant_app(
    setup: Setup,
    mock_shared_space,
):
    """should_use_tenant_app returns False when no tenant app configured."""
    tenant_id = uuid4()
    setup.tenant_app_service.get_active_app_for_tenant.return_value = None

    result = await setup.router.should_use_tenant_app(tenant_id, mock_shared_space)

    assert result is False


async def test_get_token_by_auth_type_user_oauth(
    setup: Setup,
    mock_user_integration,
    mock_oauth_token,
):
    """get_token_by_auth_type with user_oauth uses user OAuth flow."""
    setup.oauth_token_service.get_oauth_token_by_user_integration.return_value = mock_oauth_token

    token = await setup.router.get_token_by_auth_type(
        mock_user_integration, "user_oauth"
    )

    assert token.access_token == "user-access-token-123"
    setup.oauth_token_service.get_oauth_token_by_user_integration.assert_called_once()


async def test_get_token_by_auth_type_tenant_app(
    setup: Setup,
    mock_tenant_app_integration,
):
    """get_token_by_auth_type with tenant_app uses tenant app flow."""
    setup.tenant_app_auth_service.get_access_token.return_value = "tenant-app-token"

    token = await setup.router.get_token_by_auth_type(
        mock_tenant_app_integration, "tenant_app"
    )

    assert token.access_token == "tenant-app-token"
    setup.tenant_app_auth_service.get_access_token.assert_called_once()


async def test_get_token_by_auth_type_tenant_app_missing_tenant_app_id_raises_error(
    setup: Setup,
    mock_user_integration,
):
    """get_token_by_auth_type with tenant_app but no tenant_app_id raises error."""
    mock_user_integration.tenant_app_id = None

    with pytest.raises(ValueError, match="has no tenant_app_id"):
        await setup.router.get_token_by_auth_type(
            mock_user_integration, "tenant_app"
        )


async def test_get_token_by_auth_type_invalid_auth_type_raises_error(
    setup: Setup,
    mock_user_integration,
):
    """get_token_by_auth_type with invalid auth_type raises error."""
    with pytest.raises(ValueError, match="Invalid auth_type"):
        await setup.router.get_token_by_auth_type(
            mock_user_integration, "invalid_type"
        )


@pytest.mark.parametrize(
    "space_type,tenant_app_configured,expected_auth",
    [
        ("personal", True, "user_oauth"),  # Personal always user OAuth
        ("personal", False, "user_oauth"),  # Personal always user OAuth
        ("shared", True, "tenant_app"),  # Shared with tenant app uses it
        ("shared", False, "user_oauth"),  # Shared without tenant app falls back
        ("organization", True, "tenant_app"),  # Org with tenant app uses it
        ("organization", False, "user_oauth"),  # Org without tenant app falls back
    ],
)
async def test_authentication_routing_matrix(
    setup: Setup,
    mock_user_integration,
    mock_oauth_token,
    mock_tenant_app,
    space_type,
    tenant_app_configured,
    expected_auth,
):
    """Test all combinations of space type × tenant app configuration."""
    # Create appropriate space mock
    if space_type == "personal":
        space = MagicMock()
        space.is_personal = MagicMock(return_value=True)
        space.is_organization = MagicMock(return_value=False)
    elif space_type == "shared":
        space = MagicMock()
        space.is_personal = MagicMock(return_value=False)
        space.is_organization = MagicMock(return_value=False)
    else:  # organization
        space = MagicMock()
        space.is_personal = MagicMock(return_value=False)
        space.is_organization = MagicMock(return_value=True)

    # Configure tenant app availability
    if tenant_app_configured:
        setup.tenant_app_service.get_active_app_for_tenant.return_value = mock_tenant_app
        setup.tenant_app_auth_service.get_access_token.return_value = "tenant-app-token"
    else:
        setup.tenant_app_service.get_active_app_for_tenant.return_value = None

    # Configure user OAuth
    setup.oauth_token_service.get_oauth_token_by_user_integration.return_value = mock_oauth_token

    # Execute
    token = await setup.router.get_token_for_integration(
        mock_user_integration, space
    )

    # Assert correct authentication method was used
    if expected_auth == "user_oauth":
        assert token.access_token == "user-access-token-123"
        setup.oauth_token_service.get_oauth_token_by_user_integration.assert_called_once()
    else:  # tenant_app
        assert token.access_token == "tenant-app-token"
        setup.tenant_app_auth_service.get_access_token.assert_called_once()


async def test_sharepoint_token_from_user_oauth_has_correct_structure(
    setup: Setup,
    mock_user_integration,
    mock_personal_space,
    mock_oauth_token,
):
    """SharePointToken from user OAuth has all expected fields."""
    setup.oauth_token_service.get_oauth_token_by_user_integration.return_value = mock_oauth_token

    token = await setup.router.get_token_for_integration(
        mock_user_integration, mock_personal_space
    )

    assert isinstance(token, SharePointToken)
    assert token.access_token == mock_oauth_token.access_token
    assert token.refresh_token == mock_oauth_token.refresh_token
    assert token.token_type == mock_oauth_token.token_type
    assert token.user_integration == mock_user_integration
    assert token.resources == mock_oauth_token.resources
    assert token.id == mock_oauth_token.id
    assert token.created_at == mock_oauth_token.created_at
    assert token.updated_at == mock_oauth_token.updated_at


async def test_sharepoint_token_from_tenant_app_has_correct_structure(
    setup: Setup,
    mock_user_integration,
    mock_shared_space,
    mock_tenant_app,
):
    """SharePointToken from tenant app has correct structure."""
    setup.tenant_app_service.get_active_app_for_tenant.return_value = mock_tenant_app
    setup.tenant_app_auth_service.get_access_token.return_value = "tenant-app-token"

    token = await setup.router.get_token_for_integration(
        mock_user_integration, mock_shared_space
    )

    assert isinstance(token, SharePointToken)
    assert token.access_token == "tenant-app-token"
    assert token.refresh_token == ""  # Tenant app tokens don't have refresh tokens
    assert token.user_integration == mock_user_integration
    assert token.resources == {}
    # Note: Entity base class auto-generates UUID even when id=None is passed
    # This is fine - tenant app tokens just aren't persisted to DB
    assert token.id is not None  # Auto-generated by Entity base class
    assert token.created_at is None
    assert token.updated_at is None
