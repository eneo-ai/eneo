"""Debug test to understand API key authentication issue."""

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_api_key_value(admin_user_api_key):
    """Print the actual API key value."""
    print("\n=== DEBUG: API Key Object ===")
    print(f"Type: {type(admin_user_api_key)}")
    print(f"Key: {admin_user_api_key.key}")
    print(f"Hashed Key: {admin_user_api_key.hashed_key}")
    print(f"Truncated Key: {admin_user_api_key.truncated_key}")
    assert admin_user_api_key.key is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_auth_headers(auth_headers):
    """Print auth headers."""
    print("\n=== DEBUG: Auth Headers ===")
    print(f"Headers: {auth_headers}")
    assert "X-API-Key" in auth_headers


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_direct_request(client, admin_user_api_key):
    """Test API key directly without auth_headers fixture."""
    print("\n=== DEBUG: Direct API key test ===")
    print(f"Using key: {admin_user_api_key.key[:20]}...")

    response = await client.get(
        "/api/v1/users/me/", headers={"X-API-Key": admin_user_api_key.key}
    )
    print(f"Response status: {response.status_code}")
    print(f"Response body: {response.text[:200]}...")
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_via_auth_headers(client, auth_headers):
    """Test API key via auth_headers fixture."""
    print("\n=== DEBUG: Via auth_headers fixture ===")
    print(f"Headers: {auth_headers}")

    response = await client.get("/api/v1/users/me/", headers=auth_headers)
    print(f"Response status: {response.status_code}")
    print(f"Response body: {response.text[:200]}...")
    assert response.status_code == 200


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_session_endpoint(client, auth_headers):
    """Test the audit session endpoint directly."""
    print("\n=== DEBUG: Session endpoint test ===")
    print(f"Headers: {auth_headers}")

    response = await client.post(
        "/api/v1/audit/access-session",
        json={"category": "integration_test", "description": "Debug test session"},
        headers=auth_headers,
    )
    print(f"Response status: {response.status_code}")
    print(f"Response headers: {dict(response.headers)}")
    print(f"Response body: {response.text}")

    # Don't assert success - just see what happens
    if response.status_code != 200:
        print(f"FAILED with {response.status_code}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_header_name(debug_auth_config):
    """Check what API header name is configured."""
    pass


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_full_trace(client, admin_user_api_key, admin_user, db_container):
    """Full trace of what's happening."""
    print("\n=== FULL TRACE ===")
    print(f"1. Admin user ID: {admin_user.id}")
    print(f"2. Admin user email: {admin_user.email}")
    print(f"3. API key created: {admin_user_api_key.key[:20]}...")
    print(f"4. API key hashed: {admin_user_api_key.hashed_key[:20]}...")

    # Check if API key is in database
    from sqlalchemy import text

    async with db_container() as container:
        session = container.session()
        result = await session.execute(
            text("SELECT key, user_id FROM api_keys WHERE user_id = :user_id"),
            {"user_id": str(admin_user.id)},
        )
        rows = result.fetchall()
        print(f"5. API keys in DB for user {admin_user.id}:")
        for row in rows:
            print(f"   - key: {row[0][:20]}..., user_id: {row[1]}")

    # Now test the endpoint
    headers = {"X-API-Key": admin_user_api_key.key}
    print(f"6. Testing with header: {headers}")

    # Test users/me first
    response1 = await client.get("/api/v1/users/me/", headers=headers)
    print(f"7. /users/me response: {response1.status_code}")

    # Test audit session
    response2 = await client.post(
        "/api/v1/audit/access-session",
        json={"category": "test", "description": "Debug test"},
        headers=headers,
    )
    print(
        f"8. /audit/access-session response: {response2.status_code} - {response2.text}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_api_key_header_extraction(client, admin_user_api_key):
    """Test API key header extraction at different endpoints."""
    from intric.server.dependencies.auth_definitions import API_KEY_HEADER
    from intric.main.config import get_settings

    print("\n=== API KEY HEADER CONFIGURATION ===")
    print(f"API_KEY_HEADER.model.name: {API_KEY_HEADER.model.name}")
    print(f"get_settings().api_key_header_name: {get_settings().api_key_header_name}")
    print(f"Test API key: {admin_user_api_key.key[:30]}...")

    # Test with exact header name
    response = await client.post(
        "/api/v1/audit/access-session",
        json={"category": "test", "description": "Test"},
        headers={API_KEY_HEADER.model.name: admin_user_api_key.key},
    )
    print(f"With {API_KEY_HEADER.model.name}: {response.status_code}")

    # Test with X-API-Key
    response2 = await client.post(
        "/api/v1/audit/access-session",
        json={"category": "test", "description": "Test"},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    print(f"With X-API-Key: {response2.status_code}")

    # Test with lowercase
    response3 = await client.post(
        "/api/v1/audit/access-session",
        json={"category": "test", "description": "Test"},
        headers={"x-api-key": admin_user_api_key.key},
    )
    print(f"With x-api-key: {response3.status_code}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_user_permissions(admin_user, db_container):
    """Check user permissions and roles."""
    print("\n=== USER PERMISSIONS DEBUG ===")
    print(f"User ID: {admin_user.id}")
    print(f"User email: {admin_user.email}")
    print(f"User roles: {getattr(admin_user, 'roles', 'N/A')}")
    print(f"User predefined_roles: {getattr(admin_user, 'predefined_roles', 'N/A')}")
    print(f"User permissions: {getattr(admin_user, 'permissions', 'N/A')}")
    print(f"User is_superuser: {getattr(admin_user, 'is_superuser', 'N/A')}")

    # Check if Permission.ADMIN is in user's permissions
    from intric.roles.permissions import Permission

    has_admin = Permission.ADMIN in getattr(admin_user, "permissions", set())
    print(f"Has ADMIN permission: {has_admin}")

    # List all attributes
    print("\nAll user attributes:")
    for attr in dir(admin_user):
        if not attr.startswith("_"):
            try:
                val = getattr(admin_user, attr)
                if not callable(val):
                    print(f"  {attr}: {val}")
            except Exception as e:
                print(f"  {attr}: <error: {e}>")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_authentication_path(client, admin_user_api_key):
    """Trace what happens in authentication."""
    import logging

    logging.getLogger("intric").setLevel(logging.DEBUG)

    print("\n=== TRACING AUTHENTICATION ===")
    print(f"API Key: {admin_user_api_key.key[:30]}...")

    # Make request to audit endpoint with more logging
    response = await client.post(
        "/api/v1/audit/access-session",
        json={"category": "test", "description": "Debug trace"},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    print(f"Response: {response.status_code}")
    print(f"Body: {response.text}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_direct_service_call(admin_user_api_key, db_container):
    """Directly call the service to verify auth works."""

    async with db_container() as container:
        auth_service = container.auth_service()

        # Try to get API key directly
        print("\n=== DIRECT SERVICE CALL ===")
        print(f"Plain key: {admin_user_api_key.key[:30]}...")

        key = await auth_service.get_api_key(admin_user_api_key.key)
        print(f"Retrieved API key: {key}")
        print(f"User ID: {key.user_id if key else 'None'}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_container_dependencies(client, admin_user_api_key):
    """Check how API key is extracted in different dependencies."""
    from intric.server.dependencies.auth_definitions import API_KEY_HEADER
    from intric.authentication.auth_dependencies import _get_api_key_from_header

    print("\n=== DEPENDENCY ANALYSIS ===")
    print(f"API_KEY_HEADER type: {type(API_KEY_HEADER)}")
    print(f"API_KEY_HEADER.model.name: {API_KEY_HEADER.model.name}")
    print(f"_get_api_key_from_header type: {type(_get_api_key_from_header)}")

    # Create a test endpoint to check what API_KEY_HEADER extracts
    from fastapi import FastAPI, Security

    test_app = FastAPI()

    @test_app.get("/test-api-key-header")
    async def test_api_key_header(api_key: str = Security(API_KEY_HEADER)):
        return {"api_key": api_key[:20] if api_key else None}

    @test_app.get("/test-custom-header")
    async def test_custom_header(api_key: str = Security(_get_api_key_from_header)):
        return {"api_key": api_key[:20] if api_key else None}

    from httpx import AsyncClient

    async with AsyncClient(app=test_app, base_url="http://test") as test_client:
        # Test API_KEY_HEADER extraction
        response1 = await test_client.get(
            "/test-api-key-header", headers={"X-API-Key": admin_user_api_key.key}
        )
        print(f"API_KEY_HEADER extraction: {response1.json()}")

        # Test custom function extraction
        response2 = await test_client.get(
            "/test-custom-header", headers={"X-API-Key": admin_user_api_key.key}
        )
        print(f"Custom function extraction: {response2.json()}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_full_container_flow(client, admin_user_api_key):
    """Check full container flow with API key."""
    from fastapi import FastAPI, Depends
    from intric.server.dependencies.container import get_container
    from intric.main.container.container import Container

    print("\n=== FULL CONTAINER FLOW TEST ===")

    # Create a test endpoint using same pattern as audit routes
    test_app = FastAPI()

    @test_app.post("/test-audit-style")
    async def test_audit_style(
        container: Container = Depends(get_container(with_user=True)),
    ):
        user = container.user()
        return {"user_id": str(user.id), "email": user.email}

    from httpx import AsyncClient

    async with AsyncClient(app=test_app, base_url="http://test") as test_client:
        response = await test_client.post(
            "/test-audit-style", headers={"X-API-Key": admin_user_api_key.key}
        )
        print(f"Status: {response.status_code}")
        print(f"Body: {response.text}")

        if response.status_code != 200:
            print("FAILED - same pattern fails in isolated app too")
        else:
            print("SUCCESS - pattern works in isolated app")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_compare_endpoints(client, admin_user_api_key):
    """Compare how both endpoints handle the same API key."""

    print("\n=== COMPARE ENDPOINTS ===")
    print(f"API Key: {admin_user_api_key.key[:30]}...")

    # First test /users/me
    response1 = await client.get(
        "/api/v1/users/me/", headers={"X-API-Key": admin_user_api_key.key}
    )
    print(f"/users/me/ status: {response1.status_code}")
    if response1.status_code == 200:
        data = response1.json()
        print(f"/users/me/ user: {data.get('email')}")

    # Then test /audit/access-session
    response2 = await client.post(
        "/api/v1/audit/access-session",
        json={"category": "test", "description": "Debug compare test"},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    print(f"/audit/access-session status: {response2.status_code}")
    print(f"/audit/access-session body: {response2.text}")

    # They should both work with the same API key
    assert response1.status_code == 200, f"users/me failed: {response1.text}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_http_database_connection(
    client, admin_user_api_key, test_settings
):
    """Check which database the HTTP handler is using."""
    from intric.database.database import sessionmanager

    print("\n=== HTTP DATABASE CONNECTION ===")
    print(f"Test settings postgres_host: {test_settings.postgres_host}")
    print(f"Test settings postgres_db: {test_settings.postgres_db}")
    print(f"Test settings postgres_port: {test_settings.postgres_port}")

    # Check sessionmanager
    print("\nSessionmanager settings:")
    print(f"  _engine: {sessionmanager._engine}")
    print(f"  _sessionmaker: {sessionmanager._sessionmaker}")

    # Try a direct query via the client to see database info
    response = await client.get(
        "/api/v1/users/me/", headers={"X-API-Key": admin_user_api_key.key}
    )
    print(f"\n/users/me/ response: {response.status_code}")
    if response.status_code == 200:
        print(f"  User: {response.json().get('email')}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_trace_authenticate(client, admin_user_api_key, monkeypatch):
    """Add tracing to authenticate function."""
    import intric.users.user_service as user_service_module

    original_authenticate = user_service_module.UserService.authenticate
    call_count = {"count": 0}

    async def traced_authenticate(
        self, token=None, api_key=None, with_quota_used=False, request=None
    ):
        call_count["count"] += 1
        print(f"\n>>> AUTHENTICATE CALL #{call_count['count']}")
        print(f"    token: {token[:20] if token else None}...")
        print(f"    api_key: {api_key[:20] if api_key else None}...")

        result = await original_authenticate(
            self,
            token=token,
            api_key=api_key,
            with_quota_used=with_quota_used,
            request=request,
        )
        print(f"    result: {result}")
        return result

    monkeypatch.setattr(
        user_service_module.UserService, "authenticate", traced_authenticate
    )

    # Test /users/me/
    print("\n=== Testing /users/me/ ===")
    response1 = await client.get(
        "/api/v1/users/me/", headers={"X-API-Key": admin_user_api_key.key}
    )
    print(f"Response: {response1.status_code}")

    # Test /audit/access-session
    print("\n=== Testing /audit/access-session ===")
    response2 = await client.post(
        "/api/v1/audit/access-session",
        json={"category": "test", "description": "Trace test"},
        headers={"X-API-Key": admin_user_api_key.key},
    )
    print(f"Response: {response2.status_code}")
    print(f"Body: {response2.text}")

    print(f"\nTotal authenticate calls: {call_count['count']}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_api_key_header_actual(client, admin_user_api_key):
    """Check what header API_KEY_HEADER actually looks for."""
    from intric.server.dependencies.auth_definitions import API_KEY_HEADER
    from intric.main.config import get_settings

    print("\n=== API_KEY_HEADER DETAILS ===")
    print(f"API_KEY_HEADER: {API_KEY_HEADER}")
    print(f"API_KEY_HEADER type: {type(API_KEY_HEADER)}")
    print(f"API_KEY_HEADER.model: {API_KEY_HEADER.model}")
    print(f"API_KEY_HEADER.model.name: {API_KEY_HEADER.model.name}")
    print(f"API_KEY_HEADER.model.in_: {API_KEY_HEADER.model.in_}")
    print(f"API_KEY_HEADER.auto_error: {API_KEY_HEADER.auto_error}")

    # Check settings
    settings = get_settings()
    print(f"\nSettings api_key_header_name: {settings.api_key_header_name}")

    # Check if they match
    if API_KEY_HEADER.model.name != settings.api_key_header_name:
        print(
            f"\n>>> MISMATCH! API_KEY_HEADER uses '{API_KEY_HEADER.model.name}' but settings say '{settings.api_key_header_name}'"
        )
    else:
        print("\n>>> Header names MATCH")

    # Now let's send with the EXACT header name API_KEY_HEADER uses
    print(f"\nTesting with header '{API_KEY_HEADER.model.name}':")
    response = await client.post(
        "/api/v1/audit/access-session",
        json={"category": "test", "description": "Test"},
        headers={API_KEY_HEADER.model.name: admin_user_api_key.key},
    )
    print(f"Response: {response.status_code}")
    print(f"Body: {response.text}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_request_headers(client, admin_user_api_key, app):
    """Debug what headers are actually received by the request."""
    from fastapi import Request

    # Add a test endpoint to inspect headers
    @app.post("/debug/inspect-headers")
    async def inspect_headers(request: Request):
        return {
            "headers": dict(request.headers),
            "x_api_key": request.headers.get("X-API-Key"),
            "x_api_key_lower": request.headers.get("x-api-key"),
        }

    print("\n=== REQUEST HEADERS INSPECTION ===")

    # Test with POST
    response = await client.post(
        "/debug/inspect-headers", headers={"X-API-Key": admin_user_api_key.key}
    )
    print("POST /debug/inspect-headers:")
    print(f"  Status: {response.status_code}")
    data = response.json()
    print(f"  Headers received: {list(data['headers'].keys())}")
    print(f"  X-API-Key: {data['x_api_key'][:30] if data['x_api_key'] else None}...")

    # Test with GET
    response2 = await client.get(
        "/debug/inspect-headers", headers={"X-API-Key": admin_user_api_key.key}
    )
    print("\nGET /debug/inspect-headers:")
    print(f"  Status: {response2.status_code}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_debug_api_key_header_instances():
    """Check if there are multiple API_KEY_HEADER instances."""
    from intric.server.dependencies.auth_definitions import (
        API_KEY_HEADER as auth_def_header,
    )
    from intric.server.dependencies.container import API_KEY_HEADER as container_header

    print("\n=== API_KEY_HEADER INSTANCES ===")
    print(
        f"auth_definitions.API_KEY_HEADER: {id(auth_def_header)} - name={auth_def_header.model.name}"
    )
    print(
        f"container.API_KEY_HEADER: {id(container_header)} - name={container_header.model.name}"
    )
    print(f"Same instance: {auth_def_header is container_header}")
