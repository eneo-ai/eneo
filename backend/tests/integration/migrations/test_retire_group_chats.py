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
    "unavailable",
    [
        "disabled",
        "deleted",
        "deprecated",
        "no_tools",
        "no_alternative",
        "personal_unmapped",
        "below_class",
        "no_class",
        "enforcement_off",
        "not_mapped",
    ],
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
            "low",
            "high",
            "question",
            "foreign_tenant",
            "foreign_provider",
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
        classified = unavailable in {"below_class", "no_class", "enforcement_off"}
        if classified:
            connection.execute(
                sa.text("""
                INSERT INTO security_classifications (id, tenant_id, name, security_level)
                VALUES (:low, :tenant, 'Low', 1), (:high, :tenant, 'High', 2)
            """),
                ids,
            )
            connection.execute(
                sa.text(
                    "UPDATE spaces SET security_classification_id=:high WHERE id=:space"
                ),
                ids,
            )
            connection.execute(
                sa.text(
                    "UPDATE tenants SET security_enabled=:enabled WHERE id=:tenant"
                ),
                {**ids, "enabled": unavailable != "enforcement_off"},
            )
        if unavailable == "personal_unmapped":
            connection.execute(
                sa.text("UPDATE spaces SET user_id=:user WHERE id=:space"), ids
            )
            # Isolate this personal catalog from global model seeds in older revisions.
            connection.execute(
                sa.text(
                    "UPDATE completion_models SET is_enabled=false WHERE tenant_id IS NULL"
                )
            )
            connection.execute(
                sa.text("""
                INSERT INTO tenants (id, name, quota_limit, state)
                VALUES (:foreign_tenant, 'Other tenant', 1000000, 'active')
            """),
                ids,
            )
            connection.execute(
                sa.text("""
                INSERT INTO model_providers (id, tenant_id, name, provider_type, credentials)
                VALUES (:foreign_provider, :foreign_tenant, 'Tenant provider', 'openai', '{}')
            """),
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
            if classified:
                level = (
                    None
                    if unavailable == "no_class" and key == "old_model"
                    else (ids["high"] if key == "new_model" else ids["low"])
                )
                connection.execute(
                    sa.text(
                        "UPDATE completion_models SET security_classification_id=:level WHERE id=:model"
                    ),
                    {"level": level, "model": ids[key]},
                )
            if unavailable == "personal_unmapped":
                if key == "old_model":
                    connection.execute(
                        sa.text("""
                        UPDATE completion_models SET tenant_id=:foreign_tenant, provider_id=:foreign_provider WHERE id=:old_model
                    """),
                        ids,
                    )
                continue
            if key == "old_model" and unavailable == "not_mapped":
                continue
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
        connection.execute(
            sa.text("""
            INSERT INTO questions (id, tenant_id, session_id, question, answer, num_tokens_question, num_tokens_answer)
            VALUES (:question, :tenant, :session, 'Original question', 'Original answer', 2, 2)
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
            None
            if unavailable == "no_alternative"
            else ids["old_model"]
            if unavailable == "enforcement_off"
            else ids["new_model"]
        )
        assert assistant.metadata_json["migrated_from_group_chat"] is True
        session = connection.execute(
            sa.text("SELECT assistant_id, created_at FROM sessions WHERE id=:session"),
            ids,
        ).one()
        assert session.assistant_id == ids["group"]
        assert session.created_at.year == 2025
        assert connection.execute(
            sa.text("""
            SELECT question, answer, session_id FROM questions WHERE id=:question
        """),
            ids,
        ).one() == ("Original question", "Original answer", ids["session"])
        transaction.rollback()
