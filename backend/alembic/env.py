from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

# Import for autocompletion
import intric.database.tables  # noqa
from alembic import context

# Add your model's MetaData object here
# for 'autogenerate' support
from intric.database.tables.base_class import Base  # noqa
from intric.main.config import get_settings

# Alembic Config object, which provides access to values within the .ini file
config = context.config

# Interpret the config file for logging
fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode
    """

    # handle testing config for migrations
    if get_settings().testing:
        print("Running migration for test_database")
        DB_URL = f"{get_settings().sync_database_url}_test"
    else:
        DB_URL = get_settings().sync_database_url

    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = str(DB_URL)
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
        url=get_settings().sync_database_url,
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
