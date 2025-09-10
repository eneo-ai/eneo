import sqlalchemy as sa

from intric.admin.admin_models import PrivacyPolicy, UserDeletedListItem, UserStateListItem
from intric.database.tables.users_table import Users
from intric.main.exceptions import BadRequestException, NotFoundException, UniqueUserException
from intric.main.logging import get_logger
from intric.roles.permissions import Permission, validate_permissions
from intric.tenants.tenant_repo import TenantRepository
from intric.users.user import (
    UserAddAdmin,
    UserAddSuperAdmin,
    UserInDB,
    UserState,
    UserUpdatePublic,
)
from intric.users.user_repo import UsersRepository
from intric.users.user_service import UserService

logger = get_logger(__name__)


class AdminService:
    def __init__(
        self,
        user: UserInDB,
        user_repo: UsersRepository,
        tenant_repo: TenantRepository,
        user_service: UserService,
    ):
        self.user = user
        self.user_repo = user_repo
        self.tenant_repo = tenant_repo
        self.user_service = user_service

    @validate_permissions(Permission.ADMIN)
    async def get_tenant_users(self):
        logger.info(f"Admin user {self.user.username} listing all users in tenant {self.user.tenant_id}")
        
        users = await self.user_repo.get_all_users(self.user.tenant_id)
        
        logger.info(f"Successfully retrieved {len(users)} users for tenant {self.user.tenant_id}")
        return users

    @validate_permissions(Permission.ADMIN)
    async def register_tenant_user(self, user: UserAddAdmin):
        logger.info(f"Admin user {self.user.username} creating user {user.username} in tenant {self.user.tenant_id}")
        
        # Check for duplicate username in tenant (including soft-deleted users)
        existing_user_by_username = await self.user_repo.get_user_by_username(user.username)
        if existing_user_by_username and existing_user_by_username.tenant_id == self.user.tenant_id:
            logger.warning(f"Username {user.username} already exists in tenant {self.user.tenant_id}")
            raise UniqueUserException(f"Username '{user.username}' is already taken")
        
        # Check for duplicate email in tenant (including soft-deleted users)
        existing_user_by_email = await self.user_repo.get_user_by_email(user.email)
        if existing_user_by_email and existing_user_by_email.tenant_id == self.user.tenant_id:
            logger.warning(f"Email {user.email} already exists in tenant {self.user.tenant_id}")
            raise UniqueUserException(f"Email '{user.email}' is already registered")
        
        user_with_tenant = UserAddSuperAdmin(
            **user.model_dump(), tenant_id=self.user.tenant_id
        )

        result = await self.user_service.register(user_with_tenant)
        logger.info(f"Successfully created user {user.username} in tenant {self.user.tenant_id}")
        return result

    @validate_permissions(Permission.ADMIN)
    async def update_tenant_user(self, username: str, user: UserUpdatePublic):
        logger.info(f"Admin user {self.user.username} updating user {username} in tenant {self.user.tenant_id}")
        
        user_in_db = await self.user_repo.get_user_by_username(username)

        if user_in_db is None:
            logger.warning(f"User {username} not found")
            raise NotFoundException(f"User '{username}' not found in your tenant")
        
        if user_in_db.tenant_id != self.user.tenant_id:
            logger.warning(f"Cross-tenant access attempt: admin {self.user.username} tried to access user {username} in tenant {user_in_db.tenant_id}")
            raise BadRequestException("You do not have access to remove or add users on another tenant")
        
        # Check if user is soft-deleted
        if user_in_db.deleted_at is not None:
            logger.warning(f"Attempt to update soft-deleted user {username}")
            raise NotFoundException(f"User '{username}' not found in your tenant")
        
        # Check for duplicate email if email is being updated
        if user.email is not None and user.email != user_in_db.email:
            existing_user_by_email = await self.user_repo.get_user_by_email(user.email)
            if existing_user_by_email and existing_user_by_email.tenant_id == self.user.tenant_id and existing_user_by_email.id != user_in_db.id:
                logger.warning(f"Email {user.email} already exists in tenant {self.user.tenant_id}")
                raise UniqueUserException(f"Email '{user.email}' is already registered")

        result = await self.user_service.update_user(user_in_db.id, user)
        logger.info(f"Successfully updated user {username} in tenant {self.user.tenant_id}")
        return result

    @validate_permissions(Permission.ADMIN)
    async def delete_tenant_user(self, username: str):
        logger.info(f"Admin user {self.user.username} attempting to delete user {username} in tenant {self.user.tenant_id}")
        
        user_in_db = await self.user_repo.get_user_by_username(username)

        if user_in_db is None:
            logger.warning(f"User {username} not found")
            raise NotFoundException(f"User '{username}' not found in your tenant")
        
        if user_in_db.tenant_id != self.user.tenant_id:
            logger.warning(f"Cross-tenant deletion attempt: admin {self.user.username} tried to delete user {username} in tenant {user_in_db.tenant_id}")
            raise BadRequestException("You do not have access to remove or add users on another tenant")

        if user_in_db.id == self.user.id:
            logger.warning(f"Self-deletion attempt: admin {self.user.username} tried to delete themselves")
            raise BadRequestException("Cannot delete your own user account")
        
        # Check if user is already soft-deleted
        if user_in_db.deleted_at is not None:
            logger.warning(f"Attempt to delete already soft-deleted user {username}")
            raise NotFoundException(f"User '{username}' not found in your tenant")

        result = await self.user_service.delete_user(user_in_db.id)
        logger.info(f"Successfully soft-deleted user {username} in tenant {self.user.tenant_id}")
        return result

    @validate_permissions(Permission.ADMIN)
    async def update_privacy_policy(self, privacy_policy: PrivacyPolicy):
        return await self.tenant_repo.set_privacy_policy(
            privacy_policy.url, tenant_id=self.user.tenant_id
        )

    @validate_permissions(Permission.ADMIN)
    async def deactivate_tenant_user(self, username: str):
        """Deactivate user for temporary leave (sick, vacation, parental leave)"""
        logger.info(f"Admin user {self.user.username} deactivating user {username} in tenant {self.user.tenant_id}")
        
        user_in_db = await self.user_repo.get_user_by_username(username)

        if user_in_db is None:
            logger.warning(f"User {username} not found for deactivation")
            raise NotFoundException(f"User '{username}' not found in your tenant")
        
        if user_in_db.tenant_id != self.user.tenant_id:
            logger.warning(f"Cross-tenant deactivation attempt: admin {self.user.username} tried to deactivate user {username} in tenant {user_in_db.tenant_id}")
            raise BadRequestException("You do not have access to manage users on another tenant")

        if user_in_db.id == self.user.id:
            logger.warning(f"Self-deactivation attempt: admin {self.user.username} tried to deactivate themselves")
            raise BadRequestException("Cannot deactivate your own admin account")

        # Update user state to INACTIVE
        result = await self.user_service.update_user(user_in_db.id, UserUpdatePublic(state=UserState.INACTIVE))
        
        logger.info(f"Successfully deactivated user {username} in tenant {self.user.tenant_id}")
        return result

    @validate_permissions(Permission.ADMIN)
    async def reactivate_tenant_user(self, username: str):
        """Reactivate user from any state (INACTIVE or DELETED)"""
        logger.info(f"Admin user {self.user.username} reactivating user {username} in tenant {self.user.tenant_id}")
        
        # Use with_deleted=True to find users in any state
        user_in_db = await self.user_repo.get_user_by_username(username, with_deleted=True)

        if user_in_db is None:
            logger.warning(f"User {username} not found for reactivation")
            raise NotFoundException(f"User '{username}' not found in your tenant")
        
        if user_in_db.tenant_id != self.user.tenant_id:
            logger.warning(f"Cross-tenant reactivation attempt: admin {self.user.username} tried to reactivate user {username} in tenant {user_in_db.tenant_id}")
            raise BadRequestException("You do not have access to manage users on another tenant")

        # Reactivate user: set to ACTIVE and clear deleted_at if present
        if user_in_db.deleted_at is not None:
            # Clear deletion timestamp when reactivating from DELETED state
            logger.info(f"Clearing deletion timestamp for user {username} during reactivation")
        
        result = await self.user_service.update_user(user_in_db.id, UserUpdatePublic(state=UserState.ACTIVE))
        
        logger.info(f"Successfully reactivated user {username} in tenant {self.user.tenant_id}")
        return result

    @validate_permissions(Permission.ADMIN)
    async def get_inactive_tenant_users(self):
        """Get all users in INACTIVE state within tenant"""
        logger.info(f"Admin user {self.user.username} listing inactive users in tenant {self.user.tenant_id}")
        
        # Get all active users (deleted_at IS NULL) and filter for INACTIVE state
        all_users = await self.user_repo.get_all_users(self.user.tenant_id)
        inactive_users = [user for user in all_users if user.state == UserState.INACTIVE]
        
        # Convert to lightweight response format
        inactive_list = [
            UserStateListItem(
                username=user.username,
                email=user.email,
                state=user.state,
                state_changed_at=user.updated_at
            )
            for user in inactive_users
        ]
        
        logger.info(f"Successfully retrieved {len(inactive_list)} inactive users for tenant {self.user.tenant_id}")
        return inactive_list

    @validate_permissions(Permission.ADMIN)
    async def get_deleted_tenant_users(self):
        """Get all users in DELETED state within tenant"""
        logger.info(f"Admin user {self.user.username} listing deleted users in tenant {self.user.tenant_id}")
        
        # Query for deleted users directly (deleted_at IS NOT NULL)
        query = (
            sa.select(Users)
            .where(Users.tenant_id == self.user.tenant_id)
            .where(Users.deleted_at.is_not(None))
            .order_by(Users.deleted_at.desc())
        )
        
        # Execute query using the repository's session and delegate
        deleted_users_records = await self.user_repo.session.scalars(query)
        deleted_users_list = deleted_users_records.all()
        
        # Convert to lightweight response format
        deleted_list = [
            UserDeletedListItem(
                username=user.username,
                email=user.email,
                state=user.state,
                deleted_at=user.deleted_at
            )
            for user in deleted_users_list
        ]
        
        logger.info(f"Successfully retrieved {len(deleted_list)} deleted users for tenant {self.user.tenant_id}")
        return deleted_list
