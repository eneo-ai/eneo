from typing import TYPE_CHECKING, Optional
from uuid import UUID

import jwt

from intric.authentication.auth_models import AccessToken
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

if TYPE_CHECKING:
    from intric.users.user import UserInDB


logger = get_logger(__name__)


class UserService:
    def __init__(
        self,
        user_repo: UsersRepository,
        auth_service: AuthService,
        settings_repo: SettingsRepository,
        tenant_repo: TenantRepository,
        info_blob_repo: InfoBlobRepository,
    ):
        self.repo = user_repo
        self.auth_service = auth_service
        self.settings_repo = settings_repo
        self.tenant_repo = tenant_repo
        self.info_blob_repo = info_blob_repo

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

            # Assign default role if configured on tenant
            roles = []
            if tenant.default_role_id:
                roles = [ModelId(id=tenant.default_role_id)]
                logger.info(
                    "OIDC: Assigning default role to new user",
                    extra={
                        "correlation_id": correlation_id,
                        "default_role_id": str(tenant.default_role_id),
                    },
                )
            else:
                logger.info(
                    "OIDC: No default role configured, creating user without role",
                    extra={"correlation_id": correlation_id},
                )

            new_user = UserAdd(
                email=email,
                username=username.lower(),
                tenant_id=tenant_id,
                roles=roles,
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
        access_token = self.auth_service.create_access_token_for_user(user=user_in_db)

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
                access_token=access_token,
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

    async def _get_user_from_api_key(self, api_key: str):
        key = await self.auth_service.get_api_key(api_key)

        if key is None or key.user_id is None:
            return

        return await self.repo.get_user_by_id(key.user_id)

    async def _get_user_from_api_key_or_assistant_api_key(
        self, api_key: str, assistant_id: UUID = None
    ):
        api_key_in_db = await self.auth_service.get_api_key(api_key)

        if api_key_in_db is None:
            raise AuthenticationException("No authenticated user.")
        elif api_key_in_db.user_id is not None:
            return await self.repo.get_user_by_id(api_key_in_db.user_id)
        elif api_key_in_db.assistant_id is not None:
            if assistant_id is not None:
                if assistant_id != api_key_in_db.assistant_id:
                    return

            return await self.repo.get_user_by_assistant_id(api_key_in_db.assistant_id)

        # Else return None

    async def authenticate(
        self,
        token: str | None = None,
        api_key: str | None = None,
        with_quota_used: bool = False,
    ):
        user_in_db = None
        if token is not None:
            user_in_db = await self._get_user_from_token(token)

        elif api_key is not None:
            user_in_db = await self._get_user_from_api_key(api_key)

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
    ):
        user_in_db = None
        if token is not None:
            user_in_db = await self._get_user_from_token(token)

        elif api_key is not None:
            user_in_db = await self._get_user_from_api_key_or_assistant_api_key(
                api_key, assistant_id
            )

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
        roles = [user_invite.role] if user_invite.role else []

        user_add = UserAdd(
            email=user_invite.email,
            tenant_id=tenant_id,
            state=state,
            roles=roles,
        )

        user_in_db = await self.repo.add(user_add)

        settings_upsert = SettingsUpsert(user_id=user_in_db.id)
        await self.settings_repo.add(settings_upsert)

        return user_in_db

    async def update_user(self, user_id: UUID, user_update_public: UserUpdatePublic):
        await self._validate_email(user_update_public)
        await self._validate_username(user_update_public)

        # If roles are being changed, check admin safety
        if user_update_public.roles is not None:
            from intric.roles.permissions import Permission

            current_user = await self.repo.get_user_by_id(user_id)
            if current_user is not None:
                had_admin = Permission.ADMIN in current_user.permissions

                if had_admin:
                    # Fetch the actual new roles from DB to check their permissions
                    new_role_ids = {r.id for r in user_update_public.roles}
                    will_have_admin = False

                    # Check against current roles that are being kept
                    for role in current_user.roles:
                        if role.id in new_role_ids and Permission.ADMIN in role.permissions:
                            will_have_admin = True
                            break

                    # Also check new roles not in current set (role swap A→B)
                    if not will_have_admin:
                        new_ids_not_in_current = new_role_ids - {r.id for r in current_user.roles}
                        if new_ids_not_in_current:
                            new_roles = await self.repo._get_roles(
                                [ModelId(id=rid) for rid in new_ids_not_in_current],
                                current_user.tenant_id,
                            )
                            for role_record in new_roles:
                                if "admin" in (role_record.permissions or []):
                                    will_have_admin = True
                                    break

                    if not will_have_admin:
                        # This user is losing admin — check if others remain
                        admin_count = await self.repo.count_users_with_admin_permission(
                            current_user.tenant_id
                        )
                        # admin_count includes this user, so if only 1, this is the last
                        if admin_count <= 1:
                            raise BadRequestException(
                                "Cannot remove admin permissions from the last admin user. "
                                "At least one user must retain admin access."
                            )

        # If state is being changed to inactive/deleted, check admin safety
        if user_update_public.state in (UserState.INACTIVE, UserState.DELETED):
            from intric.roles.permissions import Permission

            target_user = await self.repo.get_user_by_id(user_id)
            if target_user is not None and Permission.ADMIN in target_user.permissions:
                admin_count = await self.repo.count_users_with_admin_permission(
                    target_user.tenant_id
                )
                if admin_count <= 1:
                    raise BadRequestException(
                        "Cannot deactivate the last admin user. "
                        "At least one user must retain admin access."
                    )

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
        from intric.roles.permissions import Permission

        # Check if deleting this user would leave tenant without admin
        user = await self.repo.get_user_by_id(user_id)
        if user is not None and Permission.ADMIN in user.permissions:
            admin_count = await self.repo.count_users_with_admin_permission(
                user.tenant_id
            )
            if admin_count <= 1:
                raise BadRequestException(
                    "Cannot delete the last admin user. "
                    "At least one user must retain admin access."
                )

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
