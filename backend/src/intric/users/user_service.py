from datetime import datetime, timezone
import random
from typing import TYPE_CHECKING, Optional, cast
from uuid import UUID

import jwt
import sqlalchemy as sa
from starlette.requests import Request

from intric.audit.application.audit_metadata import AuditMetadata
from intric.audit.application.audit_service import AuditService
from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.allowed_origins.allowed_origin_repo import AllowedOriginRepository
from intric.authentication.api_key_rate_limiter import ApiKeyRateLimiter
from intric.authentication.api_key_v2_repo import ApiKeysV2Repository
from intric.authentication.api_key_policy import ApiKeyPolicyService
from intric.authentication.api_key_resolver import (
    ApiKeyAuthResolver,
    ApiKeyValidationError,
)
from intric.authentication.auth_models import (
    AccessToken,
    ApiKeyPermission,
    ApiKeyScopeType,
    ApiKeyV2InDB,
)
from intric.authentication.auth_service import AuthService
from intric.info_blobs.info_blob_repo import InfoBlobRepository
from intric.main.config import get_settings
from intric.main.exceptions import (
    AuthenticationException,
    BadRequestException,
    NotFoundException,
    TenantSuspendedException,
    UniqueUserException,
    UserInactiveException,
)
from intric.main.logging import get_logger
from intric.main.models import ModelId
from intric.predefined_roles.predefined_role import PredefinedRoleName
from intric.predefined_roles.predefined_roles_repo import PredefinedRolesRepository
from intric.settings.settings import SettingsUpsert
from intric.settings.settings_repo import SettingsRepository
from intric.tenants.tenant import TenantState
from intric.tenants.tenant_repo import TenantRepository
from intric.users.user import (
    PropUserInvite,
    UserAdd,
    UserAddSuperAdmin,
    UserBase,
    UserState,
    UserUpdate,
    UserUpdatePublic,
)
from intric.users.user_repo import UsersRepository
from intric.database.tables.assistant_table import Assistants
from intric.database.tables.users_table import Users

if TYPE_CHECKING:
    from intric.users.user import UserInDB
    from intric.spaces.space_service import SpaceService


logger = get_logger(__name__)


class UserService:
    def __init__(
        self,
        user_repo: UsersRepository,
        auth_service: AuthService,
        api_key_auth_resolver: ApiKeyAuthResolver,
        api_key_v2_repo: ApiKeysV2Repository,
        allowed_origin_repo: AllowedOriginRepository,
        audit_service: Optional[AuditService],
        settings_repo: SettingsRepository,
        tenant_repo: TenantRepository,
        info_blob_repo: InfoBlobRepository,
        space_service: Optional["SpaceService"] = None,
        predefined_roles_repo: Optional[PredefinedRolesRepository] = None,
        api_key_rate_limiter: Optional[ApiKeyRateLimiter] = None,
    ):
        self.repo = user_repo
        self.auth_service = auth_service
        self.api_key_auth_resolver = api_key_auth_resolver
        self.api_key_v2_repo = api_key_v2_repo
        self.allowed_origin_repo = allowed_origin_repo
        self.space_service = space_service
        self.audit_service = audit_service
        self.settings_repo = settings_repo
        self.tenant_repo = tenant_repo
        self.predefined_roles_repo = predefined_roles_repo
        self.info_blob_repo = info_blob_repo
        self.api_key_rate_limiter = api_key_rate_limiter

    async def _validate_email(self, user: UserBase):
        if (
            await self.repo.get_user_by_email(email=user.email, with_deleted=True)
            is not None
        ):
            raise UniqueUserException("That email is already taken.")

    async def _validate_username(self, user: UserBase):
        if (
            user.username is not None
            and await self.repo.get_user_by_username(
                username=user.username, with_deleted=True
            )
            is not None
        ):
            raise UniqueUserException("That username is already taken.")

    async def login(
        self,
        email: str,
        password: str,
        correlation_id: str = None,
        source_ip: str = None,
    ):
        """
        Authenticate user with username/password.

        Implements timing attack mitigation by always performing password verification,
        even when user is not found (using dummy hash).

        Args:
            email: User email address
            password: Plaintext password
            correlation_id: Request correlation ID for logging
            source_ip: Client IP address for security logging

        Returns:
            AccessToken with JWT bearer token

        Raises:
            AuthenticationException: On authentication failure (generic message)
        """
        correlation_id = correlation_id or "no-correlation-id"

        # Log user lookup
        logger.debug(
            "Looking up user for authentication",
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "email": email,
                "source_ip": source_ip,
            },
        )

        user = await self.repo.get_user_by_email(email)

        # Timing attack mitigation: Always perform password verification
        # If user not found or password not set, verify against dummy hash
        # This ensures constant execution time regardless of user existence
        password_hash = (
            user.password if (user and user.password) else self.auth_service.DUMMY_HASH
        )

        is_valid_password = self.auth_service.verify_password(password, password_hash)

        # Check all failure conditions and log appropriately
        if not user:
            logger.warning(
                "Login failed: user not found",
                extra={
                    "correlation_id": correlation_id,
                    "auth_method": "password",
                    "email": email,
                    "source_ip": source_ip,
                },
            )
            raise AuthenticationException(
                "Invalid credentials"
            )  # Generic message for security

        if not user.password:
            logger.warning(
                "Login failed: password authentication not enabled",
                extra={
                    "correlation_id": correlation_id,
                    "auth_method": "password",
                    "user_id": str(user.id),
                    "tenant_id": str(user.tenant_id),
                    "tenant_name": user.tenant.name,
                    "email": email,
                    "source_ip": source_ip,
                },
            )
            raise AuthenticationException(
                "Invalid credentials"
            )  # Generic message for security

        if not is_valid_password:
            logger.warning(
                "Login failed: invalid password",
                extra={
                    "correlation_id": correlation_id,
                    "auth_method": "password",
                    "user_id": str(user.id),
                    "tenant_id": str(user.tenant_id),
                    "tenant_name": user.tenant.name,
                    "email": email,
                    "source_ip": source_ip,
                },
            )
            raise AuthenticationException(
                "Invalid credentials"
            )  # Generic message for security

        # Check if the user or tenant state prevents login
        await self._check_user_and_tenant_state(user)

        # Log successful authentication
        logger.info(
            "User authenticated successfully",
            extra={
                "correlation_id": correlation_id,
                "auth_method": "password",
                "user_id": str(user.id),
                "email": user.email,
                "tenant_id": str(user.tenant_id),
                "tenant_name": user.tenant.name,
                "source_ip": source_ip,
            },
        )

        return AccessToken(
            access_token=self.auth_service.create_access_token_for_user(user=user),
            token_type="bearer",
        )

    async def login_with_mobilityguard(
        self,
        id_token: str,
        access_token: str,
        key: jwt.PyJWK,
        signing_algos: list[str],
        correlation_id: str = None,
    ):
        # MIT License
        was_federated = False
        correlation_id = correlation_id or "no-correlation-id"

        logger.debug(
            "Starting OIDC user service login",
            extra={
                "correlation_id": correlation_id,
                "client_id": get_settings().oidc_client_id,
                "signing_algos": signing_algos,
                "has_tenant_id": bool(get_settings().oidc_tenant_id),
            },
        )

        try:
            username, email = self.auth_service.get_username_and_email_from_openid_jwt(
                id_token=id_token,
                access_token=access_token,
                key=key.key,
                signing_algos=signing_algos,
                client_id=get_settings().oidc_client_id,
                options={"verify_iat": False},
                correlation_id=correlation_id,
            )

            logger.info(
                "Successfully extracted user info from OIDC JWT",
                extra={
                    "correlation_id": correlation_id,
                    "username": username,
                    "email": email,
                },
            )

        except jwt.ExpiredSignatureError as e:
            logger.error(
                "JWT token has expired",
                extra={
                    "correlation_id": correlation_id,
                    "error": str(e),
                },
            )
            raise AuthenticationException("Token has expired")
        except jwt.InvalidAudienceError as e:
            logger.error(
                "JWT audience validation failed",
                extra={
                    "correlation_id": correlation_id,
                    "error": str(e),
                    "expected_audience": get_settings().oidc_client_id,
                },
            )
            raise AuthenticationException("Invalid token audience")
        except jwt.InvalidTokenError as e:
            logger.error(
                "JWT token validation failed",
                extra={
                    "correlation_id": correlation_id,
                    "error_type": type(e).__name__,
                    "error": str(e),
                },
            )
            raise AuthenticationException("Invalid token")
        except Exception as e:
            logger.error(
                "Failed to extract user info from JWT",
                extra={
                    "correlation_id": correlation_id,
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "client_id": get_settings().oidc_client_id,
                },
            )
            raise AuthenticationException("Failed to validate token")

        # Look up user in database
        logger.info(
            f"OIDC: Looking up user by email: {email}",
            extra={"correlation_id": correlation_id},
        )

        user_in_db = await self.repo.get_user_by_email(email)

        if user_in_db is None:
            logger.info(
                "OIDC: User not found in database, attempting to create new user",
                extra={
                    "correlation_id": correlation_id,
                    "email": email,
                    "username": username,
                },
            )

            # If a the user does not exist in our database, create it

            # Check if tenant ID is configured
            if not get_settings().oidc_tenant_id:
                logger.error(
                    "Cannot create new user: OIDC tenant ID not configured (OIDC_TENANT_ID or deprecated MOBILITYGUARD_TENANT_ID)",
                    extra={
                        "correlation_id": correlation_id,
                        "email": email,
                        "username": username,
                    },
                )
                raise AuthenticationException(
                    "System configuration error: Cannot create new users via OIDC. "
                    "Please contact your administrator."
                )

            try:
                # Will only work on one tenant in the instance for now
                tenant_id = UUID(get_settings().oidc_tenant_id)

                logger.info(
                    f"Creating user with tenant ID: {tenant_id}",
                    extra={"correlation_id": correlation_id},
                )

            except ValueError as e:
                logger.error(
                    f"Invalid OIDC_TENANT_ID format: {get_settings().oidc_tenant_id}",
                    extra={
                        "correlation_id": correlation_id,
                        "error": str(e),
                    },
                )
                raise AuthenticationException(
                    "System configuration error: Invalid tenant ID format"
                )

            # Verify tenant exists
            tenant = await self.tenant_repo.get(tenant_id)
            if tenant is None:
                logger.error(
                    f"Tenant not found: {tenant_id}",
                    extra={
                        "correlation_id": correlation_id,
                        "tenant_id": str(tenant_id),
                    },
                )
                raise AuthenticationException(
                    "System configuration error: Tenant does not exist"
                )

            # The hack continues
            if self.predefined_roles_repo is None:
                logger.error(
                    "Predefined roles repository is not configured",
                    extra={"correlation_id": correlation_id},
                )
                raise AuthenticationException(
                    "System configuration error: Predefined roles repository not configured"
                )

            user_role = await self.predefined_roles_repo.get_predefined_role_by_name(
                PredefinedRoleName.USER
            )

            if user_role is None:
                logger.error(
                    "Predefined USER role not found in database",
                    extra={"correlation_id": correlation_id},
                )
                raise AuthenticationException(
                    "System configuration error: User role not found"
                )

            new_user = UserAdd(
                email=email,
                username=username.lower(),
                tenant_id=tenant_id,
                predefined_roles=[ModelId(id=user_role.id)],
                state=UserState.ACTIVE,
            )

            try:
                user_in_db = await self.repo.add(new_user)
                was_federated = True

                logger.info(
                    "Successfully created new user via OIDC federation",
                    extra={
                        "correlation_id": correlation_id,
                        "user_id": str(user_in_db.id),
                        "email": email,
                        "username": username.lower(),
                        "tenant_id": str(tenant_id),
                    },
                )

            except Exception as e:
                logger.error(
                    "Failed to create new user in database",
                    extra={
                        "correlation_id": correlation_id,
                        "email": email,
                        "username": username,
                        "error_type": type(e).__name__,
                        "error": str(e),
                    },
                )
                raise AuthenticationException("Failed to create user account")

        else:
            logger.info(
                "OIDC: User found in database, checking user and tenant state",
                extra={
                    "correlation_id": correlation_id,
                    "user_id": str(user_in_db.id),
                    "email": user_in_db.email,
                    "tenant_id": str(user_in_db.tenant_id),
                    "user_state": user_in_db.state,
                },
            )

            try:
                await self._check_user_and_tenant_state(user_in_db, correlation_id)
            except (UserInactiveException, TenantSuspendedException) as e:
                logger.warning(
                    "User or tenant state check failed",
                    extra={
                        "correlation_id": correlation_id,
                        "user_id": str(user_in_db.id),
                        "error_type": type(e).__name__,
                        "error": str(e),
                    },
                )
                raise

        # Create access token
        issued_token = self.auth_service.create_access_token_for_user(user=user_in_db)
        if issued_token is None:
            raise AuthenticationException("Could not create access token.")
        issued_token = cast(str, issued_token)

        logger.info(
            "OIDC login completed successfully",
            extra={
                "correlation_id": correlation_id,
                "user_id": str(user_in_db.id),
                "email": user_in_db.email,
                "was_federated": was_federated,
            },
        )

        return (
            AccessToken(
                access_token=issued_token,
                token_type="bearer",
            ),
            was_federated,
            user_in_db,
        )

    async def register(self, new_user: UserAddSuperAdmin):
        await self._validate_email(new_user)
        await self._validate_username(new_user)

        tenant = await self.tenant_repo.get(new_user.tenant_id)
        if tenant is None:
            raise BadRequestException(f"Tenant {new_user.tenant_id} does not exist")

        if new_user.password is not None:
            salt, hashed_pass = self.auth_service.create_salt_and_hashed_password(
                new_user.password
            )
        else:
            salt = None
            hashed_pass = None

        user_add = UserAdd(
            **new_user.model_dump(exclude={"password"}),
            password=hashed_pass,
            salt=salt,
            state=UserState.ACTIVE,
        )

        user_in_db = await self.repo.add(user_add)

        settings_upsert = SettingsUpsert(user_id=user_in_db.id)
        await self.settings_repo.add(settings_upsert)

        api_key = await self.generate_api_key(user_id=user_in_db.id)

        access_token = AccessToken(
            access_token=self.auth_service.create_access_token_for_user(
                user=user_in_db
            ),
            token_type="bearer",
        )

        return user_in_db, access_token, api_key

    async def _get_user_from_token(self, token: str):
        username = self.auth_service.get_username_from_token(
            token, get_settings().jwt_secret
        )
        return await self.repo.get_user_by_username(username)

    async def _resolve_api_key(
        self,
        api_key: str,
        request: Request | None = None,
        expected_tenant_id: UUID | None = None,
    ) -> tuple["UserInDB", ApiKeyV2InDB]:
        resolved = await self.api_key_auth_resolver.resolve(
            api_key, expected_tenant_id=expected_tenant_id
        )
        user = await self.repo.get_user_by_id(resolved.key.owner_user_id)
        if user is None:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_api_key",
                message="API key owner not found.",
            )
        if user.tenant_id != resolved.key.tenant_id:
            raise ApiKeyValidationError(
                status_code=401,
                code="invalid_api_key",
                message="API key tenant mismatch.",
            )

        policy_service = ApiKeyPolicyService(
            allowed_origin_repo=self.allowed_origin_repo,
            space_service=self.space_service,
            user=None,
        )
        origin = request.headers.get("origin") if request else None
        client_ip = policy_service.resolve_client_ip(request) if request else None
        try:
            await policy_service.enforce_guardrails(
                key=resolved.key,
                origin=origin,
                client_ip=client_ip,
            )
            if self.api_key_rate_limiter is not None:
                await self.api_key_rate_limiter.enforce(resolved.key)
        except ApiKeyValidationError as exc:
            await self._log_api_key_auth_failed(user, resolved.key, exc, request)
            raise

        settings = get_settings()
        await self.api_key_v2_repo.update_last_used_at(
            key_id=resolved.key.id,
            tenant_id=resolved.key.tenant_id,
            last_used_at=datetime.now(timezone.utc),
            min_interval_seconds=settings.api_key_last_used_min_interval_seconds,
        )

        if request is not None:
            request.state.api_key = resolved.key
            request.state.api_key_permission = resolved.key.permission
            request.state.api_key_scope_type = resolved.key.scope_type
            request.state.api_key_scope_id = resolved.key.scope_id

        await self._maybe_log_api_key_used(user, resolved.key, request)

        logger.info(
            "API key authenticated",
            extra={
                "tenant_id": str(resolved.key.tenant_id),
                "user_id": str(user.id),
                "api_key_id": str(resolved.key.id),
                "scope_type": resolved.key.scope_type,
                "scope_id": str(resolved.key.scope_id)
                if resolved.key.scope_id
                else None,
                "permission": resolved.key.permission,
                "key_type": resolved.key.key_type,
            },
        )

        return user, resolved.key

    async def _get_assistant_scope_context(
        self, assistant_id: UUID
    ) -> tuple[UUID, UUID]:
        stmt = (
            sa.select(Assistants.space_id, Users.tenant_id)
            .join(Users, Users.id == Assistants.user_id)
            .where(Assistants.id == assistant_id)
            .limit(1)
        )
        record = await self.repo.session.execute(stmt)
        row = record.first()
        if row is None or row.space_id is None:
            raise ApiKeyValidationError(
                status_code=404,
                code="resource_not_found",
                message="Assistant not found.",
            )
        return row.space_id, row.tenant_id

    def _permission_allows(
        self, actual: ApiKeyPermission, required: ApiKeyPermission
    ) -> bool:
        ordering = {
            ApiKeyPermission.READ: 0,
            ApiKeyPermission.WRITE: 1,
            ApiKeyPermission.ADMIN: 2,
        }
        return ordering[actual] >= ordering[required]

    def _require_api_key_permission(
        self, *, key: ApiKeyV2InDB, required: ApiKeyPermission
    ) -> None:
        actual = ApiKeyPermission(key.permission)
        if not self._permission_allows(actual, required):
            raise ApiKeyValidationError(
                status_code=403,
                code="insufficient_permission",
                message="API key does not have required permission.",
            )

    async def _require_api_key_scope_for_assistant(
        self,
        *,
        key: ApiKeyV2InDB,
        assistant_id: UUID,
        assistant_space_id: UUID | None = None,
        assistant_tenant_id: UUID | None = None,
    ) -> None:
        scope_type = ApiKeyScopeType(key.scope_type)
        if scope_type == ApiKeyScopeType.ASSISTANT:
            if key.scope_id != assistant_id:
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="API key is not scoped to this assistant.",
                )
            return

        if scope_type in (ApiKeyScopeType.SPACE, ApiKeyScopeType.TENANT):
            if assistant_space_id is None or assistant_tenant_id is None:
                (
                    assistant_space_id,
                    assistant_tenant_id,
                ) = await self._get_assistant_scope_context(assistant_id)
            if (
                scope_type == ApiKeyScopeType.SPACE
                and key.scope_id != assistant_space_id
            ):
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="API key is not scoped to this assistant's space.",
                )
            if (
                scope_type == ApiKeyScopeType.TENANT
                and key.tenant_id != assistant_tenant_id
            ):
                raise ApiKeyValidationError(
                    status_code=403,
                    code="insufficient_permission",
                    message="API key is not scoped to this tenant.",
                )
            return

        raise ApiKeyValidationError(
            status_code=403,
            code="insufficient_permission",
            message="API key scope does not allow assistant access.",
        )

    async def _maybe_log_api_key_used(
        self,
        user: "UserInDB",
        key: ApiKeyV2InDB,
        request: Request | None,
    ) -> None:
        if self.audit_service is None:
            return
        sample_rate = get_settings().api_key_used_audit_sample_rate
        if sample_rate <= 0 or random.random() > sample_rate:
            return

        extra = {
            "scope_type": key.scope_type,
            "scope_id": str(key.scope_id) if key.scope_id else None,
            "permission": key.permission,
            "key_type": key.key_type,
        }
        if request is not None:
            extra["method"] = request.method
            extra["path"] = request.url.path
            extra["origin"] = request.headers.get("origin")

        await self.audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.API_KEY_USED,
            entity_type=EntityType.API_KEY,
            entity_id=key.id,
            description="API key used",
            metadata=AuditMetadata.standard(actor=user, target=key, extra=extra),
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )

    async def _log_api_key_auth_failed(
        self,
        user: "UserInDB",
        key: ApiKeyV2InDB,
        exc: ApiKeyValidationError,
        request: Request | None,
    ) -> None:
        if self.audit_service is None:
            return

        extra = {
            "code": exc.code,
            "error_message": exc.message,
            "scope_type": key.scope_type,
            "scope_id": str(key.scope_id) if key.scope_id else None,
            "permission": key.permission,
            "key_type": key.key_type,
        }
        if request is not None:
            extra["method"] = request.method
            extra["path"] = request.url.path
            extra["origin"] = request.headers.get("origin")

        await self.audit_service.log_async(
            tenant_id=user.tenant_id,
            actor_id=user.id,
            action=ActionType.API_KEY_AUTH_FAILED,
            entity_type=EntityType.API_KEY,
            entity_id=key.id,
            description="API key authentication failed",
            metadata=AuditMetadata.standard(actor=user, target=key, extra=extra),
            ip_address=request.client.host if request and request.client else None,
            user_agent=request.headers.get("user-agent") if request else None,
        )

        logger.warning(
            "API key authentication failed",
            extra={
                "tenant_id": str(user.tenant_id),
                "user_id": str(user.id),
                "api_key_id": str(key.id),
                "code": exc.code,
                "error_message": exc.message,
            },
        )

    async def authenticate(
        self,
        token: str | None = None,
        api_key: str | None = None,
        with_quota_used: bool = False,
        request: Request | None = None,
    ):
        user_in_db = None
        if token is not None:
            user_in_db = await self._get_user_from_token(token)

        elif api_key is not None:
            user_in_db, _ = await self._resolve_api_key(api_key, request=request)

        if user_in_db is None:
            raise AuthenticationException("No authenticated user.")

        await self._check_user_and_tenant_state(user_in_db, correlation_id="api-auth")

        if with_quota_used:
            user_in_db.quota_used = await self.info_blob_repo.get_total_size_of_user(
                user_id=user_in_db.id
            )

        return user_in_db

    async def _check_user_and_tenant_state(
        self, user_in_db, correlation_id: str = None
    ):
        """
        Check if the user or their tenant has restrictions.
        Raises appropriate exceptions if user is inactive or tenant is suspended.
        """
        correlation_id = correlation_id or "no-correlation-id"

        logger.debug(
            "Checking user and tenant state",
            extra={
                "correlation_id": correlation_id,
                "user_id": str(user_in_db.id),
                "user_email": user_in_db.email,
                "user_state": user_in_db.state,
                "tenant_id": str(user_in_db.tenant_id),
                "tenant_state": user_in_db.tenant.state
                if user_in_db.tenant
                else "No tenant",
                "tenant_name": user_in_db.tenant.name
                if user_in_db.tenant
                else "No tenant",
            },
        )

        if user_in_db.state == UserState.INACTIVE:
            logger.error(
                "User is INACTIVE, blocking login",
                extra={
                    "correlation_id": correlation_id,
                    "user_id": str(user_in_db.id),
                    "user_email": user_in_db.email,
                    "user_state": user_in_db.state,
                },
            )
            raise UserInactiveException()

        # Check if the tenant is suspended
        if user_in_db.tenant and user_in_db.tenant.state == TenantState.SUSPENDED.value:
            logger.error(
                "Tenant is SUSPENDED, blocking login",
                extra={
                    "correlation_id": correlation_id,
                    "user_id": str(user_in_db.id),
                    "tenant_id": str(user_in_db.tenant_id),
                    "tenant_state": user_in_db.tenant.state,
                    "tenant_name": user_in_db.tenant.name,
                },
            )
            raise TenantSuspendedException()

        logger.debug(
            "User and tenant state check passed",
            extra={
                "correlation_id": correlation_id,
                "user_id": str(user_in_db.id),
            },
        )

    async def authenticate_with_assistant_api_key(
        self,
        api_key: str,
        token: str,
        assistant_id: UUID = None,
        request: Request | None = None,
    ):
        user_in_db = None
        assistant_space_id: UUID | None = None
        assistant_tenant_id: UUID | None = None
        if token is not None:
            user_in_db = await self._get_user_from_token(token)

        elif api_key is not None:
            if assistant_id is not None:
                (
                    assistant_space_id,
                    assistant_tenant_id,
                ) = await self._get_assistant_scope_context(assistant_id)
            user_in_db, key = await self._resolve_api_key(
                api_key,
                request=request,
                expected_tenant_id=assistant_tenant_id,
            )
            try:
                if assistant_id is not None:
                    await self._require_api_key_scope_for_assistant(
                        key=key,
                        assistant_id=assistant_id,
                        assistant_space_id=assistant_space_id,
                        assistant_tenant_id=assistant_tenant_id,
                    )
                self._require_api_key_permission(
                    key=key, required=ApiKeyPermission.READ
                )
            except ApiKeyValidationError as exc:
                await self._log_api_key_auth_failed(user_in_db, key, exc, request)
                raise

        if user_in_db is None:
            raise AuthenticationException("No authenticated user.")

        await self._check_user_and_tenant_state(user_in_db, correlation_id="api-auth")

        return user_in_db

    async def update_used_tokens(self, user_id: UUID, tokens_to_add: int):
        user_in_db = await self.repo.get_user_by_id(user_id)
        new_used_tokens = user_in_db.used_tokens + tokens_to_add
        user_update = UserUpdate(id=user_in_db.id, used_tokens=new_used_tokens)
        await self.repo.update(user_update)

    async def get_total_count(
        self, tentant_id: Optional[UUID] = None, filters: Optional[str] = None
    ) -> int:
        count = await self.repo.get_total_count(tenant_id=tentant_id, filters=filters)
        return count or 0

    async def get_all_users(
        self,
        tenant_id: UUID = None,
        cursor: Optional[str] = None,
        previous: bool = False,
        limit: Optional[int] = None,
        filters: Optional[str] = None,
    ) -> list["UserInDB"]:
        """
        Retrieves a paginated list of users for a specific tenant,
        with optional filtering and cursor-based pagination.
        """

        return await self.repo.get_all_users(
            tenant_id=tenant_id,
            limit=limit,
            cursor=cursor,
            previous=previous,
            filters=filters,
        )

    async def invite_user(self, user_invite: PropUserInvite, tenant_id: UUID):
        await self._validate_email(user_invite)
        username = getattr(user_invite, "username", None)
        if username is not None:
            await self._validate_username(user_invite)

        tenant = await self.tenant_repo.get(tenant_id)
        if tenant is None:
            raise BadRequestException(f"Tenant {tenant_id} does not exist")

        state = user_invite.state or UserState.INVITED
        predefined_roles = (
            [user_invite.predefined_role] if user_invite.predefined_role else []
        )

        user_add = UserAdd(
            email=user_invite.email,
            tenant_id=tenant_id,
            state=state,
            predefined_roles=predefined_roles,
        )

        user_in_db = await self.repo.add(user_add)

        settings_upsert = SettingsUpsert(user_id=user_in_db.id)
        await self.settings_repo.add(settings_upsert)

        return user_in_db

    async def update_user(self, user_id: UUID, user_update_public: UserUpdatePublic):
        await self._validate_email(user_update_public)
        await self._validate_username(user_update_public)

        user_update = UserUpdate(
            id=user_id, **user_update_public.model_dump(exclude_unset=True)
        )

        if user_update_public.password is not None:
            salt, hashed_pass = self.auth_service.create_salt_and_hashed_password(
                user_update_public.password
            )
            user_update.salt = salt
            user_update.password = hashed_pass

        user_in_db = await self.repo.update(
            UserUpdate(**user_update.model_dump(exclude_unset=True))
        )

        if user_in_db is None:
            raise NotFoundException("No such user")

        return user_in_db

    async def delete_user(self, user_id: UUID):
        deleted_user = await self.repo.delete(user_id)

        if deleted_user is None:
            raise NotFoundException("No such user exists.")

        return True

    async def get_user(self, user_id: UUID):
        user = await self.repo.get_user_by_id(user_id)

        if user is None:
            raise NotFoundException("No such user exists.")

        user.quota_used = await self.info_blob_repo.get_total_size_of_user(
            user_id=user.id
        )
        return user

    async def generate_api_key(self, user_id: UUID):
        return await self.auth_service.create_user_api_key("inp", user_id=user_id)
