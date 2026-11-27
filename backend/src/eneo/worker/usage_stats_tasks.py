"""Recalculation of an organisation's completion model usage statistics.

Run nightly for every active organisation, and by the operator for one. The
statistics are the organisation's own, so nothing here runs as a person."""

import logging
from typing import Any
from uuid import UUID

from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.main.container.container import Container

logger = logging.getLogger(__name__)


async def recalculate_tenant_usage_stats_direct(container: Container, tenant_id: UUID):
    """Recalculate usage statistics for a specific tenant directly (for sysadmin endpoints).

    This function performs the recalculation synchronously without using the job service,
    making it suitable for sysadmin endpoints that need immediate execution.

    Uses explicit sessionmanager.session() to avoid nested transaction issues
    when called from contexts that may already have a transaction open.

    Args:
        container: Dependency injection container (without user dependency)
        tenant_id: UUID of the tenant to recalculate usage stats for
    """
    logger.info(
        f"Starting direct usage statistics recalculation for tenant {tenant_id}",
        extra={"tenant_id": str(tenant_id)},
    )

    # Use fresh session to avoid nested transaction errors
    async with sessionmanager.session() as session:
        session_provider: Any = container.session
        session_provider.override(providers.Object(session))
        try:
            async with session.begin():
                tenant_repo = container.tenant_repo()

                tenant = await tenant_repo.get(tenant_id)
                if not tenant:
                    logger.error(
                        f"Tenant {tenant_id} not found",
                        extra={"tenant_id": str(tenant_id)},
                    )
                    return False

                # Import TenantState to check for active status
                from eneo.tenants.tenant import TenantState

                if tenant.state != TenantState.ACTIVE:
                    logger.warning(
                        f"Tenant {tenant_id} is not active (state: {tenant.state}), skipping usage stats recalculation",
                        extra={
                            "tenant_id": str(tenant_id),
                            "tenant_state": tenant.state,
                        },
                    )
                    return False

                # The statistics are the organisation's own: the service reads
                # by its id, and no person is behind the recalculation.
                tenant_provider: Any = container.tenant
                tenant_provider.override(providers.Object(tenant))

                # Get the usage service with proper context
                usage_service = container.completion_model_usage_service()

                # Perform full recalculation within this transaction
                logger.info(f"Starting direct recalculation for tenant {tenant_id}")
                await usage_service.recalculate_all_usage_stats_in_transaction(
                    tenant_id
                )

                logger.info(
                    f"Successfully completed direct usage stats recalculation for tenant {tenant_id}",
                    extra={"tenant_id": str(tenant_id)},
                )

                return True
        finally:
            # Always reset all overrides, even on exception
            container.session.reset_override()
            try:
                container.tenant.reset_override()
            except Exception:
                pass  # Best effort - may not have been overridden yet


async def recalculate_all_tenants_usage_stats(container: Container):
    """Recalculate usage statistics for all active tenants.

    This is designed to be called from a cron job for nightly updates.
    Uses explicit sessionmanager.session() to avoid nested transaction issues
    when called from cron wrapper that may already have a transaction open.
    """
    logger.info("Starting nightly usage statistics recalculation for all tenants")

    # Get all active tenants first (in a fresh, isolated session)
    # Use sessionmanager.session() instead of container.session() to avoid
    # nested transaction errors when cron wrapper already has a transaction
    async with sessionmanager.session() as session:
        # Override container's session with our fresh session
        session_provider: Any = container.session
        session_provider.override(providers.Object(session))
        try:
            async with session.begin():
                tenant_repo = container.tenant_repo()
                tenants = await tenant_repo.get_all_tenants()
                logger.info(f"Found {len(tenants)} total tenants from database")

                # Import TenantState to filter for active tenants
                from eneo.tenants.tenant import TenantState

                active_tenants = [t for t in tenants if t.state == TenantState.ACTIVE]

                # Log tenant states for debugging
                for tenant in tenants:
                    logger.info(
                        f"Tenant {tenant.id} ({tenant.name}): state={tenant.state}, active={tenant.state == TenantState.ACTIVE}",
                        extra={
                            "tenant_id": str(tenant.id),
                            "tenant_name": tenant.name,
                            "tenant_state": tenant.state,
                            "is_active": tenant.state == TenantState.ACTIVE,
                        },
                    )

                logger.info(
                    f"Found {len(active_tenants)} active tenants for usage stats update",
                    extra={
                        "tenant_count": len(active_tenants),
                        "active_tenant_ids": [str(t.id) for t in active_tenants],
                    },
                )

                if not active_tenants:
                    logger.warning(
                        "No active tenants found, skipping usage stats recalculation"
                    )
                    return True
        finally:
            # Always reset override, even on exception
            container.session.reset_override()

    # Process each tenant in its own isolated session/transaction
    # This ensures one tenant's failure doesn't affect others and avoids
    # nested transaction issues when called from cron wrapper
    processed_count = 0
    for tenant in active_tenants:
        try:
            logger.info(
                f"Processing usage stats for tenant {tenant.id} ({tenant.name})"
            )

            # Use fresh session per tenant to isolate failures and avoid nested transactions
            async with sessionmanager.session() as session:
                # Override container's session with our fresh session
                session_provider: Any = container.session
                session_provider.override(providers.Object(session))
                try:
                    async with session.begin():
                        # The statistics are the organisation's own: the
                        # service reads by its id, and no person is behind
                        # the recalculation.
                        tenant_provider: Any = container.tenant
                        tenant_provider.override(providers.Object(tenant))

                        # Get the usage service with proper context
                        usage_service = container.completion_model_usage_service()

                        # Perform full recalculation
                        logger.info(
                            f"Starting full recalculation for tenant {tenant.id}"
                        )
                        await usage_service.recalculate_all_usage_stats_in_transaction(
                            tenant.id
                        )

                        processed_count += 1

                        logger.info(
                            f"Successfully completed usage stats recalculation for tenant {tenant.id}",
                            extra={
                                "tenant_id": str(tenant.id),
                                "tenant_name": tenant.name,
                                "processed_count": processed_count,
                            },
                        )
                finally:
                    # Always reset all overrides, even on exception
                    # Reset the tenant to prevent leakage to next tenant iteration
                    container.session.reset_override()
                    try:
                        container.tenant.reset_override()
                    except Exception:
                        pass  # Best effort - may not have been overridden yet

        except Exception as e:
            logger.error(
                f"Error processing usage stats for tenant {tenant.id}",
                extra={
                    "tenant_id": str(tenant.id),
                    "tenant_name": getattr(tenant, "name", "unknown"),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            # Continue processing other tenants even if one fails
            continue

    logger.info(
        f"Completed processing: {processed_count} out of {len(active_tenants)} tenants successfully processed",
        extra={
            "processed_count": processed_count,
            "total_active_tenants": len(active_tenants),
        },
    )

    return True
