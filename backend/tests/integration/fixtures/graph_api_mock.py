"""Fixtures for mocking Microsoft Graph API responses in SharePoint integration tests."""

import json
from collections.abc import Callable
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def graph_api_mock(monkeypatch):
    """Provide a configurable fake aiohttp client for Microsoft Graph API calls.

    This fixture mocks Graph API endpoints used by SharePoint integrations:
    - OAuth token acquisition (client_credentials and authorization_code flows)
    - Subscription management (POST/PATCH/DELETE /subscriptions)
    - Site and drive content (sites, drives, items, delta)

    Example usage:
        ```python
        graph_mock = graph_api_mock(
            token_responses={
                ("https://login.microsoftonline.com/tenant.onmicrosoft.com/oauth2/v2.0/token", "client_credentials"): {
                    "access_token": "access-token-123",
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            },
            subscription_responses={
                ("POST", "https://graph.microsoft.com/v1.0/subscriptions"): {
                    "id": "sub-123",
                    "resource": "/sites/site-id/drives/drive-id/root",
                    "expirationDateTime": (datetime.utcnow() + timedelta(days=1)).isoformat() + "Z",
                },
            },
        )
        ```

    Args:
        token_responses: Maps (token_url, grant_type) to token response payload
        subscription_responses: Maps (method, url) to subscription response payload
        content_responses: Maps (method, url) to content API response payload
        default_token_response: Default token response if URL not in token_responses

    Returns:
        Callable that returns request log summary
    """

    def _install(
        *,
        token_responses: dict[tuple[str, str], tuple[dict, int] | dict] | None = None,
        subscription_responses: dict[tuple[str, str], tuple[dict, int] | dict] | None = None,
        content_responses: dict[tuple[str, str], tuple[dict, int] | dict] | None = None,
        default_token_response: dict | None = None,
    ) -> Callable[[], dict[str, list[tuple[str, str, dict | None]]]]:
        """Install the mock and return a function to retrieve request logs.

        Returns:
            Function that returns {"requests": [(method, url, data), ...]}
        """
        # Normalize responses to include status codes
        token_map: dict[tuple[str, str], tuple[dict, int]] = {}
        for key, payload in (token_responses or {}).items():
            if isinstance(payload, tuple):
                token_map[key] = payload
            else:
                token_map[key] = (payload, 200)

        subscription_map: dict[tuple[str, str], tuple[dict, int]] = {}
        for key, payload in (subscription_responses or {}).items():
            if isinstance(payload, tuple):
                subscription_map[key] = payload
            else:
                subscription_map[key] = (payload, 200)

        content_map: dict[tuple[str, str], tuple[dict, int]] = {}
        for key, payload in (content_responses or {}).items():
            if isinstance(payload, tuple):
                content_map[key] = payload
            else:
                content_map[key] = (payload, 200)

        request_log: list[tuple[str, str, dict | None]] = []

        class _FakeResponse:
            """Fake aiohttp response object."""

            def __init__(self, payload: dict | str, status: int = 200):
                self._payload = payload
                self.status = status

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def json(self):
                if isinstance(self._payload, str):
                    return json.loads(self._payload)
                return self._payload

            async def text(self):
                if isinstance(self._payload, dict):
                    return json.dumps(self._payload)
                return self._payload

        class _FakeClient:
            """Fake aiohttp ClientSession."""

            def get(self, url: str, **kwargs):
                """Handle GET requests to Graph API."""
                request_log.append(("GET", url, None))

                # Match content API responses
                key = ("GET", url)
                if key in content_map:
                    payload, status = content_map[key]
                    return _FakeResponse(payload, status)

                # For URLs with query parameters, try matching base URL
                if "?" in url:
                    base_url = url.split("?")[0]
                    key = ("GET", base_url)
                    if key in content_map:
                        payload, status = content_map[key]
                        return _FakeResponse(payload, status)

                raise AssertionError(f"Unmocked Graph API GET request: {url}")

            def post(self, url: str, data=None, json=None, **kwargs):
                """Handle POST requests to Graph API (token acquisition, subscriptions)."""
                request_data = data or json
                request_log.append(("POST", url, request_data))

                # Token endpoint
                if "/oauth2/v2.0/token" in url:
                    grant_type = None
                    if isinstance(request_data, dict):
                        grant_type = request_data.get("grant_type")

                    key = (url, grant_type)
                    if key in token_map:
                        payload, status = token_map[key]
                        return _FakeResponse(payload, status)

                    # Try matching without grant_type
                    if default_token_response:
                        return _FakeResponse(default_token_response, 200)

                    raise AssertionError(f"Unmocked token request: {url} grant_type={grant_type}")

                # Subscription endpoint
                if "/subscriptions" in url:
                    key = ("POST", url)
                    if key in subscription_map:
                        payload, status = subscription_map[key]
                        return _FakeResponse(payload, status)

                    # Generic subscription creation response
                    if "https://graph.microsoft.com/v1.0/subscriptions" in url:
                        # Return default subscription response
                        default_sub = {
                            "id": "mock-subscription-id",
                            "resource": "/sites/mock-site/drives/mock-drive/root",
                            "changeType": "updated",
                            "notificationUrl": request_data.get("notificationUrl", "https://example.com/webhook") if request_data else "https://example.com/webhook",
                            "expirationDateTime": (datetime.utcnow() + timedelta(hours=48)).isoformat() + "Z",
                            "clientState": request_data.get("clientState", "mock-client-state") if request_data else "mock-client-state",
                        }
                        return _FakeResponse(default_sub, 201)

                raise AssertionError(f"Unmocked Graph API POST request: {url}")

            def patch(self, url: str, data=None, json=None, **kwargs):
                """Handle PATCH requests to Graph API (subscription renewal)."""
                request_data = data or json
                request_log.append(("PATCH", url, request_data))

                key = ("PATCH", url)
                if key in subscription_map:
                    payload, status = subscription_map[key]
                    return _FakeResponse(payload, status)

                # Generic subscription renewal response
                if "/subscriptions/" in url:
                    sub_id = url.split("/subscriptions/")[-1].split("/")[0].split("?")[0]
                    default_renewal = {
                        "id": sub_id,
                        "expirationDateTime": request_data.get("expirationDateTime") if request_data else (datetime.utcnow() + timedelta(hours=48)).isoformat() + "Z",
                    }
                    return _FakeResponse(default_renewal, 200)

                raise AssertionError(f"Unmocked Graph API PATCH request: {url}")

            def delete(self, url: str, **kwargs):
                """Handle DELETE requests to Graph API (subscription deletion)."""
                request_log.append(("DELETE", url, None))

                key = ("DELETE", url)
                if key in subscription_map:
                    payload, status = subscription_map[key]
                    return _FakeResponse(payload, status)

                # Generic subscription deletion (returns 204 No Content)
                if "/subscriptions/" in url:
                    return _FakeResponse({}, 204)

                raise AssertionError(f"Unmocked Graph API DELETE request: {url}")

        fake_client = _FakeClient()

        def _client_factory():
            """Factory function that returns the fake client."""
            return fake_client

        # Monkeypatch aiohttp_client in integration module
        import intric.main.aiohttp_client as aiohttp_client_module

        monkeypatch.setattr(aiohttp_client_module, "aiohttp_client", _client_factory)

        # Also patch any integration-specific aiohttp client imports
        monkeypatch.setattr(
            "intric.integration.infrastructure.auth_service.sharepoint_auth_service.aiohttp_client",
            _client_factory,
            raising=False,
        )
        monkeypatch.setattr(
            "intric.integration.infrastructure.auth_service.tenant_app_auth_service.aiohttp_client",
            _client_factory,
            raising=False,
        )
        monkeypatch.setattr(
            "intric.integration.infrastructure.sharepoint_subscription_service.aiohttp_client",
            _client_factory,
            raising=False,
        )
        monkeypatch.setattr(
            "intric.integration.infrastructure.clients.sharepoint_content_client.aiohttp_client",
            _client_factory,
            raising=False,
        )

        def _summary() -> dict[str, list[tuple[str, str, dict | None]]]:
            """Return summary of all requests made."""
            return {"requests": request_log}

        return _summary

    return _install


@pytest.fixture
def default_graph_token_response():
    """Default token response for Graph API mock."""
    return {
        "token_type": "Bearer",
        "expires_in": 3600,
        "access_token": "mock-access-token-123",
        "refresh_token": "mock-refresh-token-456",
    }


@pytest.fixture
def graph_token_url_factory():
    """Factory for creating Graph API token URLs."""
    def _create_url(tenant_domain: str = "contoso.onmicrosoft.com") -> str:
        return f"https://login.microsoftonline.com/{tenant_domain}/oauth2/v2.0/token"
    return _create_url


@pytest.fixture
def graph_subscription_factory():
    """Factory for creating Graph API subscription responses."""
    def _create_subscription(
        subscription_id: str = "mock-sub-id",
        site_id: str = "mock-site-id",
        drive_id: str = "mock-drive-id",
        expiration_hours: int = 48,
        client_state: str = "mock-client-state",
    ) -> dict:
        return {
            "id": subscription_id,
            "resource": f"/sites/{site_id}/drives/{drive_id}/root",
            "changeType": "updated",
            "notificationUrl": "https://example.com/webhook",
            "expirationDateTime": (datetime.utcnow() + timedelta(hours=expiration_hours)).isoformat() + "Z",
            "clientState": client_state,
        }
    return _create_subscription
