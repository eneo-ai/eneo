import secrets
from fastapi import APIRouter, Body, Depends, HTTPException, status
from typing import Dict, Optional
from uuid import UUID

from intric.integration.application.tenant_sharepoint_app_service import TenantSharePointAppService
from intric.integration.infrastructure.auth_service.service_account_auth_service import (
    ServiceAccountAuthService,
)
from intric.integration.infrastructure.auth_service.tenant_app_auth_service import TenantAppAuthService
from intric.settings.encryption_service import EncryptionService
from intric.integration.presentation.admin_models import (
    TenantSharePointAppCreate,
    TenantSharePointAppPublic,
    TenantAppTestResult,
    SharePointSubscriptionPublic,
    SubscriptionRenewalResult,
    ServiceAccountAuthStart,
    ServiceAccountAuthStartResponse,
    ServiceAccountAuthCallback,
)
from intric.main.container.container import Container
from intric.main.logging import get_logger
from intric.roles.permissions import Permission, validate_permission
from intric.server.dependencies.container import get_container

logger = get_logger(__name__)
router = APIRouter()

# In-memory storage for OAuth states (in production, use Redis or similar)
# Format: {state: {client_id, client_secret, tenant_domain, tenant_id, created_at}}
_oauth_states: Dict[str, Dict] = {}


@router.post(
    "/sharepoint/app",
    response_model=TenantSharePointAppPublic,
    status_code=201,
    summary="Configure tenant SharePoint app",
    description=(
        "Configure Azure AD application credentials for organization-wide SharePoint access. "
        "This eliminates person-dependency for shared and organization spaces by using "
        "application permissions instead of delegated user permissions. "
        "Requires admin role."
    ),
    responses={
        201: {"description": "SharePoint app successfully configured"},
        400: {"description": "Invalid credentials or configuration"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    }
)
async def configure_sharepoint_app(
    app_config: TenantSharePointAppCreate,
    container: Container = Depends(get_container(with_user=True))
) -> TenantSharePointAppPublic:
    """Configure or update the tenant's SharePoint application credentials."""
    try:
        user = container.user()
        validate_permission(user, Permission.ADMIN)

        tenant_app_service: TenantSharePointAppService = container.tenant_sharepoint_app_service()
        tenant_app_auth_service: TenantAppAuthService = container.tenant_app_auth_service()
        encryption_service: EncryptionService = container.encryption_service()

        tenant_id = user.tenant_id

        from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
        temp_app = TenantSharePointApp(
            tenant_id=tenant_id,
            client_id=app_config.client_id,
            client_secret=app_config.client_secret,
            tenant_domain=app_config.tenant_domain,
            certificate_path=app_config.certificate_path,
        )

        success, error_msg = await tenant_app_auth_service.test_credentials(temp_app)
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid credentials: {error_msg}"
            )

        app = await tenant_app_service.configure_tenant_app(
            tenant_id=tenant_id,
            client_id=app_config.client_id,
            client_secret=app_config.client_secret,
            tenant_domain=app_config.tenant_domain,
            certificate_path=app_config.certificate_path,
            created_by=user.id,
        )

        logger.info(f"Configured SharePoint app for tenant {tenant_id} by user {user.id}")

        user_integration_repo = container.user_integration_repo()
        tenant_integration_repo = container.tenant_integration_repo()
        integration_repo = container.integration_repo()

        sharepoint_integrations = await tenant_integration_repo.query(tenant_id=tenant_id)
        sharepoint_integration = next(
            (ti for ti in sharepoint_integrations
             if ti.integration.integration_type == "sharepoint"),
            None
        )

        if not sharepoint_integration:
            logger.info(f"SharePoint TenantIntegration not found for tenant {tenant_id}, creating it")

            sharepoint_system_integration = await integration_repo.one_or_none(
                integration_type="sharepoint"
            )

            if not sharepoint_system_integration:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="SharePoint integration not found in system"
                )

            from intric.integration.domain.entities.tenant_integration import TenantIntegration
            sharepoint_integration = TenantIntegration(
                tenant_id=tenant_id,
                integration=sharepoint_system_integration,
            )
            sharepoint_integration = await tenant_integration_repo.add(sharepoint_integration)
            logger.info(f"Created SharePoint TenantIntegration {sharepoint_integration.id} for tenant {tenant_id}")

        if sharepoint_integration:
            # Tenant app integrations are person-independent (user_id=None)
            existing_integration = await user_integration_repo.one_or_none(
                tenant_integration_id=sharepoint_integration.id,
                auth_type="tenant_app",
                tenant_app_id=app.id
            )

            if existing_integration:
                logger.info(
                    f"Found existing tenant_app integration {existing_integration.id}, updating"
                )
                try:
                    existing_integration.authenticated = True
                    await user_integration_repo.update(existing_integration)
                    logger.info(f"Updated tenant_app integration {existing_integration.id}")
                except Exception as update_error:
                    logger.error(
                        f"Failed to update tenant_app integration: {type(update_error).__name__}: {str(update_error)}",
                        exc_info=True
                    )
                    raise
            else:
                # Create new person-independent tenant_app integration
                from intric.integration.domain.entities.user_integration import UserIntegration
                new_user_integration = UserIntegration(
                    tenant_integration=sharepoint_integration,
                    user_id=None,  # Person-independent! Not tied to any specific user
                    authenticated=True,
                    auth_type="tenant_app",
                    tenant_app_id=app.id,
                )
                await user_integration_repo.add(new_user_integration)
                logger.info(
                    f"Created new person-independent tenant_app integration for tenant {tenant_id}"
                )

        return TenantSharePointAppPublic(
            id=app.id,
            tenant_id=app.tenant_id,
            client_id=app.client_id,
            client_secret_masked=encryption_service.mask_secret(app.client_secret),
            tenant_domain=app.tenant_domain,
            is_active=app.is_active,
            auth_method=app.auth_method,
            service_account_email=app.service_account_email,
            certificate_path=app.certificate_path,
            created_by=app.created_by,
            created_at=app.created_at,
            updated_at=app.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to configure SharePoint app: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to configure SharePoint app: {str(e)}"
        )


@router.get(
    "/sharepoint/app",
    response_model=Optional[TenantSharePointAppPublic],
    summary="Get tenant SharePoint app configuration",
    description=(
        "Retrieve the current SharePoint app configuration for the tenant. "
        "Client secret is masked in the response. "
        "Requires admin role."
    ),
    responses={
        200: {"description": "SharePoint app configuration retrieved (may be null if not configured)"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    }
)
async def get_sharepoint_app(
    container: Container = Depends(get_container(with_user=True))
) -> Optional[TenantSharePointAppPublic]:
    """Get the tenant's SharePoint app configuration."""
    try:
        user = container.user()
        validate_permission(user, Permission.ADMIN)

        tenant_app_service: TenantSharePointAppService = container.tenant_sharepoint_app_service()
        encryption_service: EncryptionService = container.encryption_service()

        tenant_id = user.tenant_id

        app = await tenant_app_service.get_active_app_for_tenant(tenant_id)

        if not app:
            return None

        return TenantSharePointAppPublic(
            id=app.id,
            tenant_id=app.tenant_id,
            client_id=app.client_id,
            client_secret_masked=encryption_service.mask_secret(app.client_secret),
            tenant_domain=app.tenant_domain,
            is_active=app.is_active,
            auth_method=app.auth_method,
            service_account_email=app.service_account_email,
            certificate_path=app.certificate_path,
            created_by=app.created_by,
            created_at=app.created_at,
            updated_at=app.updated_at,
        )

    except Exception as e:
        logger.error(f"Failed to get SharePoint app: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get SharePoint app: {str(e)}"
        )


@router.post(
    "/sharepoint/app/test",
    response_model=TenantAppTestResult,
    summary="Test SharePoint app credentials",
    description=(
        "Test if the provided SharePoint app credentials are valid by attempting "
        "to acquire an access token. This does not save the credentials. "
        "Requires admin role."
    ),
    responses={
        200: {"description": "Test completed (check success field in response)"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    }
)
async def test_sharepoint_app_credentials(
    app_config: TenantSharePointAppCreate = Body(...),
    container: Container = Depends(get_container(with_user=True))
) -> TenantAppTestResult:
    """Test SharePoint app credentials without saving them."""
    try:
        user = container.user()
        validate_permission(user, Permission.ADMIN)

        logger.info(f"Received test request with app_config: {app_config}")

        tenant_app_auth_service: TenantAppAuthService = container.tenant_app_auth_service()
        tenant_id = user.tenant_id

        from intric.integration.domain.entities.tenant_sharepoint_app import TenantSharePointApp
        temp_app = TenantSharePointApp(
            tenant_id=tenant_id,
            client_id=app_config.client_id,
            client_secret=app_config.client_secret,
            tenant_domain=app_config.tenant_domain,
            certificate_path=app_config.certificate_path,
        )

        success, error_msg = await tenant_app_auth_service.test_credentials(temp_app)

        return TenantAppTestResult(
            success=success,
            error_message=error_msg,
            details="Token acquired successfully" if success else None
        )

    except Exception as e:
        logger.error(f"Failed to test SharePoint app credentials: {e}")
        return TenantAppTestResult(
            success=False,
            error_message=str(e)
        )


@router.delete(
    "/sharepoint/app",
    status_code=200,
    summary="Permanently delete SharePoint app",
    description=(
        "Permanently delete the tenant's SharePoint app configuration and all associated data. "
        "WARNING: This action CANNOT be undone. This will cascade delete:\n"
        "- All user_integrations using this tenant app (both org and personal)\n"
        "- All integration_knowledge (imported SharePoint content)\n"
        "- All info_blobs and embeddings (document data and vectors)\n"
        "- All sharepoint_subscriptions (webhooks)\n"
        "- All oauth_tokens for personal SharePoint integrations\n"
        "- All sync_logs\n\n"
        "Assistants linked to this knowledge will lose their connections.\n"
        "Requires admin role."
    ),
    responses={
        200: {"description": "SharePoint app permanently deleted"},
        404: {"description": "No SharePoint app configured"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    }
)
async def delete_sharepoint_app(
    container: Container = Depends(get_container(with_user=True))
) -> Dict[str, str]:
    """Permanently delete the tenant's SharePoint app and all associated data."""
    try:
        user = container.user()
        validate_permission(user, Permission.ADMIN)

        tenant_app_service: TenantSharePointAppService = container.tenant_sharepoint_app_service()
        user_integration_repo = container.user_integration_repo()

        tenant_id = user.tenant_id

        app = await tenant_app_service.tenant_app_repo.get_by_tenant(tenant_id)
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No SharePoint app configured for this tenant"
            )

        # CRITICAL: Delete all user_integrations that use this tenant app first
        # This triggers database CASCADE DELETE for:
        # - oauth_tokens (via user_integration_id FK)
        # - integration_knowledge (via user_integration_id FK)
        # - sharepoint_subscriptions (via user_integration_id FK)
        # - info_blobs (via integration_knowledge_id FK from integration_knowledge)
        # - info_blob_chunks (via info_blob_id FK from info_blobs)
        user_integrations = await user_integration_repo.query(tenant_app_id=app.id)

        logger.warning(
            f"Deleting {len(user_integrations)} user_integrations for SharePoint app {app.id} "
            f"(tenant {tenant_id}) - this will cascade delete all related knowledge and tokens"
        )

        for user_integration in user_integrations:
            await user_integration_repo.remove(id=user_integration.id)
            logger.info(f"Deleted user_integration {user_integration.id}")

        # Now delete the app itself
        success = await tenant_app_service.delete_app(tenant_id)

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete SharePoint app after cleaning up integrations"
            )

        logger.warning(
            f"Permanently deleted SharePoint app for tenant {tenant_id} by user {user.id}. "
            f"Deleted {len(user_integrations)} user_integrations and all associated data."
        )

        return {"message": "SharePoint app and all associated data permanently deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete SharePoint app: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete SharePoint app: {str(e)}"
        )


@router.get(
    "/sharepoint/subscriptions",
    response_model=list[SharePointSubscriptionPublic],
    summary="List all SharePoint webhook subscriptions",
    description=(
        "Get all SharePoint webhook subscriptions for the tenant. "
        "Shows status, expiration time, and related integration information. "
        "Requires admin role."
    ),
    responses={
        200: {"description": "List of subscriptions retrieved"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    }
)
async def list_sharepoint_subscriptions(
    container: Container = Depends(get_container(with_user=True))
):
    """List all SharePoint subscriptions for the tenant."""
    try:
        user = container.user()

        # Check admin permissions
        validate_permission(user, Permission.ADMIN)

        subscription_repo = container.sharepoint_subscription_repo()
        user_integration_repo = container.user_integration_repo()
        user_repo = container.user_repo()

        # Get all subscriptions
        all_subscriptions = await subscription_repo.list_all()

        from datetime import datetime, timezone

        # Build a cache of user_integrations and users for efficiency
        user_integration_ids = [sub.user_integration_id for sub in all_subscriptions]
        user_integrations_map = {}
        users_map = {}

        # Fetch all user_integrations
        for ui_id in user_integration_ids:
            try:
                ui = await user_integration_repo.one_or_none(id=ui_id)
                if ui:
                    user_integrations_map[ui_id] = ui
                    # Fetch user if user_id exists
                    if ui.user_id and ui.user_id not in users_map:
                        user_obj = await user_repo.get_user_by_id(ui.user_id)
                        if user_obj:
                            users_map[ui.user_id] = user_obj
            except Exception as e:
                logger.warning(f"Could not fetch user_integration {ui_id}: {e}")

        # Convert to public models with computed fields
        result = []
        for sub in all_subscriptions:
            now = datetime.now(timezone.utc)
            expires_in_hours = max(0, int((sub.expires_at - now).total_seconds() / 3600))

            # Determine owner info
            owner_email = None
            owner_type = "organization"

            ui = user_integrations_map.get(sub.user_integration_id)
            if ui:
                if ui.user_id:
                    owner_type = "user"
                    user_obj = users_map.get(ui.user_id)
                    if user_obj:
                        owner_email = user_obj.email
                else:
                    owner_type = "organization"

            result.append(SharePointSubscriptionPublic(
                id=sub.id,
                user_integration_id=sub.user_integration_id,
                site_id=sub.site_id,
                subscription_id=sub.subscription_id,
                drive_id=sub.drive_id,
                expires_at=sub.expires_at,
                created_at=sub.created_at,
                is_expired=sub.is_expired(),
                expires_in_hours=expires_in_hours,
                owner_email=owner_email,
                owner_type=owner_type,
            ))

        return result

    except Exception as e:
        logger.error(f"Failed to list SharePoint subscriptions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list SharePoint subscriptions: {str(e)}"
        )


@router.post(
    "/sharepoint/subscriptions/renew-expired",
    response_model=SubscriptionRenewalResult,
    summary="Renew all expired SharePoint subscriptions",
    description=(
        "Recreate all expired SharePoint webhook subscriptions for the tenant. "
        "This is useful after server downtime > 24h when subscriptions have expired. "
        "Preserves all integration relationships - assistants continue to work. "
        "Requires admin role."
    ),
    responses={
        200: {"description": "Renewal operation completed (check result for details)"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    }
)
async def renew_expired_subscriptions(
    container: Container = Depends(get_container(with_user=True))
):
    """Renew all expired SharePoint subscriptions for the tenant."""
    try:
        user = container.user()

        # Check admin permissions
        validate_permission(user, Permission.ADMIN)

        subscription_repo = container.sharepoint_subscription_repo()
        subscription_service = container.sharepoint_subscription_service()
        oauth_token_service = container.oauth_token_service()

        # Get all subscriptions
        all_subscriptions = await subscription_repo.list_all()

        # Filter expired ones
        expired_subscriptions = [sub for sub in all_subscriptions if sub.is_expired()]

        logger.info(
            f"Admin {user.id} initiated bulk renewal for {len(expired_subscriptions)} "
            f"expired subscriptions (total subscriptions: {len(all_subscriptions)})"
        )

        recreated = 0
        failed = 0
        errors = []

        for sub in expired_subscriptions:
            try:
                # Get token for this user integration
                token = await oauth_token_service.get_oauth_token_by_user_integration(
                    user_integration_id=sub.user_integration_id
                )

                if not token:
                    error_msg = f"No token found for subscription {sub.id} (user_integration={sub.user_integration_id})"
                    logger.warning(error_msg)
                    errors.append(error_msg)
                    failed += 1
                    continue

                # Ensure it's a SharePoint token
                if not token.token_type.is_sharepoint:
                    error_msg = f"Token for subscription {sub.id} is not a SharePoint token"
                    logger.warning(error_msg)
                    errors.append(error_msg)
                    failed += 1
                    continue

                # Refresh token if needed (expired tokens can't be used)
                try:
                    token = await oauth_token_service.refresh_and_update_token(token_id=token.id)
                    logger.debug(f"Refreshed OAuth token for subscription {sub.id}")
                except Exception as refresh_error:
                    error_msg = f"Failed to refresh token for subscription {sub.id}: {str(refresh_error)}"
                    logger.error(error_msg)
                    errors.append(error_msg)
                    failed += 1
                    continue

                # Recreate subscription
                success = await subscription_service.recreate_expired_subscription(
                    subscription=sub,
                    token=token
                )

                if success:
                    recreated += 1
                else:
                    failed += 1
                    errors.append(f"Failed to recreate subscription {sub.id}")

            except Exception as exc:
                logger.error(f"Error recreating subscription {sub.id}: {exc}", exc_info=True)
                failed += 1
                errors.append(f"Subscription {sub.id}: {str(exc)}")

        result = SubscriptionRenewalResult(
            total_subscriptions=len(all_subscriptions),
            expired_count=len(expired_subscriptions),
            recreated=recreated,
            failed=failed,
            errors=errors
        )

        logger.info(
            f"Bulk renewal complete: {recreated} recreated, {failed} failed "
            f"(out of {len(expired_subscriptions)} expired)"
        )

        return result

    except Exception as e:
        logger.error(
            f"Failed to renew expired subscriptions: {e}",
            exc_info=True  # This logs the full stack trace
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to renew expired subscriptions: {str(e)}"
        )


@router.post(
    "/sharepoint/subscriptions/{subscription_id}/recreate",
    response_model=SharePointSubscriptionPublic,
    summary="Recreate a specific SharePoint subscription",
    description=(
        "Recreate a specific SharePoint webhook subscription. "
        "Useful for targeted fixes of expired or problematic subscriptions. "
        "Preserves all integration relationships. "
        "Requires admin role."
    ),
    responses={
        200: {"description": "Subscription successfully recreated"},
        404: {"description": "Subscription not found"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    }
)
async def recreate_subscription(
    subscription_id: UUID,
    container: Container = Depends(get_container(with_user=True))
):
    """Recreate a specific SharePoint subscription."""
    try:
        user = container.user()

        # Check admin permissions
        validate_permission(user, Permission.ADMIN)

        subscription_repo = container.sharepoint_subscription_repo()
        subscription_service = container.sharepoint_subscription_service()
        oauth_token_service = container.oauth_token_service()
        user_integration_repo = container.user_integration_repo()

        # Get subscription
        subscription = await subscription_repo.one_or_none(id=subscription_id)

        if not subscription:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Subscription {subscription_id} not found"
            )

        # Get user_integration to check auth type
        user_integration = await user_integration_repo.one_or_none(
            id=subscription.user_integration_id
        )

        if not user_integration:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User integration {subscription.user_integration_id} not found"
            )

        # Handle different auth types
        token = None

        if user_integration.tenant_app_id:
            # Tenant app authentication - get token from TenantSharePointApp
            logger.info(f"Subscription {subscription_id} uses tenant_app_id: {user_integration.tenant_app_id}")
            tenant_app_repo = container.tenant_sharepoint_app_repo()

            tenant_app = await tenant_app_repo.get_by_id(user_integration.tenant_app_id)
            if not tenant_app:
                logger.error(f"TenantSharePointApp {user_integration.tenant_app_id} not found")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"TenantSharePointApp {user_integration.tenant_app_id} not found"
                )

            logger.info(f"TenantSharePointApp found: auth_method={tenant_app.auth_method}")

            # Create a simple token-like object for the subscription service
            class SimpleToken:
                def __init__(self, access_token: str):
                    self.access_token = access_token
                    self.base_url = "https://graph.microsoft.com"

            try:
                if tenant_app.is_service_account():
                    # Service account uses delegated permissions with refresh token
                    service_account_auth = container.service_account_auth_service()
                    token_result = await service_account_auth.refresh_access_token(tenant_app)
                    logger.info(f"Refreshed service account token for subscription {subscription_id}")
                    token = SimpleToken(token_result["access_token"])
                else:
                    # Tenant app uses client credentials flow (application permissions)
                    tenant_app_auth = container.tenant_app_auth_service()
                    access_token = await tenant_app_auth.get_access_token(tenant_app)
                    logger.info(f"Got tenant app token for subscription {subscription_id}")
                    token = SimpleToken(access_token)
            except Exception as auth_error:
                logger.error(f"Failed to get token for subscription {subscription_id}: {auth_error}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to get access token: {str(auth_error)}"
                )
        else:
            # Personal OAuth token authentication
            token = await oauth_token_service.get_oauth_token_by_user_integration(
                user_integration_id=subscription.user_integration_id
            )

            if not token:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"No OAuth token found for user_integration {subscription.user_integration_id}"
                )

            # Ensure it's a SharePoint token
            if not token.token_type.is_sharepoint:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Token for user_integration {subscription.user_integration_id} is not a SharePoint token"
                )

            # Refresh token if needed (expired tokens can't be used)
            try:
                token = await oauth_token_service.refresh_and_update_token(token_id=token.id)
                logger.info(f"Refreshed OAuth token for subscription {subscription_id}")
            except Exception as refresh_error:
                logger.error(f"Failed to refresh token for subscription {subscription_id}: {refresh_error}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Failed to refresh OAuth token: {str(refresh_error)}"
                )

        # Recreate subscription
        success = await subscription_service.recreate_expired_subscription(
            subscription=subscription,
            token=token
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to recreate subscription {subscription_id}"
            )

        logger.info(f"Admin {user.id} manually recreated subscription {subscription_id}")

        # Return updated subscription
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        expires_in_hours = max(0, int((subscription.expires_at - now).total_seconds() / 3600))

        # Determine owner info (user_integration already fetched above)
        owner_email = None
        owner_type = "organization"
        if user_integration.user_id:
            owner_type = "user"
            user_repo = container.user_repo()
            owner_user = await user_repo.get_user_by_id(user_integration.user_id)
            if owner_user:
                owner_email = owner_user.email

        return SharePointSubscriptionPublic(
            id=subscription.id,
            user_integration_id=subscription.user_integration_id,
            site_id=subscription.site_id,
            subscription_id=subscription.subscription_id,
            drive_id=subscription.drive_id,
            expires_at=subscription.expires_at,
            created_at=subscription.created_at,
            is_expired=subscription.is_expired(),
            expires_in_hours=expires_in_hours,
            owner_email=owner_email,
            owner_type=owner_type,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to recreate subscription {subscription_id}: {e}",
            exc_info=True  # This logs the full stack trace
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to recreate subscription: {str(e)}"
        )


# Service Account OAuth Endpoints

@router.post(
    "/sharepoint/service-account/auth/start",
    response_model=ServiceAccountAuthStartResponse,
    summary="Start service account OAuth flow",
    description=(
        "Start the OAuth flow for configuring a service account. "
        "Returns an authorization URL that the admin should be redirected to. "
        "The admin will log in with the service account credentials at Microsoft. "
        "Requires admin role."
    ),
    responses={
        200: {"description": "OAuth authorization URL generated"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    }
)
async def start_service_account_auth(
    app_config: ServiceAccountAuthStart,
    container: Container = Depends(get_container(with_user=True))
) -> ServiceAccountAuthStartResponse:
    """Start OAuth flow for service account configuration."""
    try:
        user = container.user()
        validate_permission(user, Permission.ADMIN)

        # Generate a secure state token
        state = secrets.token_urlsafe(32)

        # Store state with credentials for callback verification
        from datetime import datetime
        _oauth_states[state] = {
            "client_id": app_config.client_id,
            "client_secret": app_config.client_secret,
            "tenant_domain": app_config.tenant_domain,
            "tenant_id": str(user.tenant_id),
            "user_id": str(user.id),
            "created_at": datetime.utcnow().isoformat(),
        }

        # Generate OAuth URL
        service_account_auth_service = ServiceAccountAuthService()
        auth_result = service_account_auth_service.gen_auth_url(
            state=state,
            client_id=app_config.client_id,
            client_secret=app_config.client_secret,
            tenant_domain=app_config.tenant_domain,
        )

        logger.info(
            f"Started service account OAuth flow for tenant {user.tenant_id} "
            f"by user {user.id}"
        )

        return ServiceAccountAuthStartResponse(
            auth_url=auth_result["auth_url"],
            state=state,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start service account OAuth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start service account OAuth: {str(e)}"
        )


@router.post(
    "/sharepoint/service-account/auth/callback",
    response_model=TenantSharePointAppPublic,
    status_code=201,
    summary="Complete service account OAuth flow",
    description=(
        "Complete the OAuth flow by exchanging the authorization code for tokens. "
        "This will configure the service account for the tenant's SharePoint access. "
        "Requires admin role."
    ),
    responses={
        201: {"description": "Service account successfully configured"},
        400: {"description": "Invalid state or auth code"},
        401: {"description": "Authentication required"},
        403: {"description": "Admin permissions required"},
    }
)
async def service_account_auth_callback(
    callback: ServiceAccountAuthCallback,
    container: Container = Depends(get_container(with_user=True))
) -> TenantSharePointAppPublic:
    """Complete OAuth flow and configure service account."""
    try:
        user = container.user()
        validate_permission(user, Permission.ADMIN)

        # Verify state
        if callback.state not in _oauth_states:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired OAuth state. Please restart the authentication flow."
            )

        stored_state = _oauth_states.pop(callback.state)

        # Verify tenant matches
        if stored_state["tenant_id"] != str(user.tenant_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth state was initiated by a different tenant"
            )

        # Exchange auth code for tokens
        service_account_auth_service = ServiceAccountAuthService()
        token_result = await service_account_auth_service.exchange_token(
            auth_code=callback.auth_code,
            client_id=callback.client_id,
            client_secret=callback.client_secret,
            tenant_domain=callback.tenant_domain,
        )

        # Configure service account
        tenant_app_service: TenantSharePointAppService = container.tenant_sharepoint_app_service()
        encryption_service: EncryptionService = container.encryption_service()

        app = await tenant_app_service.configure_service_account(
            tenant_id=user.tenant_id,
            client_id=callback.client_id,
            client_secret=callback.client_secret,
            tenant_domain=callback.tenant_domain,
            refresh_token=token_result.refresh_token,
            service_account_email=token_result.email or "unknown",
            created_by=user.id,
        )

        # Create or update the person-independent UserIntegration
        user_integration_repo = container.user_integration_repo()
        tenant_integration_repo = container.tenant_integration_repo()
        integration_repo = container.integration_repo()

        sharepoint_integrations = await tenant_integration_repo.query(tenant_id=user.tenant_id)
        sharepoint_integration = next(
            (ti for ti in sharepoint_integrations
             if ti.integration.integration_type == "sharepoint"),
            None
        )

        if not sharepoint_integration:
            logger.info(f"SharePoint TenantIntegration not found for tenant {user.tenant_id}, creating it")

            sharepoint_system_integration = await integration_repo.one_or_none(
                integration_type="sharepoint"
            )

            if not sharepoint_system_integration:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="SharePoint integration not found in system"
                )

            from intric.integration.domain.entities.tenant_integration import TenantIntegration
            sharepoint_integration = TenantIntegration(
                tenant_id=user.tenant_id,
                integration=sharepoint_system_integration,
            )
            sharepoint_integration = await tenant_integration_repo.add(sharepoint_integration)
            logger.info(f"Created SharePoint TenantIntegration {sharepoint_integration.id}")

        if sharepoint_integration:
            existing_integration = await user_integration_repo.one_or_none(
                tenant_integration_id=sharepoint_integration.id,
                auth_type="tenant_app",
                tenant_app_id=app.id
            )

            if existing_integration:
                existing_integration.authenticated = True
                await user_integration_repo.update(existing_integration)
                logger.info(f"Updated service account integration {existing_integration.id}")
            else:
                from intric.integration.domain.entities.user_integration import UserIntegration
                new_user_integration = UserIntegration(
                    tenant_integration=sharepoint_integration,
                    user_id=None,
                    authenticated=True,
                    auth_type="tenant_app",
                    tenant_app_id=app.id,
                )
                await user_integration_repo.add(new_user_integration)
                logger.info(
                    f"Created new person-independent service account integration for tenant {user.tenant_id}"
                )

        logger.info(
            f"Configured service account for tenant {user.tenant_id} "
            f"({token_result.email}) by user {user.id}"
        )

        return TenantSharePointAppPublic(
            id=app.id,
            tenant_id=app.tenant_id,
            client_id=app.client_id,
            client_secret_masked=encryption_service.mask_secret(app.client_secret),
            tenant_domain=app.tenant_domain,
            is_active=app.is_active,
            auth_method=app.auth_method,
            service_account_email=app.service_account_email,
            certificate_path=app.certificate_path,
            created_by=app.created_by,
            created_at=app.created_at,
            updated_at=app.updated_at,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to complete service account OAuth: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to complete service account OAuth: {str(e)}"
        )
