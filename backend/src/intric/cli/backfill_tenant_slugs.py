"""Backfill slugs for existing tenants.

This script generates URL-safe slugs for all tenants that don't have one.
It should be run after deploying the federation per tenant feature.

Usage:
    poetry run python -m intric.cli.backfill_tenant_slugs
"""

import asyncio

from sqlalchemy import select

from intric.database.database import sessionmanager
from intric.database.tables.tenant_table import Tenants
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.tenants.tenant_repo import TenantRepository

logger = get_logger(__name__)


async def backfill_slugs():
    """Generate slugs for all tenants missing them."""
    logger.info("Starting tenant slug backfill process...")

    # Initialize database session manager
    settings = get_settings()
    db_url = f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    sessionmanager.init(db_url)

    try:
        # Create session and repository
        async with sessionmanager.session() as session:
            async with session.begin():
                # Get all tenants (including those without slugs)
                stmt = select(Tenants)
                result = await session.execute(stmt)
                all_tenants = result.scalars().all()

                logger.info(f"Found {len(all_tenants)} total tenants")

                backfilled = 0
                skipped = 0
                errors = 0

                # Create repository instance for slug generation
                tenant_repo = TenantRepository(session=session, encryption_service=None)

                for tenant_row in all_tenants:
                    if not tenant_row.slug:
                        try:
                            slug = await tenant_repo.generate_slug_for_tenant(
                                tenant_row.id
                            )
                            logger.info(
                                f"Generated slug '{slug}' for tenant '{tenant_row.name}' (ID: {tenant_row.id})"
                            )
                            backfilled += 1
                        except Exception as e:
                            logger.error(
                                f"Failed to generate slug for tenant '{tenant_row.name}' (ID: {tenant_row.id}): {e}"
                            )
                            errors += 1
                    else:
                        logger.debug(
                            f"Tenant '{tenant_row.name}' already has slug '{tenant_row.slug}'"
                        )
                        skipped += 1

                logger.info(
                    f"Backfill complete: {backfilled} slugs generated, {skipped} already had slugs, {errors} errors"
                )

                if errors > 0:
                    logger.warning(
                        f"{errors} tenants failed slug generation - check logs above"
                    )

    finally:
        await sessionmanager.close()


def main():
    """Entry point for CLI script."""
    try:
        asyncio.run(backfill_slugs())
    except KeyboardInterrupt:
        logger.info("Backfill interrupted by user")
    except Exception as e:
        logger.error(f"Backfill failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
