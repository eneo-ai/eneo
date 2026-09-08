from pathlib import Path

import psycopg2
import pytest

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


def test_pause_revision_preserves_admission_generation(
    object_content_database, object_content_postgres_13
):
    backend = Path(__file__).resolve().parents[3]
    config = Config(str(backend / "alembic.ini"))
    url = object_content_postgres_13.get_connection_url()
    config.set_main_option("sqlalchemy.url", url)
    connection = psycopg2.connect(url.replace("postgresql+psycopg2", "postgresql"))
    connection.autocommit = True
    try:
        command.downgrade(config, "202609041000")
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE file_icon_backfill_admission_state SET generation = 42"
            )
        command.upgrade(config, "202609071000")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT generation, paused FROM file_icon_backfill_admission_state"
            )
            assert cursor.fetchone() == (42, False)
            cursor.execute(
                "UPDATE file_icon_backfill_admission_state SET paused = true"
            )
        command.upgrade(config, "202609071000")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT generation, paused FROM file_icon_backfill_admission_state"
            )
            assert cursor.fetchone() == (42, True)
        command.downgrade(config, "202609041000")
        with connection.cursor() as cursor:
            cursor.execute("SELECT generation FROM file_icon_backfill_admission_state")
            assert cursor.fetchone() == (42,)
    finally:
        command.upgrade(config, "head")
        connection.close()
