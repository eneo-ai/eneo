"""Run retirement against persisted groups, including unavailable model choices."""

from collections.abc import Generator
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import Connection
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]


@pytest.fixture(scope="session", autouse=True)
def override_settings_for_session() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def cleanup_database() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Generator[None, None, None]:
    yield


@pytest.fixture(autouse=True)
def encryption_service() -> Generator[None, None, None]:
    yield


@pytest.fixture(scope="module")
def migration_database() -> Generator[tuple[Connection, Config], None, None]:
    backend = Path(__file__).resolve().parents[3]
    with PostgresContainer("pgvector/pgvector:pg16").with_kwargs(
        mem_limit="512m"
    ) as postgres:
        url = postgres.get_connection_url()
        config = Config(str(backend / "alembic.ini"))
        config.set_main_option("script_location", str(backend / "alembic"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "202610201100")
        engine = sa.create_engine(url)
        try:
            with engine.connect() as connection:
                yield connection, config
        finally:
            engine.dispose()


@pytest.mark.parametrize(
    "unavailable", ["disabled", "deleted", "deprecated", "no_tools", "no_alternative"]
)
def test_retirement_selects_an_available_tool_model_and_keeps_old_sessions(
    migration_database: tuple[Connection, Config], unavailable: str
) -> None:
    connection, config = migration_database
    ids = {
        key: uuid4()
        for key in (
            "tenant",
            "user",
            "space",
            "old_model",
            "new_model",
            "group",
            "session",
        )
    }
    with connection.begin() as transaction:
        connection.execute(
            sa.text(
                "INSERT INTO tenants (id, name, quota_limit, state) VALUES (:tenant, 'Migration tenant', 1000000, 'active')"
            ),
            ids,
        )
        connection.execute(
            sa.text(
                "INSERT INTO users (id, tenant_id, email, used_tokens, state) VALUES (:user, :tenant, 'migration@example.test', 0, 'active')"
            ),
            ids,
        )
        connection.execute(
            sa.text(
                "INSERT INTO spaces (id, tenant_id, name) VALUES (:space, :tenant, 'Migration space')"
            ),
            ids,
        )
        for key, enabled, deleted, deprecated, tools, created in (
            (
                "old_model",
                unavailable not in {"disabled", "no_alternative"},
                unavailable == "deleted",
                unavailable == "deprecated",
                unavailable != "no_tools",
                "2026-01-01",
            ),
            ("new_model", True, False, False, True, "2026-02-01"),
        ):
            if key == "new_model" and unavailable == "no_alternative":
                continue
            connection.execute(
                sa.text("""
                INSERT INTO completion_models (
                    id, name, nickname, family, stability, hosting,
                    max_input_tokens, max_output_tokens, reasoning, vision,
                    is_enabled, deleted_at, is_deprecated, supports_tool_calling, created_at
                ) VALUES (
                    :id, :name, :name, 'openai', 'stable', 'europe', 8000, 4096, false, false,
                    :enabled, CASE WHEN :deleted THEN now() END, :deprecated, :tools, :created
                )
            """),
                {
                    "id": ids[key],
                    "name": key,
                    "tenant": ids["tenant"],
                    "enabled": enabled,
                    "deleted": deleted,
                    "deprecated": deprecated,
                    "tools": tools,
                    "created": created,
                },
            )
            connection.execute(
                sa.text(
                    "INSERT INTO spaces_completion_models (space_id, completion_model_id) VALUES (:space, :model)"
                ),
                {"space": ids["space"], "model": ids[key]},
            )
        connection.execute(
            sa.text("""
            INSERT INTO group_chats (id, name, space_id, user_id, allow_mentions,
                show_response_label, published, type, insight_enabled)
            VALUES (:group, 'Former group', :space, :user, false, false, true, 'group-chat', true)
        """),
            ids,
        )
        connection.execute(
            sa.text("""
            INSERT INTO sessions (id, name, user_id, group_chat_id, created_at)
            VALUES (:session, 'Old conversation', :user, :group, '2025-01-01T00:00:00Z')
        """),
            ids,
        )
        revision = ScriptDirectory.from_config(config).get_revision("202610221200")
        assert revision is not None
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.upgrade()
        assistant = connection.execute(
            sa.text(
                "SELECT completion_model_id, metadata_json FROM assistants WHERE id=:group"
            ),
            ids,
        ).one()
        assert assistant.completion_model_id == (
            None if unavailable == "no_alternative" else ids["new_model"]
        )
        assert assistant.metadata_json["migrated_from_group_chat"] is True
        session = connection.execute(
            sa.text("SELECT assistant_id, created_at FROM sessions WHERE id=:session"),
            ids,
        ).one()
        assert session.assistant_id == ids["group"]
        assert session.created_at.year == 2025
        transaction.rollback()
