"""Integration matrix for API-key governance and diagnostics isolation.

These tests lock the policy contract for scope lockdown:
- Governance endpoints require tenant scope + admin key permission.
- Diagnostics endpoints require tenant scope regardless of key permission.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from intric.main.config import get_settings, set_settings


@pytest.fixture
async def default_user(db_container):
    async with db_container() as container:
        user_repo = container.user_repo()
        user = await user_repo.get_user_by_email("test@example.com")
    return user


@pytest.fixture
async def default_user_token(db_container, patch_auth_service_jwt, default_user):
    async with db_container() as container:
        auth_service = container.auth_service()
        token = auth_service.create_access_token_for_user(default_user)
    return token


async def _create_space(client, *, bearer_token: str) -> str:
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"scope-lockdown-space-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_assistant(client, *, bearer_token: str, space_id: str) -> str:
    response = await client.post(
        "/api/v1/assistants/",
        json={
            "name": f"scope-lockdown-assistant-{uuid4().hex[:8]}",
            "space_id": space_id,
        },
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _create_app(client, *, bearer_token: str, space_id: str) -> str:
    response = await client.post(
        f"/api/v1/spaces/{space_id}/applications/apps/",
        json={"name": f"scope-lockdown-app-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _create_api_key(
    client,
    *,
    bearer_token: str,
    scope_type: str = "tenant",
    scope_id: str | None = None,
    permission: str = "read",
) -> str:
    body: dict[str, str] = {
        "name": f"scope-lockdown-key-{scope_type}-{permission}-{uuid4().hex[:8]}",
        "key_type": "sk_",
        "permission": permission,
        "scope_type": scope_type,
    }
    if scope_id is not None:
        body["scope_id"] = scope_id

    response = await client.post(
        "/api/v1/api-keys",
        json=body,
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    assert response.status_code == 201, response.text
    return response.json()["secret"]


def _error_detail(response) -> dict:
    payload = response.json()
    if isinstance(payload, dict) and isinstance(payload.get("detail"), dict):
        return payload["detail"]
    return payload


def _governance_paths() -> list[str]:
    paths = [
        "/api/v1/allowed-origins/",
        "/api/v1/security-classifications/",
    ]
    if get_settings().using_access_management:
        paths.append("/api/v1/roles/")
    return paths


def _diagnostics_paths(*, include_logging: bool = True) -> list[str]:
    paths = [
        "/api/v1/analysis/counts/",
        "/api/v1/analysis/metadata-statistics/",
        "/api/v1/jobs/",
    ]
    if include_logging:
        paths.append(f"/api/v1/logging/{uuid4()}/")
    return paths


def _governance_write_cases() -> list[tuple[str, str, dict | None]]:
    cases: list[tuple[str, str, dict | None]] = [
        (
            "PATCH",
            "/api/v1/security-classifications/",
            {"security_classifications": []},
        ),
        ("DELETE", f"/api/v1/security-classifications/{uuid4()}/", None),
    ]
    if get_settings().using_access_management:
        cases.append(
            (
                "POST",
                "/api/v1/roles/",
                {
                    "name": f"scope-lock-role-{uuid4().hex[:8]}",
                    "permissions": [],
                },
            )
        )
    return cases


def _expected_governance_write_denial_context(
    *, permission: str, method: str, path: str
) -> tuple[str, str]:
    """Return expected action/required_level for method-first authorization ordering."""
    normalized_method = method.upper()
    if normalized_method == "PATCH":
        if permission == "read":
            return "patch", "write"
        return "management", "admin"
    if normalized_method == "DELETE":
        return "delete", "admin"
    if normalized_method == "POST" and path.startswith("/api/v1/roles/"):
        if permission == "read":
            return "post", "write"
        return "management", "admin"
    raise AssertionError(
        f"Unhandled governance write case for permission={permission}, "
        f"method={method}, path={path}"
    )


def _smoke_endpoints() -> list[tuple[str, str, dict | None]]:
    return [
        ("GET", "/api/v1/assistants/", None),
        ("GET", "/api/v1/files/", None),
        ("GET", "/api/v1/analysis/counts/", None),
        ("GET", "/api/v1/analysis/metadata-statistics/", None),
        ("GET", "/api/v1/jobs/", None),
        ("GET", f"/api/v1/logging/{uuid4()}/", None),
        ("GET", "/api/v1/allowed-origins/", None),
        ("GET", "/api/v1/security-classifications/", None),
    ]


def _low_risk_paths() -> list[str]:
    """Routes that should remain usable by scoped keys for DX/self-service."""
    return [
        "/api/v1/users/me/",
        "/api/v1/limits/",
    ]


@contextmanager
def _scope_enforcement_kill_switch(mode: str):
    """Temporarily disable scope enforcement by env flag or tenant feature flag."""
    if mode not in {"env_off", "tenant_flag_off"}:
        raise ValueError(f"Unsupported mode: {mode}")

    settings = get_settings()
    patched = settings.model_copy(update={"api_key_enforce_scope": mode != "env_off"})
    set_settings(patched)
    tenant_patch = (
        patch(
            "intric.users.user_service.UserService._is_scope_enforcement_enabled",
            new=AsyncMock(return_value=False),
        )
        if mode == "tenant_flag_off"
        else nullcontext()
    )
    try:
        with tenant_patch:
            yield
    finally:
        set_settings(settings)


async def _resolve_scoped_ids(client, *, bearer_token: str) -> dict[str, str]:
    """Provision scope IDs for assistant/space/app.

    App scope may not be provisionable in all environments (tenant model setup).
    In that case app-scope matrix rows are skipped rather than made flaky.
    """
    space_id = await _create_space(client, bearer_token=bearer_token)
    assistant_id = await _create_assistant(
        client, bearer_token=bearer_token, space_id=space_id
    )
    scoped_ids: dict[str, str] = {
        "space": space_id,
        "assistant": assistant_id,
    }

    app_id: str | None = None
    existing_apps = await client.get(
        "/api/v1/apps/",
        headers={"Authorization": f"Bearer {bearer_token}"},
    )
    if existing_apps.status_code == 200:
        items = existing_apps.json().get("items", [])
        if items:
            app_id = items[0]["id"]
    elif existing_apps.status_code not in {404}:
        pytest.skip(
            f"Cannot query apps endpoint while provisioning governance scope matrix "
            f"(status={existing_apps.status_code})."
        )

    if app_id is None:
        try:
            app_id = await _create_app(
                client, bearer_token=bearer_token, space_id=space_id
            )
        except AssertionError:
            app_id = None

    if app_id is not None:
        scoped_ids["app"] = app_id

    return scoped_ids


def _assert_api_key_error(
    response,
    *,
    expected_code: str,
    expected_auth_layer: str,
    request_id: str,
) -> dict:
    assert response.status_code == 403, response.text
    detail = _error_detail(response)
    assert detail.get("code") == expected_code, response.text
    assert detail.get("request_id") == request_id, response.text
    context = detail.get("context", {})
    assert context.get("auth_layer") == expected_auth_layer, response.text
    return detail


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("permission", ["read", "write"])
async def test_scoped_non_admin_keys_on_governance_fail_with_management_permission(
    client,
    default_user_token,
    permission: str,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)

    for scope_type, scope_id in scoped_ids.items():
        secret = await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type=scope_type,
            scope_id=scope_id,
            permission=permission,
        )
        for path in _governance_paths():
            request_id = f"gov-{scope_type}-{permission}-{uuid4().hex[:8]}"
            response = await client.get(
                path,
                headers={
                    "X-API-Key": secret,
                    "X-Correlation-ID": request_id,
                },
            )
            detail = _assert_api_key_error(
                response,
                expected_code="insufficient_permission",
                expected_auth_layer="api_key_method",
                request_id=request_id,
            )
            assert detail.get("context", {}).get("action") == "management", response.text
            assert detail.get("context", {}).get("required_level") == "admin", response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scoped_admin_keys_on_governance_fail_with_scope(
    client,
    default_user_token,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)

    for scope_type, scope_id in scoped_ids.items():
        secret = await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type=scope_type,
            scope_id=scope_id,
            permission="admin",
        )
        for path in _governance_paths():
            request_id = f"gov-{scope_type}-admin-{uuid4().hex[:8]}"
            response = await client.get(
                path,
                headers={
                    "X-API-Key": secret,
                    "X-Correlation-ID": request_id,
                },
            )
            _assert_api_key_error(
                response,
                expected_code="insufficient_scope",
                expected_auth_layer="api_key_scope",
                request_id=request_id,
            )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("permission", ["read", "write"])
async def test_scoped_non_admin_keys_on_governance_write_fail_with_management_permission(
    client,
    default_user_token,
    permission: str,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)

    for scope_type, scope_id in scoped_ids.items():
        secret = await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type=scope_type,
            scope_id=scope_id,
            permission=permission,
        )
        for method, path, payload in _governance_write_cases():
            request_id = f"gov-write-{scope_type}-{permission}-{uuid4().hex[:8]}"
            response = await client.request(
                method,
                path,
                json=payload,
                headers={
                    "X-API-Key": secret,
                    "X-Correlation-ID": request_id,
                },
            )
            detail = _assert_api_key_error(
                response,
                expected_code="insufficient_permission",
                expected_auth_layer="api_key_method",
                request_id=request_id,
            )
            expected_action, expected_required = (
                _expected_governance_write_denial_context(
                    permission=permission,
                    method=method,
                    path=path,
                )
            )
            assert detail.get("context", {}).get("action") == expected_action, response.text
            assert (
                detail.get("context", {}).get("required_level") == expected_required
            ), response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scoped_admin_keys_on_governance_write_fail_with_scope(
    client,
    default_user_token,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)

    for scope_type, scope_id in scoped_ids.items():
        secret = await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type=scope_type,
            scope_id=scope_id,
            permission="admin",
        )
        for method, path, payload in _governance_write_cases():
            request_id = f"gov-write-{scope_type}-admin-{uuid4().hex[:8]}"
            response = await client.request(
                method,
                path,
                json=payload,
                headers={
                    "X-API-Key": secret,
                    "X-Correlation-ID": request_id,
                },
            )
            _assert_api_key_error(
                response,
                expected_code="insufficient_scope",
                expected_auth_layer="api_key_scope",
                request_id=request_id,
            )


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("permission", ["read", "write", "admin"])
async def test_scoped_keys_cannot_access_diagnostics_endpoints(
    client,
    default_user_token,
    permission: str,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)

    for scope_type, scope_id in scoped_ids.items():
        secret = await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type=scope_type,
            scope_id=scope_id,
            permission=permission,
        )
        for path in _diagnostics_paths():
            request_id = f"diag-{scope_type}-{permission}-{uuid4().hex[:8]}"
            response = await client.get(
                path,
                headers={
                    "X-API-Key": secret,
                    "X-Correlation-ID": request_id,
                },
            )
            _assert_api_key_error(
                response,
                expected_code="insufficient_scope",
                expected_auth_layer="api_key_scope",
                request_id=request_id,
            )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_key_matrix_for_governance_and_diagnostics(
    client,
    default_user_token,
):
    tenant_read = await _create_api_key(
        client,
        bearer_token=default_user_token,
        scope_type="tenant",
        permission="read",
    )
    tenant_admin = await _create_api_key(
        client,
        bearer_token=default_user_token,
        scope_type="tenant",
        permission="admin",
    )

    # Tenant-read key passes scope on diagnostics routes (may still be blocked by domain role checks).
    for path in _diagnostics_paths():
        request_id = f"tenant-read-diag-{uuid4().hex[:8]}"
        response = await client.get(
            path,
            headers={
                "X-API-Key": tenant_read,
                "X-Correlation-ID": request_id,
            },
        )
        detail = _error_detail(response)
        assert not (
            response.status_code == 403 and detail.get("code") == "insufficient_scope"
        ), response.text

    # Tenant-read keys fail governance with management permission error.
    for path in _governance_paths():
        request_id = f"tenant-read-gov-{uuid4().hex[:8]}"
        response = await client.get(
            path,
            headers={
                "X-API-Key": tenant_read,
                "X-Correlation-ID": request_id,
            },
        )
        detail = _assert_api_key_error(
            response,
            expected_code="insufficient_permission",
            expected_auth_layer="api_key_method",
            request_id=request_id,
        )
        assert detail.get("context", {}).get("action") == "management", response.text
        assert detail.get("context", {}).get("required_level") == "admin", response.text

    # Tenant-admin keys pass governance guards (endpoint-specific domain logic still applies).
    for path in _governance_paths():
        request_id = f"tenant-admin-gov-{uuid4().hex[:8]}"
        response = await client.get(
            path,
            headers={
                "X-API-Key": tenant_admin,
                "X-Correlation-ID": request_id,
            },
        )
        detail = _error_detail(response)
        assert not (
            response.status_code == 403
            and detail.get("code") in {"insufficient_permission", "insufficient_scope"}
        ), response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tenant_read_key_logging_missing_message_returns_404_not_scope_error(
    client,
    default_user_token,
):
    tenant_read = await _create_api_key(
        client,
        bearer_token=default_user_token,
        scope_type="tenant",
        permission="read",
    )

    request_id = f"tenant-read-logging-{uuid4().hex[:8]}"
    response = await client.get(
        f"/api/v1/logging/{uuid4()}/",
        headers={
            "X-API-Key": tenant_read,
            "X-Correlation-ID": request_id,
        },
    )
    assert response.status_code == 404, response.text
    detail = _error_detail(response)
    assert detail.get("request_id") == request_id, response.text
    assert detail.get("code") != "insufficient_scope", response.text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["env_off", "tenant_flag_off"])
async def test_kill_switch_scoped_admin_key_not_scope_blocked_on_locked_governance_routes(
    client,
    default_user_token,
    mode: str,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)
    assistant_id = scoped_ids["assistant"]
    scoped_admin = await _create_api_key(
        client,
        bearer_token=default_user_token,
        scope_type="assistant",
        scope_id=assistant_id,
        permission="admin",
    )

    with _scope_enforcement_kill_switch(mode):
        for path in _governance_paths():
            request_id = f"kill-switch-admin-{mode}-{uuid4().hex[:8]}"
            response = await client.get(
                path,
                headers={
                    "X-API-Key": scoped_admin,
                    "X-Correlation-ID": request_id,
                },
            )
            detail = _error_detail(response)
            assert not (
                response.status_code == 403 and detail.get("code") == "insufficient_scope"
            ), response.text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["env_off", "tenant_flag_off"])
async def test_kill_switch_keeps_management_permission_for_scoped_read_keys(
    client,
    default_user_token,
    mode: str,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)
    assistant_id = scoped_ids["assistant"]
    scoped_read = await _create_api_key(
        client,
        bearer_token=default_user_token,
        scope_type="assistant",
        scope_id=assistant_id,
        permission="read",
    )

    with _scope_enforcement_kill_switch(mode):
        request_id = f"kill-switch-read-{mode}-{uuid4().hex[:8]}"
        response = await client.get(
            "/api/v1/allowed-origins/",
            headers={
                "X-API-Key": scoped_read,
                "X-Correlation-ID": request_id,
            },
        )
        detail = _assert_api_key_error(
            response,
            expected_code="insufficient_permission",
            expected_auth_layer="api_key_method",
            request_id=request_id,
        )
        assert detail.get("context", {}).get("required_level") == "admin", response.text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["env_off", "tenant_flag_off"])
async def test_kill_switch_scoped_keys_not_scope_blocked_on_diagnostics(
    client,
    default_user_token,
    mode: str,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)
    space_id = scoped_ids["space"]
    scoped_read = await _create_api_key(
        client,
        bearer_token=default_user_token,
        scope_type="space",
        scope_id=space_id,
        permission="read",
    )

    with _scope_enforcement_kill_switch(mode):
        for path in _diagnostics_paths(include_logging=False):
            request_id = f"kill-switch-diag-{mode}-{uuid4().hex[:8]}"
            response = await client.get(
                path,
                headers={
                    "X-API-Key": scoped_read,
                    "X-Correlation-ID": request_id,
                },
            )
            detail = _error_detail(response)
            assert not (
                response.status_code == 403 and detail.get("code") == "insufficient_scope"
            ), response.text


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["env_off", "tenant_flag_off"])
async def test_kill_switch_scoped_keys_not_scope_blocked_on_logging_route(
    client,
    default_user_token,
    mode: str,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)
    assistant_id = scoped_ids["assistant"]
    scoped_read = await _create_api_key(
        client,
        bearer_token=default_user_token,
        scope_type="assistant",
        scope_id=assistant_id,
        permission="read",
    )

    with _scope_enforcement_kill_switch(mode):
        request_id = f"kill-switch-logging-{mode}-{uuid4().hex[:8]}"
        response = await client.get(
            f"/api/v1/logging/{uuid4()}/",
            headers={
                "X-API-Key": scoped_read,
                "X-Correlation-ID": request_id,
            },
        )
        detail = _error_detail(response)
        assert not (
            response.status_code == 403 and detail.get("code") == "insufficient_scope"
        ), response.text
        if isinstance(detail, dict):
            assert detail.get("request_id") == request_id, response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_api_key_scope_smoke_matrix_no_500_on_representative_locked_and_core_routes(
    client,
    default_user_token,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)
    key_specs: list[tuple[str, str, str | None]] = [
        ("assistant", "read", scoped_ids["assistant"]),
        ("assistant", "admin", scoped_ids["assistant"]),
        ("space", "write", scoped_ids["space"]),
        ("tenant", "read", None),
        ("tenant", "admin", None),
    ]
    app_scope_id = scoped_ids.get("app")
    if app_scope_id is not None:
        key_specs.append(("app", "admin", app_scope_id))

    for scope_type, permission, scope_id in key_specs:
        secret = await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type=scope_type,
            scope_id=scope_id,
            permission=permission,
        )
        for method, path, payload in _smoke_endpoints():
            request_id = f"smoke-{scope_type}-{permission}-{uuid4().hex[:8]}"
            response = await client.request(
                method,
                path,
                json=payload,
                headers={
                    "X-API-Key": secret,
                    "X-Correlation-ID": request_id,
                },
            )
            assert response.status_code != 500, (
                f"Unexpected 500 for {method} {path} with {scope_type}/{permission}: {response.text}"
            )
            if response.status_code == 403:
                detail = _error_detail(response)
                assert isinstance(detail.get("code"), str) and detail.get("code"), response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scoped_read_keys_keep_access_to_low_risk_self_service_routes(
    client,
    default_user_token,
):
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)
    key_specs: list[tuple[str, str | None]] = [
        ("assistant", scoped_ids["assistant"]),
        ("space", scoped_ids["space"]),
    ]
    app_scope_id = scoped_ids.get("app")
    if app_scope_id is not None:
        key_specs.append(("app", app_scope_id))

    for scope_type, scope_id in key_specs:
        secret = await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type=scope_type,
            scope_id=scope_id,
            permission="read",
        )
        for path in _low_risk_paths():
            request_id = f"low-risk-{scope_type}-{uuid4().hex[:8]}"
            response = await client.get(
                path,
                headers={
                    "X-API-Key": secret,
                    "X-Correlation-ID": request_id,
                },
            )
            assert response.status_code != 500, response.text
            detail = _error_detail(response)
            assert not (
                response.status_code == 403 and detail.get("code") == "insufficient_scope"
            ), response.text


@pytest.mark.integration
@pytest.mark.asyncio
async def test_scope_capability_matrix_for_core_resource_endpoints(
    client,
    default_user_token,
):
    """Lock expected read-level scope behavior on core assistant/app/file endpoints."""
    scoped_ids = await _resolve_scoped_ids(client, bearer_token=default_user_token)

    keys: dict[str, str] = {
        "assistant": await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type="assistant",
            scope_id=scoped_ids["assistant"],
            permission="read",
        ),
        "space": await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type="space",
            scope_id=scoped_ids["space"],
            permission="read",
        ),
        "tenant": await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type="tenant",
            permission="read",
        ),
    }
    app_scope_id = scoped_ids.get("app")
    if app_scope_id is not None:
        keys["app"] = await _create_api_key(
            client,
            bearer_token=default_user_token,
            scope_type="app",
            scope_id=app_scope_id,
            permission="read",
        )

    endpoint_matrix: list[tuple[str, set[str], set[str]]] = [
        ("/api/v1/files/", {"assistant", "space", "tenant", "app"}, set()),
        (
            f"/api/v1/assistants/{scoped_ids['assistant']}/",
            {"assistant", "space", "tenant"},
            {"app"},
        ),
    ]
    if app_scope_id is not None:
        endpoint_matrix.append(
            (
                f"/api/v1/apps/{app_scope_id}/",
                {"app", "space", "tenant"},
                {"assistant"},
            )
        )

    for path, allowed_scopes, scope_denied_scopes in endpoint_matrix:
        for scope_type, secret in keys.items():
            request_id = f"core-matrix-{scope_type}-{uuid4().hex[:8]}"
            response = await client.get(
                path,
                headers={
                    "X-API-Key": secret,
                    "X-Correlation-ID": request_id,
                },
            )
            detail = _error_detail(response)

            if scope_type in allowed_scopes:
                assert response.status_code != 500, response.text
                assert not (
                    response.status_code == 403
                    and detail.get("code") == "insufficient_scope"
                ), response.text
                continue

            if scope_type in scope_denied_scopes:
                denied = _assert_api_key_error(
                    response,
                    expected_code="insufficient_scope",
                    expected_auth_layer="api_key_scope",
                    request_id=request_id,
                )
                assert denied.get("context", {}).get("auth_layer") == "api_key_scope"
                continue

            raise AssertionError(
                f"Scope {scope_type} missing from matrix for path {path}. "
                f"allowed={sorted(allowed_scopes)}, denied={sorted(scope_denied_scopes)}"
            )
