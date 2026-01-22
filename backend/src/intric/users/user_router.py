from typing import Optional
from uuid import UUID, uuid4
import json
import secrets
import time
import traceback

import aiohttp
import jwt
from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from intric.authentication import auth_dependencies
from intric.authentication.auth_models import AccessToken, ApiKey, OpenIdConnectLogin
from intric.main import config
from intric.main.exceptions import AuthenticationException
from intric.main.aiohttp_client import aiohttp_client
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.main.models import CursorPaginatedResponse
from intric.main.request_context import set_request_context
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

# Audit logging - module level imports for consistency
from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType

logger = get_logger(__name__)

router = APIRouter()


@router.post(
    "/login/token/",
    response_model=AccessToken,
    name="Login",
    responses=responses.get_responses([401]),
)
async def user_login_with_email_and_password(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(OAuth2PasswordRequestForm),
    container: Container = Depends(get_container()),
) -> AccessToken:
    """OAuth2 Login with comprehensive error handling and logging"""

    # Generate correlation ID for request tracking
    correlation_id = secrets.token_hex(8)
    set_request_context(correlation_id=correlation_id)

    # Capture source IP (proxy-aware)
    source_ip = request.headers.get("x-forwarded-for", request.client.host if request.client else None)
    
    email = form_data.username
    password = form_data.password

    # Log login attempt
    logger.info(
        "Username/password login initiated",
        extra={
            "correlation_id": correlation_id,
            "auth_method": "password",
            "email": email,
            "source_ip": source_ip,
        }
    )

    # Validate input format
    try:
        UserLogin(email=email, password=password)
    except ValidationError as e:
        logger.error(
            "Login failed: validation error",
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "email": email,
                "source_ip": source_ip,
                "errors": e.errors(),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=e.errors(),
            headers={"X-Correlation-ID": correlation_id},
        )

    # Authenticate user
    service = container.user_service()
    
    try:
        result = await service.login(email, password, correlation_id, source_ip)
        
        # Log successful authentication
        logger.info(
            "Username/password login successful",
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "email": email,
                "source_ip": source_ip,
            }
        )
        
        return result
        
    except AuthenticationException as e:
        # Expected authentication failure - use warning level (not error)
        logger.warning(
            "Login failed: invalid credentials",
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "email": email,
                "source_ip": source_ip,
                "error": str(e),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",  # Generic message for security
            headers={"X-Correlation-ID": correlation_id},
        )
        
    except Exception as e:
        # Unexpected system error - use error level with full traceback
        logger.error(
            "Login failed: unexpected error",
            exc_info=True,  # Include stack trace
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "email": email,
                "source_ip": source_ip,
                "error_type": type(e).__name__,
                "error": str(e),
            }
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred during login",
            headers={"X-Correlation-ID": correlation_id},
        )


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

    # Generate API key
    api_key = await service.generate_api_key(current_user.id)

    # Build extra context for API key generation
    extra = {
        "truncated_key": api_key.truncated_key,
        "key_type": "user",
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": current_user.tenant.display_name or current_user.tenant.name if current_user.tenant else None,
    }

    # Audit logging for API key generation
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.API_KEY_GENERATED,
        entity_type=EntityType.API_KEY,
        entity_id=current_user.id,  # Use user ID as entity ID for user API keys
        description=f"Generated new API key for user '{current_user.email}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=current_user,  # Self-action: user is both actor and target
            extra=extra,
        ),
    )

    return api_key


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
    current_user = container.user()
    session = container.session()

    # Create user
    new_user = await user_service.invite_user(user_invite)

    # Build comprehensive extra context for user creation
    extra = {
        "email": new_user.email,
        "username": new_user.username,
        "state": user_invite.state.value if user_invite.state else "invited",
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": current_user.tenant.display_name or current_user.tenant.name if current_user.tenant else None,
    }

    # Fetch predefined role details if role was assigned
    if user_invite.predefined_role:
        from intric.database.tables.roles_table import PredefinedRoles
        import sqlalchemy as sa

        # Query for the predefined role details
        role_query = sa.select(PredefinedRoles).where(PredefinedRoles.id == user_invite.predefined_role)
        role_result = await session.execute(role_query)
        predefined_role = role_result.scalar_one_or_none()

        if predefined_role:
            extra["predefined_role"] = predefined_role.name
            extra["permissions"] = sorted([p.value for p in predefined_role.permissions])

    # Include role/group information if available
    if hasattr(new_user, 'predefined_roles') and new_user.predefined_roles:
        extra["predefined_roles"] = [role.name for role in new_user.predefined_roles]

    if hasattr(new_user, 'roles') and new_user.roles:
        extra["roles"] = [role.name for role in new_user.roles]

    if hasattr(new_user, 'user_groups') and new_user.user_groups:
        extra["user_groups"] = [group.name for group in new_user.user_groups]

    if hasattr(new_user, 'quota_limit') and new_user.quota_limit:
        extra["quota_limit"] = new_user.quota_limit

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.USER_CREATED,
        entity_type=EntityType.USER,
        entity_id=new_user.id,
        description=f"Invited user '{new_user.email}' to tenant",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=new_user,
            extra=extra,
        ),
    )

    return new_user


@router.patch("/admin/{id}/", response_model=UserAdminView)
async def update_user(
    id: UUID,
    user_update: PropUserUpdate,
    container: Container = Depends(get_container(with_user=True)),
):
    user_service = container.user_service()
    current_user = container.user()

    # Get old state for change tracking
    old_user = await user_service.get_user(id)

    # Update user
    updated_user = await user_service.update_user(user_id=id, prop_user_update=user_update)

    # Track comprehensive changes
    changes = {}

    # Basic field changes
    if hasattr(user_update, 'username') and user_update.username and user_update.username != old_user.username:
        changes["username"] = {"old": old_user.username, "new": user_update.username}
    if hasattr(user_update, 'email') and user_update.email and user_update.email != old_user.email:
        changes["email"] = {"old": old_user.email, "new": user_update.email}

    # State change
    if hasattr(user_update, 'state') and user_update.state:
        old_state = old_user.state.value if hasattr(old_user, 'state') else None
        if old_state and user_update.state.value != old_state:
            changes["state"] = {"old": old_state, "new": user_update.state.value}

    # Predefined role change (PropUserUpdate has single predefined_role)
    if hasattr(user_update, 'predefined_role') and user_update.predefined_role:
        old_roles = []
        if hasattr(old_user, 'predefined_roles') and old_user.predefined_roles:
            old_roles = [role.name for role in old_user.predefined_roles]

        # After update, get the new roles
        new_roles = []
        if hasattr(updated_user, 'predefined_roles') and updated_user.predefined_roles:
            new_roles = [role.name for role in updated_user.predefined_roles]

        if old_roles != new_roles:
            changes["predefined_roles"] = {"old": old_roles, "new": new_roles}

    # Track permission changes (computed from role changes)
    old_permissions = sorted([p.value for p in old_user.permissions]) if hasattr(old_user, 'permissions') else []
    new_permissions = sorted([p.value for p in updated_user.permissions]) if hasattr(updated_user, 'permissions') else []

    if old_permissions != new_permissions:
        added_perms = list(set(new_permissions) - set(old_permissions))
        removed_perms = list(set(old_permissions) - set(new_permissions))
        if added_perms or removed_perms:
            changes["permissions"] = {}
            if added_perms:
                changes["permissions"]["added"] = sorted(added_perms)
            if removed_perms:
                changes["permissions"]["removed"] = sorted(removed_perms)

    # Build extra context with current user state
    extra = {
        "email": updated_user.email,
        "username": updated_user.username,
        "state": updated_user.state.value if hasattr(updated_user, 'state') else None,
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": current_user.tenant.display_name or current_user.tenant.name if current_user.tenant else None,
    }

    # Include current role/group information
    if hasattr(updated_user, 'predefined_roles') and updated_user.predefined_roles:
        extra["predefined_roles"] = [role.name for role in updated_user.predefined_roles]

    if hasattr(updated_user, 'roles') and updated_user.roles:
        extra["roles"] = [role.name for role in updated_user.roles]

    if hasattr(updated_user, 'user_groups') and updated_user.user_groups:
        extra["user_groups"] = [group.name for group in updated_user.user_groups]

    if hasattr(updated_user, 'quota_limit') and updated_user.quota_limit:
        extra["quota_limit"] = updated_user.quota_limit

    # Build change summary for description
    change_summary = list(changes.keys()) if changes else []

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.USER_UPDATED,
        entity_type=EntityType.USER,
        entity_id=id,
        description=f"Updated user '{updated_user.email}'" + (f" ({', '.join(change_summary)})" if change_summary else ""),
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=updated_user,
            changes=changes if changes else None,
            extra=extra,
        ),
    )

    return updated_user


@router.delete("/admin/{id}/", status_code=204)
async def delete_user(
    id: UUID, container: Container = Depends(get_container(with_user=True))
):
    user_service = container.user_service()
    current_user = container.user()

    # Get user details BEFORE deletion (snapshot pattern)
    user_to_delete = await user_service.get_user(id)

    # Build extra context capturing what was deleted
    extra = {
        "email": user_to_delete.email,
        "username": user_to_delete.username,
        "state": user_to_delete.state.value if hasattr(user_to_delete, 'state') else None,
        "tenant_id": str(current_user.tenant_id),
        "tenant_name": current_user.tenant.display_name or current_user.tenant.name if current_user.tenant else None,
        "created_at": user_to_delete.created_at.isoformat() if hasattr(user_to_delete, 'created_at') and user_to_delete.created_at else None,
    }

    # Include full context of what was deleted
    if hasattr(user_to_delete, 'predefined_roles') and user_to_delete.predefined_roles:
        extra["predefined_roles"] = [role.name for role in user_to_delete.predefined_roles]

    if hasattr(user_to_delete, 'roles') and user_to_delete.roles:
        extra["roles"] = [role.name for role in user_to_delete.roles]

    if hasattr(user_to_delete, 'permissions'):
        extra["permissions"] = sorted([p.value for p in user_to_delete.permissions])

    if hasattr(user_to_delete, 'user_groups') and user_to_delete.user_groups:
        extra["user_groups"] = [group.name for group in user_to_delete.user_groups]

    if hasattr(user_to_delete, 'quota_limit') and user_to_delete.quota_limit:
        extra["quota_limit"] = user_to_delete.quota_limit

    # Delete user
    await user_service.delete_user(user_id=id)

    # Audit logging
    audit_service = container.audit_service()
    await audit_service.log_async(
        tenant_id=current_user.tenant_id,
        actor_id=current_user.id,
        action=ActionType.USER_DELETED,
        entity_type=EntityType.USER,
        entity_id=id,
        description=f"Deleted user '{user_to_delete.email}'",
        metadata=AuditMetadata.standard(
            actor=current_user,
            target=user_to_delete,
            extra=extra,
        ),
    )


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
