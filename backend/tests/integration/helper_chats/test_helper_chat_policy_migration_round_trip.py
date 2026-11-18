"""``202611182000`` seeds the helper chat's organisation settings from the
prompt guide once: a guide that is off or hidden turns the helper chat off, and
a guide's tool-calling model becomes the default where none is set. The
downgrade takes back what the seed wrote and leaves what an administrator set
since."""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from testcontainers.community.postgres import PostgresContainer

from alembic import command
from alembic.config import Config

pytestmark = pytest.mark.migration_isolation

_REVISION = "202611182000"
_PREVIOUS_REVISION = "202611181200"


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


def _tenant(connection: sa.Connection, flow_settings: dict[str, Any]) -> UUID:
    tenant_id = uuid4()
    connection.execute(
        sa.text(
            "INSERT INTO tenants (id, name, quota_limit, state, flow_settings) "
            "VALUES (:id, :name, 1000000, 'active', CAST(:settings AS jsonb))"
        ),
        {
            "id": tenant_id,
            "name": f"helper-chat-policy-{tenant_id.hex[:8]}",
            "settings": json.dumps(flow_settings),
        },
    )
    return tenant_id


def _model(
    connection: sa.Connection, tenant_id: UUID, *, tools: bool, enabled: bool = True
) -> UUID:
    """A model of the tenant's own, through a provider of its own."""
    model_id, provider_id = uuid4(), uuid4()
    connection.execute(
        sa.text(
            "INSERT INTO model_providers (id, tenant_id, name, provider_type, "
            "credentials) VALUES (:id, :tenant, :name, 'generic', '{}'::jsonb)"
        ),
        {"id": provider_id, "tenant": tenant_id, "name": f"p-{provider_id.hex[:8]}"},
    )
    connection.execute(
        sa.text(
            "INSERT INTO completion_models (id, name, nickname, max_input_tokens, "
            "max_output_tokens, family, stability, hosting, reasoning, "
            "supports_tool_calling, is_enabled, tenant_id, provider_id) "
            "VALUES (:id, :name, :name, 128000, 4096, 'generic', 'stable', 'eu', "
            "false, :tools, :enabled, :tenant, :provider)"
        ),
        {
            "id": model_id,
            "name": f"model-{model_id.hex[:8]}",
            "tools": tools,
            "enabled": enabled,
            "tenant": tenant_id,
            "provider": provider_id,
        },
    )
    return model_id


def _guide(
    connection: sa.Connection,
    tenant_id: UUID,
    *,
    model_id: UUID | None,
    enabled: bool = True,
    visible: bool = True,
) -> UUID:
    """The tenant's organisation space with a prompt guide whose assistant
    answers with ``model_id``."""
    space_id, user_id, assistant_id, role_id = uuid4(), uuid4(), uuid4(), uuid4()
    connection.execute(
        sa.text(
            "INSERT INTO users (id, tenant_id, username, email, used_tokens, state) "
            "VALUES (:user, :tenant, :name, :email, 0, 'active')"
        ),
        {
            "user": user_id,
            "tenant": tenant_id,
            "name": f"guide-{user_id.hex[:8]}",
            "email": f"guide-{user_id.hex[:8]}@example.test",
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO spaces (id, tenant_id, name) "
            "VALUES (:space, :tenant, 'Organisation')"
        ),
        {"space": space_id, "tenant": tenant_id},
    )
    connection.execute(
        sa.text(
            "INSERT INTO assistants (id, user_id, space_id, name, logging_enabled, "
            "is_default, published, type, insight_enabled, hidden, "
            "completion_model_id) "
            "VALUES (:assistant, :user, :space, 'Promptguide', false, false, "
            "false, 'assistant', false, false, :model)"
        ),
        {
            "assistant": assistant_id,
            "user": user_id,
            "space": space_id,
            "model": model_id,
        },
    )
    connection.execute(
        sa.text(
            "INSERT INTO org_space_assistant_roles (id, org_space_id, kind, "
            "assistant_id, is_enabled, is_visible_to_users) "
            "VALUES (:role, :space, 'prompt_guide', :assistant, :enabled, :visible)"
        ),
        {
            "role": role_id,
            "space": space_id,
            "assistant": assistant_id,
            "enabled": enabled,
            "visible": visible,
        },
    )
    return role_id


def _settings(connection: sa.Connection, tenant_ids: dict[str, UUID]) -> dict:
    rows = connection.execute(
        sa.text("SELECT id, flow_settings FROM tenants WHERE id = ANY(:ids)"),
        {"ids": list(tenant_ids.values())},
    ).all()
    by_id = {row.id: row.flow_settings for row in rows}
    return {name: by_id[tenant_id] for name, tenant_id in tenant_ids.items()}


def _roles(connection: sa.Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in connection.execute(
            sa.text(
                "SELECT id, org_space_id, kind, assistant_id, is_enabled, "
                "is_visible_to_users, updated_at FROM org_space_assistant_roles "
                "ORDER BY id"
            )
        ).all()
    ]


def test_the_seed_upgrades_downgrades_and_upgrades_again() -> None:
    postgres = PostgresContainer(
        image="pgvector/pgvector:pg16",
        username="helper_chat_policy",
        password="helper_chat_policy_password",
        dbname="helper_chat_policy",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        engine = create_engine(database_url)
        try:
            command.upgrade(config, _PREVIOUS_REVISION)
            runtime = {"runtime_policy": {"version": 1, "max_concurrent_runs": 2}}
            with engine.begin() as connection:
                tenants = {
                    name: _tenant(connection, runtime)
                    for name in (
                        "guide_off",
                        "guide_hidden",
                        "guide_model",
                        "guide_off_with_model",
                        "default_already_set",
                        "model_without_tools",
                        "model_turned_off",
                        "no_guide",
                    )
                }
                models = {
                    name: _model(connection, tenants[name], tools=True)
                    for name in (
                        "guide_model",
                        "guide_off_with_model",
                        "default_already_set",
                    )
                }
                admins_model = _model(
                    connection, tenants["default_already_set"], tools=True
                )
                admins_later_model = _model(
                    connection, tenants["guide_off_with_model"], tools=True
                )
                connection.execute(
                    sa.text(
                        "UPDATE tenants SET flow_settings = CAST(:settings AS jsonb) "
                        "WHERE id = :id"
                    ),
                    {
                        "id": tenants["default_already_set"],
                        "settings": json.dumps(
                            {
                                **runtime,
                                "authoring_chat": {
                                    "completion_model_id": str(admins_model)
                                },
                            }
                        ),
                    },
                )
                _guide(
                    connection,
                    tenants["guide_off"],
                    enabled=False,
                    model_id=_model(connection, tenants["guide_off"], tools=False),
                )
                _guide(
                    connection, tenants["guide_hidden"], visible=False, model_id=None
                )
                _guide(
                    connection, tenants["guide_model"], model_id=models["guide_model"]
                )
                _guide(
                    connection,
                    tenants["guide_off_with_model"],
                    enabled=False,
                    visible=False,
                    model_id=models["guide_off_with_model"],
                )
                _guide(
                    connection,
                    tenants["default_already_set"],
                    model_id=models["default_already_set"],
                )
                _guide(
                    connection,
                    tenants["model_without_tools"],
                    model_id=_model(
                        connection, tenants["model_without_tools"], tools=False
                    ),
                )
                _guide(
                    connection,
                    tenants["model_turned_off"],
                    model_id=_model(
                        connection,
                        tenants["model_turned_off"],
                        tools=True,
                        enabled=False,
                    ),
                )
                before = _settings(connection, tenants)
                roles = _roles(connection)

            command.upgrade(config, _REVISION)
            seeded_model = str(models["guide_model"])
            seeded_off_model = str(models["guide_off_with_model"])
            seeded = {
                **before,
                "guide_off": {**runtime, "helper_chat": {"enabled": False}},
                "guide_hidden": {**runtime, "helper_chat": {"enabled": False}},
                "guide_model": {
                    **runtime,
                    "authoring_chat": {"completion_model_id": seeded_model},
                    "helper_chat": {"seeded_completion_model_id": seeded_model},
                },
                "guide_off_with_model": {
                    **runtime,
                    "authoring_chat": {"completion_model_id": seeded_off_model},
                    "helper_chat": {
                        "enabled": False,
                        "seeded_completion_model_id": seeded_off_model,
                    },
                },
            }
            with engine.begin() as connection:
                assert _settings(connection, tenants) == seeded
                assert _roles(connection) == roles
                # An administrator then sets a default model of their own and
                # writes guidance.
                connection.execute(
                    sa.text(
                        "UPDATE tenants SET flow_settings = CAST(:settings AS jsonb) "
                        "WHERE id = :id"
                    ),
                    {
                        "id": tenants["guide_off_with_model"],
                        "settings": json.dumps(
                            {
                                **runtime,
                                "authoring_chat": {
                                    "completion_model_id": str(admins_later_model)
                                },
                                "helper_chat": {
                                    "enabled": False,
                                    "guidance": "Tilltala alltid personen med du.",
                                },
                            }
                        ),
                    },
                )

            command.downgrade(config, _PREVIOUS_REVISION)
            with engine.begin() as connection:
                assert _settings(connection, tenants) == {
                    **before,
                    "guide_off_with_model": {
                        **runtime,
                        "authoring_chat": {
                            "completion_model_id": str(admins_later_model)
                        },
                    },
                }
                assert _roles(connection) == roles

            command.upgrade(config, _REVISION)
            with engine.begin() as connection:
                assert _settings(connection, tenants) == {
                    **seeded,
                    "guide_off_with_model": {
                        **runtime,
                        "authoring_chat": {
                            "completion_model_id": str(admins_later_model)
                        },
                        "helper_chat": {"enabled": False},
                    },
                }
                assert _roles(connection) == roles
        finally:
            engine.dispose()
