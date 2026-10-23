"""Round trip for 202610121300: the CHECK on flow_steps.input_source.

    pytest -m migration_isolation \
        tests/integration/migrations/test_flow_tool_input_source_round_trip.py
"""

from __future__ import annotations

import threading
from pathlib import Path

import psycopg2
import psycopg2.errors
import pytest
import sqlalchemy as sa

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import at_revision

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610111900"
REVISION = "202610121300"


@pytest.fixture(autouse=True)
def cleanup_database():
    """Keep the schema revision across the cycle within this module."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _input_source_check(conn) -> tuple[bool, bool]:
    """Whether the CHECK admits 'tool', and whether PostgreSQL validated it."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid), convalidated FROM pg_constraint "
            "WHERE conname = 'ck_flow_steps_input_source'"
        )
        ((definition, validated),) = cur.fetchall()
        return "'tool'" in definition, validated


def _store_a_tool_step(conn) -> None:
    # The step's flow, tenant and assistant are not what is tested: without
    # the foreign-key triggers the row needs none. A CHECK is no trigger.
    with conn.cursor() as cur:
        cur.execute("SET session_replication_role = replica")
        cur.execute(
            "INSERT INTO flow_steps (flow_id, tenant_id, assistant_id, step_order, "
            "input_source, input_type, output_mode, output_type) VALUES "
            "(gen_random_uuid(), gen_random_uuid(), gen_random_uuid(), 1, "
            "'tool', 'text', 'pass_through', 'text')"
        )
        cur.execute("SET session_replication_role = DEFAULT")


def _downgrade_stops_at_a_held_lock(cfg: Config, test_settings) -> None:
    # Kills the mutant where the downgrade's count of 'tool' steps runs before
    # its lock_timeout: it would wait for the lock with no bound. If it waits,
    # the lock is released after 20 s so that the test fails instead of hanging.
    holder = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    outcome: list[BaseException | None] = []

    def downgrade() -> None:
        try:
            command.downgrade(cfg, PRE_REVISION)
        except BaseException as exc:  # handed to the test thread
            outcome.append(exc)
        else:
            outcome.append(None)

    try:
        with holder.cursor() as cur:
            cur.execute("LOCK TABLE flow_steps IN ACCESS EXCLUSIVE MODE")
        worker = threading.Thread(target=downgrade)
        worker.start()
        worker.join(timeout=20)
        stopped_in_time = not worker.is_alive()
    finally:
        holder.rollback()
        holder.close()
    worker.join()
    assert stopped_in_time
    (error,) = outcome
    assert isinstance(error, sa.exc.OperationalError)
    assert isinstance(error.orig, psycopg2.errors.LockNotAvailable)


def test_the_input_source_check_gains_and_loses_the_tool_value(test_settings):
    # Kills the mutants where either direction leaves the CHECK absent, not
    # validated or with the other direction's values on a real database, where
    # the downgrade starts although a step holds 'tool' (it would end in a raw
    # CHECK violation with the narrower check half installed), or where the
    # refusal has already changed the check.
    cfg = Config(str(Path(__file__).parents[3] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    try:
        with at_revision(cfg, REVISION):
            try:
                assert _input_source_check(conn) == (True, True)
                _store_a_tool_step(conn)

                _downgrade_stops_at_a_held_lock(cfg, test_settings)
                assert _input_source_check(conn) == (True, True)

                with pytest.raises(RuntimeError, match="1 flow step"):
                    command.downgrade(cfg, PRE_REVISION)
                assert _input_source_check(conn) == (True, True)

                with conn.cursor() as cur:
                    cur.execute("DELETE FROM flow_steps WHERE input_source = 'tool'")
                command.downgrade(cfg, PRE_REVISION)
                assert _input_source_check(conn) == (False, True)

                command.upgrade(cfg, REVISION)
                assert _input_source_check(conn) == (True, True)
            finally:
                with conn.cursor() as cur:
                    cur.execute("SET session_replication_role = replica")
                    cur.execute("DELETE FROM flow_steps WHERE input_source = 'tool'")
                    cur.execute("SET session_replication_role = DEFAULT")
    finally:
        conn.close()
