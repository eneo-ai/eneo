"""Discard the separate window without changing declared input/output capacity."""

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def test_two_limit_capacity_round_trip(test_settings):
    backend = Path(__file__).parents[3]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    assert ScriptDirectory.from_config(config).get_heads() == ["202609171100"]
    command.upgrade(config, "202609161100")
    with psycopg2.connect(
        test_settings.sync_database_url.replace("postgresql+psycopg2", "postgresql")
    ) as connection:
        identities = [str(uuid4()) for _ in range(4)]
        values = [(100, 80), (None, 80), (100, None), (None, None)]
        with connection.cursor() as cursor:
            for identity, (input_tokens, output_tokens) in zip(identities, values):
                cursor.execute(
                    "INSERT INTO completion_models (id, name, nickname, max_input_tokens, max_output_tokens, context_window_tokens, family, stability, hosting, reasoning) VALUES (%s, %s, %s, %s, %s, 1000, 'openai', 'stable', 'usa', false)",
                    (identity, identity, identity, input_tokens, output_tokens),
                )
        connection.commit()
        command.upgrade(config, "head")
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'completion_models' AND column_name = 'context_window_tokens'"
            )
            assert cursor.fetchall() == []
            for identity, expected in zip(identities, values):
                cursor.execute(
                    "SELECT max_input_tokens, max_output_tokens FROM completion_models WHERE id = %s",
                    (identity,),
                )
                assert cursor.fetchone() == expected
        connection.commit()
        command.downgrade(config, "202609161100")
        with connection.cursor() as cursor:
            for identity, expected in zip(identities, values):
                cursor.execute(
                    "SELECT max_input_tokens, max_output_tokens, context_window_tokens FROM completion_models WHERE id = %s",
                    (identity,),
                )
                assert cursor.fetchone() == (*expected, None)
        connection.commit()
        command.upgrade(config, "head")
        command.upgrade(config, "head")
