"""``202611181200`` turns the flow authoring chat binding into the helper chat
binding of any target and back: the flow chats survive both ways, and the
downgrade removes the chats it has no place for with their assistants and
conversations."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, inspect
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.migration_isolation

_REVISION = "202611181200"
_PREVIOUS_REVISION = "202611111400"


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


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).resolve().parents[3]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def _schema(engine: sa.Engine, table: str) -> dict[str, object] | None:
    inspector = inspect(engine)
    if not inspector.has_table(table):
        return None
    return {
        "columns": {
            str(column["name"]): (column["nullable"], column["default"])
            for column in inspector.get_columns(table)
        },
        "primary_key": inspector.get_pk_constraint(table)["name"],
        "foreign_keys": sorted(
            (
                str(fk["name"]),
                tuple(fk["constrained_columns"]),
                fk["referred_table"],
                fk["options"].get("ondelete"),
            )
            for fk in inspector.get_foreign_keys(table)
        ),
        "unique": sorted(
            (str(constraint["name"]), tuple(constraint["column_names"]))
            for constraint in inspector.get_unique_constraints(table)
        ),
        "indexes": sorted(str(index["name"]) for index in inspector.get_indexes(table)),
    }


_COLUMNS = {
    "session_id": (False, None),
    "assistant_id": (False, None),
    "tenant_id": (False, None),
    "space_id": (False, None),
    "user_id": (False, None),
    "editing": (False, "false"),
    "created_at": (False, "now()"),
    "updated_at": (False, "now()"),
    "completion_model_id": (True, None),
    "reasoning_effort": (True, None),
    "mode_changed_at": (True, None),
}


def _foreign_keys(table: str) -> list[tuple[str, tuple[str, ...], str, str]]:
    return [
        (f"{table}_assistant_id_fkey", ("assistant_id",), "assistants", "CASCADE"),
        (
            f"{table}_completion_model_id_fkey",
            ("completion_model_id",),
            "completion_models",
            "SET NULL",
        ),
        (f"{table}_session_id_fkey", ("session_id",), "sessions", "CASCADE"),
        (f"{table}_space_id_fkey", ("space_id",), "spaces", "CASCADE"),
        (f"{table}_tenant_id_fkey", ("tenant_id",), "tenants", "CASCADE"),
        (f"{table}_user_id_fkey", ("user_id",), "users", "CASCADE"),
    ]


_FLOW_AUTHORING_CHATS = {
    "columns": {**_COLUMNS, "flow_id": (False, None)},
    "primary_key": "flow_authoring_chats_pkey",
    "foreign_keys": sorted(
        [
            *_foreign_keys("flow_authoring_chats"),
            ("flow_authoring_chats_flow_id_fkey", ("flow_id",), "flows", "CASCADE"),
        ]
    ),
    "unique": [
        ("flow_authoring_chats_assistant_id_key", ("assistant_id",)),
        ("uq_flow_authoring_chat_owner", ("tenant_id", "user_id", "flow_id")),
    ],
    "indexes": [
        "flow_authoring_chats_assistant_id_key",
        "ix_flow_authoring_chats_tenant_id",
        "uq_flow_authoring_chat_owner",
    ],
}

# The target is named by kind and id; the id has no foreign key.
_HELPER_CHATS = {
    "columns": {
        **_COLUMNS,
        "target_id": (False, None),
        "target_type": (False, None),
    },
    "primary_key": "helper_chats_pkey",
    "foreign_keys": _foreign_keys("helper_chats"),
    "unique": [
        ("helper_chats_assistant_id_key", ("assistant_id",)),
        (
            "uq_helper_chat_owner",
            ("tenant_id", "user_id", "target_type", "target_id"),
        ),
    ],
    "indexes": [
        "helper_chats_assistant_id_key",
        "ix_helper_chats_tenant_id",
        "uq_helper_chat_owner",
    ],
}


def _shapes(engine: sa.Engine) -> tuple[object, object]:
    return _schema(engine, "flow_authoring_chats"), _schema(engine, "helper_chats")


def _owner(connection: sa.Connection) -> dict[str, UUID]:
    """A tenant with a person, a space and a flow in it."""
    ids = {name: uuid4() for name in ("tenant", "user", "space", "flow")}
    connection.execute(
        sa.text(
            "INSERT INTO tenants (id, name, quota_limit, state) "
            "VALUES (:tenant, :name, 1000000, 'active')"
        ),
        {"tenant": ids["tenant"], "name": f"helper-chats-{ids['tenant'].hex[:8]}"},
    )
    connection.execute(
        sa.text(
            "INSERT INTO users (id, tenant_id, username, email, used_tokens, state) "
            "VALUES (:user, :tenant, :name, :email, 0, 'active')"
        ),
        {
            **ids,
            "name": f"helper-chats-{ids['user'].hex[:8]}",
            "email": f"helper-chats-{ids['user'].hex[:8]}@example.test",
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO spaces (id, tenant_id, name) "
            "VALUES (:space, :tenant, 'Hjälpchattar')"
        ),
        ids,
    )
    connection.execute(
        sa.text(
            "INSERT INTO flows (id, tenant_id, space_id, name) "
            "VALUES (:flow, :tenant, :space, 'Ärendeflöde')"
        ),
        ids,
    )
    return ids


def _hidden_assistant_and_conversation(
    connection: sa.Connection, owner: dict[str, UUID]
) -> tuple[UUID, UUID]:
    assistant_id, session_id = uuid4(), uuid4()
    connection.execute(
        sa.text(
            "INSERT INTO assistants (id, user_id, space_id, name, logging_enabled, "
            "is_default, published, type, insight_enabled, hidden) "
            "VALUES (:assistant, :user, :space, 'Hjälp', false, false, false, "
            "'assistant', false, true)"
        ),
        {**owner, "assistant": assistant_id},
    )
    connection.execute(
        sa.text(
            "INSERT INTO sessions (id, name, user_id, assistant_id) "
            "VALUES (:session, 'Hjälp', :user, :assistant)"
        ),
        {**owner, "assistant": assistant_id, "session": session_id},
    )
    return assistant_id, session_id


def _existing(connection: sa.Connection, table: str, ids: list[UUID]) -> set[UUID]:
    return set(
        connection.execute(
            sa.text(f"SELECT id FROM {table} WHERE id = ANY(:ids)"), {"ids": ids}
        ).scalars()
    )


def test_helper_chats_upgrade_downgrade_and_reupgrade() -> None:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="helper_chats",
        password="helper_chats_password",
        dbname="helper_chats",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        engine = create_engine(database_url)
        try:
            command.upgrade(config, _PREVIOUS_REVISION)
            assert _shapes(engine) == (_FLOW_AUTHORING_CHATS, None)
            with engine.begin() as connection:
                owner = _owner(connection)
                kept_assistant, kept_session = _hidden_assistant_and_conversation(
                    connection, owner
                )
                connection.execute(
                    sa.text(
                        "INSERT INTO flow_authoring_chats (session_id, assistant_id, "
                        "tenant_id, space_id, user_id, flow_id, editing) "
                        "VALUES (:session, :assistant, :tenant, :space, :user, "
                        ":flow, true)"
                    ),
                    {**owner, "assistant": kept_assistant, "session": kept_session},
                )

            command.upgrade(config, _REVISION)
            assert _shapes(engine) == (None, _HELPER_CHATS)
            with engine.begin() as connection:
                assert connection.execute(
                    sa.text(
                        "SELECT target_type, target_id, editing FROM helper_chats "
                        "WHERE session_id = :session"
                    ),
                    {"session": kept_session},
                ).one() == ("flow", owner["flow"], True)
                # A chat on a target of another kind, and one whose flow is gone.
                gone = []
                for target_type, target_id in (
                    ("assistant", uuid4()),
                    ("flow", uuid4()),
                ):
                    assistant_id, session_id = _hidden_assistant_and_conversation(
                        connection, owner
                    )
                    connection.execute(
                        sa.text(
                            "INSERT INTO helper_chats (session_id, assistant_id, "
                            "tenant_id, space_id, user_id, target_type, target_id) "
                            "VALUES (:session, :assistant, :tenant, :space, :user, "
                            ":target_type, :target_id)"
                        ),
                        {
                            **owner,
                            "assistant": assistant_id,
                            "session": session_id,
                            "target_type": target_type,
                            "target_id": target_id,
                        },
                    )
                    gone.append((assistant_id, session_id))

            command.downgrade(config, _PREVIOUS_REVISION)
            assert _shapes(engine) == (_FLOW_AUTHORING_CHATS, None)
            gone_assistants = [assistant for assistant, _ in gone]
            gone_sessions = [session for _, session in gone]
            with engine.begin() as connection:
                assert connection.execute(
                    sa.text("SELECT session_id, flow_id FROM flow_authoring_chats")
                ).all() == [(kept_session, owner["flow"])]
                assert _existing(
                    connection, "assistants", [kept_assistant, *gone_assistants]
                ) == {kept_assistant}
                assert _existing(
                    connection, "sessions", [kept_session, *gone_sessions]
                ) == {kept_session}

            command.upgrade(config, _REVISION)
            assert _shapes(engine) == (None, _HELPER_CHATS)
        finally:
            engine.dispose()
