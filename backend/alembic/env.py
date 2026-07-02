from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# Import for autocompletion
import eneo.database.tables  # noqa
from alembic import context

# Add your model's MetaData object here
# for 'autogenerate' support
from eneo.database.tables.base_class import Base  # noqa
from eneo.main.config import get_settings

# Alembic Config object, which provides access to values within the .ini file
config = context.config

# Interpret the config file for logging
fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _migration_database_url() -> str:
    configured_url = config.get_main_option("sqlalchemy.url")
    if configured_url:
        return configured_url

    settings = get_settings()
    if settings.testing:
        print("Running migration for test_database")
        return f"{settings.sync_database_url}_test"
    return settings.sync_database_url


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode
    """

    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = _migration_database_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, compare_type=True
        )

        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    """

    context.configure(
        url=_migration_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
