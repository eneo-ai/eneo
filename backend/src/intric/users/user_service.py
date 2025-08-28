from typing import TYPE_CHECKING, Optional
from uuid import UUID

import jwt

from intric.authentication.auth_models import AccessToken
from intric.authentication.auth_service import AuthService
from intric.info_blobs.info_blob_repo import InfoBlobRepository
from intric.main.config import SETTINGS
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
        predefined_roles_repo: Optional[PredefinedRolesRepository] = None,
    ):
        self.repo = user_repo
        self.auth_service = auth_service
        self.settings_repo = settings_repo
        self.tenant_repo = tenant_repo
        self.predefined_roles_repo = predefined_roles_repo
        self.info_blob_repo = info_blob_repo

    async def _validate_email(self, user: UserBase):
        if await self.repo.get_user_by_email(email=user.email, with_deleted=True) is not None:
            raise UniqueUserException("That email is already taken.")

    async def _validate_username(self, user: UserBase):
        if (
            user.username is not None
            and await self.repo.get_user_by_username(username=user.username, with_deleted=True)
            is not None
        ):
            raise UniqueUserException("That username is already taken.")

    async def login(self, email: str, password: str):
        user = await self.repo.get_user_by_email(email)

        if user is None:
            raise AuthenticationException("No such user")

        if user.password is None:
            raise AuthenticationException("User has not enabled username and password login")

        if not self.auth_service.verify_password(password, user.password):
            raise AuthenticationException("Wrong password")

        # Check if the user or tenant state prevents login
        await self._check_user_and_tenant_state(user)

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
    ):
        # MIT License
        was_federated = False

        try:
            username, email = self.auth_service.get_username_and_email_from_openid_jwt(
                id_token=id_token,
                access_token=access_token,
                key=key.key,
                signing_algos=signing_algos,
                client_id=SETTINGS.mobilityguard_client_id,
                options={"verify_iat": False},
            )
        except Exception:
            raise AuthenticationException()

        user_in_db = await self.repo.get_user_by_email(email)

        if user_in_db is None:
            # If a the user does not exist in our database, create it

            # Will only work on one tenant in the instance for now
            tenant_id = UUID(SETTINGS.mobilityguard_tenant_id)

            # The hack continues
            user_role = await self.predefined_roles_repo.get_predefined_role_by_name(
                PredefinedRoleName.USER
            )

            assert user_role is not None

            new_user = UserAdd(
                email=email,
                username=username.lower(),
                tenant_id=tenant_id,
                predefined_roles=[ModelId(id=user_role.id)],
                state=UserState.ACTIVE,
            )

            user_in_db = await self.repo.add(new_user)
            was_federated = True

        else:
            await self._check_user_and_tenant_state(user_in_db)

        return (
            AccessToken(
                access_token=self.auth_service.create_access_token_for_user(user=user_in_db),
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
            salt, hashed_pass = self.auth_service.create_salt_and_hashed_password(new_user.password)
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
            access_token=self.auth_service.create_access_token_for_user(user=user_in_db),
            token_type="bearer",
        )

        return user_in_db, access_token, api_key

    async def _get_user_from_token(self, token: str):
        username = self.auth_service.get_username_from_token(token, SETTINGS.jwt_secret)
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

        await self._check_user_and_tenant_state(user_in_db)

        if with_quota_used:
            user_in_db.quota_used = await self.info_blob_repo.get_total_size_of_user(
                user_id=user_in_db.id
            )

        return user_in_db

    async def _check_user_and_tenant_state(self, user_in_db):
        """
        Check if the user or their tenant has restrictions.
        Raises appropriate exceptions if user is inactive or tenant is suspended.
        """
        if user_in_db.state == UserState.INACTIVE:
            raise UserInactiveException()

        # Check if the tenant is suspended
        if user_in_db.tenant.state == TenantState.SUSPENDED.value:
            raise TenantSuspendedException()

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

        await self._check_user_and_tenant_state(user_in_db)

        return user_in_db

    async def update_used_tokens(self, user_id: UUID, tokens_to_add: int):
        user_in_db = await self.repo.get_user_by_id(user_id)
        new_used_tokens = user_in_db.used_tokens + tokens_to_add
        user_update = UserUpdate(id=user_in_db.id, used_tokens=new_used_tokens)
        await self.repo.update(user_update)

    async def get_total_count(
        self, tentant_id: Optional[UUID] = None, filters: Optional[str] = None
    ) -> int:
        return await self.repo.get_total_count(tenant_id=tentant_id, filters=filters)

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

    async def update_user(self, user_id: UUID, user_update_public: UserUpdatePublic):
        await self._validate_email(user_update_public)
        await self._validate_username(user_update_public)

        user_update = UserUpdate(id=user_id, **user_update_public.model_dump(exclude_unset=True))

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

        user.quota_used = await self.info_blob_repo.get_total_size_of_user(user_id=user.id)
        return user

    async def generate_api_key(self, user_id: UUID):
        return await self.auth_service.create_user_api_key("inp", user_id=user_id)
