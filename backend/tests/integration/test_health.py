"""
Integration tests for authentication and user endpoints.

Note: Basic infrastructure verification (settings, database connection, app initialization,
tenant/user setup) is now done automatically in conftest.py fixtures before tests run.
"""
import pytest


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticated_user_request(client, admin_user, admin_user_api_key):
    """
    Test that an authenticated user can access /api/users/me endpoint.

    This test demonstrates the use of fixtures:
    - admin_user: The default test user (test@example.com)
    - admin_user_api_key: A fresh API key for the admin user
    """
    # Make authenticated request to /api/users/me
    response = await client.get(
        "/api/v1/users/me/",
        headers={"X-API-Key": admin_user_api_key.key}
    )

    # Verify response
    assert response.status_code == 200
    user_data = response.json()
    assert user_data["email"] == admin_user.email
    assert user_data["username"] == admin_user.username
    assert user_data["id"] == str(admin_user.id)
    assert "predefined_roles" in user_data
    assert len(user_data["predefined_roles"]) > 0

