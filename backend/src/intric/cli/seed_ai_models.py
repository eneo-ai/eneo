"""Seed AI models from ai_models.yml configuration file.

This script loads completion and embedding models from the ai_models.yml file
and creates/updates them in the database. It provides backwards compatibility
for deployments that previously relied on auto-seeding at server startup.

The script is idempotent and safe to run multiple times:
- Creates new models that don't exist
- Updates existing models with new configuration
- Deletes models that are no longer in the config (same behavior as old auto-sync)

Usage:
    uv run python -m intric.cli.seed_ai_models

Note: This does NOT enable models for tenants. Admins must explicitly enable
models for each tenant via the API/UI.
"""

import asyncio

from intric.database.database import sessionmanager
from intric.main.config import get_settings
from intric.main.logging import get_logger
from intric.server.dependencies.ai_models import init_models

logger = get_logger(__name__)


async def seed_models():
    """Seed AI models from ai_models.yml configuration."""
    logger.info("Starting AI models seeding from ai_models.yml...")

    # Initialize database session manager
    settings = get_settings()
    db_url = f"postgresql+asyncpg://{settings.postgres_user}:{settings.postgres_password}@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    sessionmanager.init(db_url)

    try:
        # Run the existing init_models function
        await init_models()

        logger.info("✅ AI models seeding completed successfully")
        logger.info(
            "Note: Models have been created but are NOT enabled for any tenants. "
            "Use the /sysadmin API endpoints or UI to enable models for specific tenants."
        )

    except FileNotFoundError as e:
        logger.error(f"❌ Configuration file not found: {e}")
        logger.error("Make sure ai_models.yml exists in src/intric/server/dependencies/")
        raise
    except Exception as e:
        logger.error(f"❌ Seeding failed: {e}", exc_info=True)
        raise
    finally:
        await sessionmanager.close()


def main():
    """Entry point for CLI script."""
    try:
        asyncio.run(seed_models())
    except KeyboardInterrupt:
        logger.info("Seeding interrupted by user")
    except Exception as e:
        logger.error(f"Seeding failed: {e}")
        exit(1)


if __name__ == "__main__":
    main()
