from typing import Optional
from uuid import UUID, uuid4
import json
import time
import traceback

import aiohttp
import jwt
from fastapi import APIRouter, Depends, Query
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from intric.authentication import auth_dependencies
from intric.authentication.auth_models import AccessToken, ApiKey, OpenIdConnectLogin
from intric.main import config
from intric.main.aiohttp_client import aiohttp_client
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.models import CursorPaginatedResponse
from intric.server.dependencies.container import get_container
from intric.server.protocol import responses
from intric.tenants.tenant import TenantPublic
from intric.users.user import (
    PropUserInvite,
    PropUserUpdate,
    UserAdminView,
    UserInDB,
    UserLogin,
    UserProvision,
    UserPublic,
    UserSparse,
)

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/login/token/",
    response_model=AccessToken,
    name="Login",
    responses=responses.get_responses([401]),
)
async def user_login_with_email_and_password(
    form_data: OAuth2PasswordRequestForm = Depends(OAuth2PasswordRequestForm),
    container: Container = Depends(get_container()),
) -> AccessToken:
    """OAuth2 Login"""

    try:
        UserLogin(email=form_data.username, password=form_data.password)
    except ValidationError as e:
        raise HTTPException(422, e.errors())

    service = container.user_service()
    return await service.login(form_data.username, form_data.password)


@router.post("/login/openid-connect/mobilityguard/", response_model=AccessToken)
async def login_with_mobilityguard(
    openid_connect_login: OpenIdConnectLogin,
    container: Container = Depends(get_container()),
):
    """OpenID Connect Login (generic OIDC provider)."""
    correlation_id = str(uuid4())
    start_time = time.time()

    logger.debug(
        "OIDC login initiated",
        extra={
            "correlation_id": correlation_id,
            "client_id": openid_connect_login.client_id,
            "redirect_uri": openid_connect_login.redirect_uri,
            "has_code": bool(openid_connect_login.code),
            "has_code_verifier": bool(openid_connect_login.code_verifier),
        },
    )

    settings = config.get_settings()

    # Compute redirect_uri server-side (ignore frontend-provided value)
    encryption_service = container.encryption_service()
    from intric.settings.credential_resolver import CredentialResolver
    credential_resolver = CredentialResolver(
        tenant=None,  # Single-tenant mode - no tenant context
        settings=settings,
        encryption_service=encryption_service,
    )

    try:
        redirect_uri = credential_resolver.get_redirect_uri()
    except ValueError as e:
        logger.error(
            "Failed to resolve redirect_uri",
            extra={
                "correlation_id": correlation_id,
                "error": str(e),
            },
        )
        raise HTTPException(
            500,
            "OIDC redirect_uri not configured. Set PUBLIC_ORIGIN environment variable.",
        )

    # Override frontend-provided redirect_uri with server-computed value (defense in depth)
    if openid_connect_login.redirect_uri != redirect_uri:
        logger.warning(
            "Redirect URI mismatch - using server-configured value",
            extra={
                "correlation_id": correlation_id,
                "frontend_provided": openid_connect_login.redirect_uri,
                "server_computed": redirect_uri,
            },
        )
        openid_connect_login.redirect_uri = redirect_uri

    logger.info(
        "OIDC login initiated (single-tenant)",
        extra={
            "correlation_id": correlation_id,
            "redirect_uri": redirect_uri,
            "source": "server-computed from PUBLIC_ORIGIN",
        },
    )

    # Check required configuration
    if not settings.oidc_discovery_endpoint:
        logger.error(
            "OIDC discovery endpoint not configured",
            extra={"correlation_id": correlation_id, "provider": "oidc"},
        )
        raise HTTPException(500, "OIDC provider not properly configured")

    if not settings.oidc_client_secret:
        logger.error(
            "OIDC client secret not configured",
            extra={"correlation_id": correlation_id, "provider": "oidc"},
        )
        raise HTTPException(500, "OIDC provider not properly configured")

    if not settings.oidc_tenant_id:
        logger.warning(
            "OIDC tenant ID not configured - new user creation will fail",
            extra={"correlation_id": correlation_id, "provider": "oidc"},
        )

    try:
        # Get the endpoints from discovery endpoint
        discovery_start = time.time()
        logger.debug(
            f"Fetching OIDC discovery endpoint: {settings.oidc_discovery_endpoint}",
            extra={"correlation_id": correlation_id, "provider": "oidc"},
        )

        async with aiohttp_client().get(settings.oidc_discovery_endpoint) as resp:
            discovery_time = time.time() - discovery_start

            if resp.status != 200:
                response_text = await resp.text()
                logger.error(
                    f"OIDC discovery endpoint failed with status {resp.status}",
                    extra={
                        "correlation_id": correlation_id,
                        "provider": "oidc",
                        "status": resp.status,
                        "response": response_text[:500],  # Truncate for logging
                        "duration_ms": discovery_time * 1000,
                    },
                )
                raise HTTPException(502, "Failed to fetch OIDC discovery endpoint")

            endpoints = await resp.json()
            logger.debug(
                "OIDC discovery endpoint fetched successfully",
                extra={
                    "correlation_id": correlation_id,
                    "provider": "oidc",
                    "duration_ms": discovery_time * 1000,
                    "token_endpoint": endpoints.get("token_endpoint"),
                    "jwks_uri": endpoints.get("jwks_uri"),
                    "userinfo_endpoint": endpoints.get("userinfo_endpoint"),
                    "authorization_endpoint": endpoints.get("authorization_endpoint"),
                },
            )

    except aiohttp.ClientError as e:
        logger.error(
            f"Network error fetching OIDC discovery endpoint: {str(e)}",
            extra={
                "correlation_id": correlation_id,
                "provider": "oidc",
                "error_type": type(e).__name__,
                "error": str(e),
            },
        )
        raise HTTPException(502, "Network error during OIDC authentication")

    token_endpoint = endpoints["token_endpoint"]
    jwks_endpoint = endpoints["jwks_uri"]
    signing_algos = endpoints["id_token_signing_alg_values_supported"]

    # Exchange code for a token
    token_exchange_start = time.time()
    logger.debug(
        f"OIDC token exchange at: {token_endpoint}",
        extra={
            "correlation_id": correlation_id,
            "provider": "oidc",
            "client_id": openid_connect_login.client_id,
            "grant_type": openid_connect_login.grant_type,
            "scope": openid_connect_login.scope,
        },
    )

    try:
        async with aiohttp_client().post(
            token_endpoint,
            data=openid_connect_login.model_dump(),
            auth=aiohttp.BasicAuth(
                openid_connect_login.client_id,
                settings.oidc_client_secret,
            ),
        ) as resp:
            token_exchange_time = time.time() - token_exchange_start
            response_text = await resp.text()

            if resp.status != 200:
                logger.error(
                    f"OIDC token exchange failed with status {resp.status}",
                    extra={
                        "correlation_id": correlation_id,
                        "provider": "oidc",
                        "status": resp.status,
                        "response": response_text[:500],  # Truncate sensitive data
                        "duration_ms": token_exchange_time * 1000,
                        "client_id": openid_connect_login.client_id,
                    },
                )
                if resp.status == 401:
                    raise HTTPException(
                        401, "Invalid client credentials or authorization code"
                    )
                elif resp.status == 400:
                    raise HTTPException(400, "Invalid token request - check parameters")
                else:
                    raise HTTPException(
                        resp.status, f"OIDC token exchange failed: {resp.status}"
                    )

            try:
                token_response = json.loads(response_text)
            except json.JSONDecodeError:
                logger.error(
                    "OIDC token response is not valid JSON",
                    extra={
                        "correlation_id": correlation_id,
                        "provider": "oidc",
                        "response": response_text[:500],
                    },
                )
                raise HTTPException(502, "Invalid OIDC token response format")

            logger.debug(
                "OIDC token exchange successful",
                extra={
                    "correlation_id": correlation_id,
                    "provider": "oidc",
                    "duration_ms": token_exchange_time * 1000,
                    "has_id_token": "id_token" in token_response,
                    "has_access_token": "access_token" in token_response,
                    "has_refresh_token": "refresh_token" in token_response,
                    "token_type": token_response.get("token_type"),
                    "expires_in": token_response.get("expires_in"),
                },
            )

    except aiohttp.ClientError as e:
        logger.error(
            f"Network error during OIDC token exchange: {str(e)}",
            extra={
                "correlation_id": correlation_id,
                "provider": "oidc",
                "error_type": type(e).__name__,
                "error": str(e),
            },
        )
        raise HTTPException(502, "Network error during OIDC token exchange")

    if "id_token" not in token_response or "access_token" not in token_response:
        logger.error(
            "OIDC token response missing required fields",
            extra={
                "correlation_id": correlation_id,
                "provider": "oidc",
                "fields_received": list(token_response.keys()),
                "fields_required": ["id_token", "access_token"],
            },
        )
        raise HTTPException(
            502, "Invalid OIDC token response - missing id_token or access_token"
        )

    id_token = token_response["id_token"]
    access_token = token_response["access_token"]

    # Get the jwks
    jwks_start = time.time()
    logger.debug(
        f"Fetching JWKS from: {jwks_endpoint}", extra={"correlation_id": correlation_id}
    )

    try:
        jwks_client = jwt.PyJWKClient(jwks_endpoint)
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        jwks_time = time.time() - jwks_start

        logger.debug(
            "OIDC JWKS fetched and signing key extracted",
            extra={
                "correlation_id": correlation_id,
                "duration_ms": jwks_time * 1000,
                "key_id": signing_key.key_id
                if hasattr(signing_key, "key_id")
                else None,
            },
        )
    except Exception as e:
        logger.error(
            f"Failed to get signing key from OIDC JWKS: {str(e)}",
            extra={
                "correlation_id": correlation_id,
                "provider": "oidc",
                "error_type": type(e).__name__,
                "error": str(e),
                "jwks_uri": jwks_endpoint,
            },
        )
        raise HTTPException(502, "Failed to verify OIDC token signature")

    # Sign in
    user_service = container.user_service()

    try:
        service_start = time.time()
        (
            intric_token,
            was_federated,
            user_in_db,
        ) = await user_service.login_with_mobilityguard(
            id_token=id_token,
            access_token=access_token,
            key=signing_key,
            signing_algos=signing_algos,
            correlation_id=correlation_id,  # Pass correlation ID to service
        )
        service_time = time.time() - service_start

        total_time = time.time() - start_time
        logger.info(
            "OIDC login successful",
            extra={
                "correlation_id": correlation_id,
                "was_federated": was_federated,
                "user_id": str(user_in_db.id) if user_in_db else None,
                "user_email": user_in_db.email if user_in_db else None,
                "service_duration_ms": service_time * 1000,
                "total_duration_ms": total_time * 1000,
            },
        )

    except Exception as e:
        total_time = time.time() - start_time
        logger.error(
            f"OIDC user service login failed: {str(e)}",
            extra={
                "correlation_id": correlation_id,
                "provider": "oidc",
                "error_type": type(e).__name__,
                "error": str(e),
                "traceback": traceback.format_exc(),
                "total_duration_ms": total_time * 1000,
            },
        )
        raise HTTPException(401, "OIDC authentication failed")

    return intric_token


@router.get("/", response_model=CursorPaginatedResponse[UserSparse])
async def get_tenant_users(
    email: Optional[str] = Query(None, description="Email of user"),
    limit: int = Query(None, description="Users per page", ge=1),
    cursor: Optional[str] = Query(None, description="Current cursor"),
    previous: Optional[bool] = Query(False, description="Show previous page"),
    container: Container = Depends(get_container(with_user=True)),
):
    user = container.user()
    user_assembler = container.user_assembler()
    user_service = container.user_service()

    paginated_users = await user_service.get_all_users(
        tenant_id=user.tenant_id,
        limit=limit,
        cursor=cursor,
        previous=previous,
        filters=email,
    )

    total_count = await user_service.get_total_count(user.tenant_id, filters=email)

    public_paginated_users = user_assembler.users_to_paginated_response(
        users=paginated_users,
        total_count=total_count,
        limit=limit,
        cursor=cursor,
        previous=previous,
    )

    return public_paginated_users


@router.get(
    "/me/",
    response_model=UserPublic,
    name="Get current user",
    responses=responses.get_responses([404]),
)
async def get_currently_authenticated_user(
    current_user: UserInDB = Depends(
        auth_dependencies.get_current_active_user_with_quota
    ),
):
    truncated_key = (
        current_user.api_key.truncated_key if current_user.api_key is not None else None
    )
    return UserPublic(**current_user.model_dump(), truncated_api_key=truncated_key)


@router.get("/api-keys/", response_model=ApiKey)
async def generate_api_key(
    current_user: UserInDB = Depends(auth_dependencies.get_current_active_user),
    container: Container = Depends(get_container()),
):
    """Generating a new api key will delete the old key.
    Make sure to copy the key since it will only be showed once,
    after which only the truncated key will be shown."""
    service = container.user_service()
    return await service.generate_api_key(current_user.id)


@router.get(
    "/tenant/",
    response_model=TenantPublic,
    name="Get current user tenant",
    responses=responses.get_responses([404]),
)
async def get_current_user_tenant(
    current_user: UserInDB = Depends(auth_dependencies.get_current_active_user),
):
    tenant = current_user.tenant
    return TenantPublic(**tenant.model_dump())


@router.post("/admin/invite/", response_model=UserAdminView, status_code=201)
async def invite_user(
    user_invite: PropUserInvite,
    container: Container = Depends(get_container(with_user=True)),
):
    user_service = container.user_service()

    return await user_service.invite_user(user_invite)


@router.patch("/admin/{id}/", response_model=UserAdminView)
async def update_user(
    id: UUID,
    user_update: PropUserUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    user_service = container.user_service()

    return await user_service.update_user(user_id=id, prop_user_update=user_update)


@router.delete("/admin/{id}/", status_code=204)
async def delete_user(
    id: UUID, container: Container = Depends(get_container(with_user=True))
):
    user_service = container.user_service()

    await user_service.delete_user(user_id=id)


@router.post(
    "/provision/",
    status_code=201,
    responses=responses.get_responses([403]),
)
async def provision_user(
    user_provision: UserProvision,
    container: Container = Depends(get_container()),
):
    user_service = container.user_creation_service()

    await user_service.provision_user(access_token=user_provision.zitadel_token)
