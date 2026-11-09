"""Audit rows written before this version lose the file and conversation
names they copied, and keep who, what, when and which object.

A file row named the file in its description and target, an upload to a
collection named it in its target, three conversation routes named the
conversation in their target, and an assistant update named its attachments.
Those names copy text that retention removes, so the upgrade removes every
copy, in batches.
"""

from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy.exc import DBAPIError
from testcontainers.postgres import PostgresContainer

from alembic import command
from alembic.config import Config
from eneo.audit.domain.action_types import ActionType
from eneo.audit.domain.removable_names import (
    COLLECTION_UPLOAD_DESCRIPTION,
    FILE_DESCRIPTIONS,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_POSTGRES_13_IMAGE = (
    "pgvector/pgvector:pg13@"
    "sha256:751a89c96f7c32cb8133472f711c274853378fb5f8b55dd9fa0e9d3f1471bfc3"
)
_PREVIOUS_REVISION = "202611090600"

NAME = "Utredning Anna Svensson.pdf"
TITLE = "Can my neighbour read my medical records"
# More file rows than one batch of the upgrade.
_FILE_ROWS = 5_001
_BATCH_ROWS = 5_000
# The actions whose rows the upgrade reads, in its batches by id.
_REWRITTEN_ACTIONS = [
    *(action.value for action in FILE_DESCRIPTIONS),
    ActionType.MCP_APP_TOOL_CALLED.value,
    ActionType.DOCUMENT_EXPORTED.value,
    ActionType.DOCUMENT_VERSION_SAVED.value,
    ActionType.ASSISTANT_UPDATED.value,
]


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


def _connect(database_url: str):
    return psycopg2.connect(database_url.replace("+psycopg2", ""))


def _written_rows() -> dict[str, tuple[ActionType, str, dict[str, Any]]]:
    """Each old form, by row id: action, description and metadata."""
    actor = {"id": str(uuid4()), "name": "anna", "email": "anna@example.test"}
    rows: dict[str, tuple[ActionType, str, dict[str, Any]]] = {}
    for action in FILE_DESCRIPTIONS:
        file_id = str(uuid4())
        rows[str(uuid4())] = (
            action,
            f"Original file '{NAME}' accessed with a signed link",
            {
                "actor": actor,
                "target": {"id": file_id, "name": NAME},
                "extra": {"size_bytes": 7, "mimetype": "application/pdf"},
            },
        )
    group_id = str(uuid4())
    rows[str(uuid4())] = (
        ActionType.FILE_UPLOADED,
        f"Uploaded file '{NAME}' to collection/group",
        {
            "actor": actor,
            "target": {
                "group_id": group_id,
                "group_name": "Policies",
                "filename": NAME,
                "content_type": "application/pdf",
            },
        },
    )
    rows[str(uuid4())] = (
        ActionType.FILE_UPLOADED,
        "Added 2 info blobs to collection/group",
        {
            "actor": actor,
            "target": {
                "group_id": group_id,
                "group_name": "Policies",
                "blobs_count": 2,
            },
        },
    )
    for action in (
        ActionType.MCP_APP_TOOL_CALLED,
        ActionType.DOCUMENT_EXPORTED,
        ActionType.DOCUMENT_VERSION_SAVED,
    ):
        session_id = str(uuid4())
        rows[str(uuid4())] = (
            action,
            "Exported a document as docx",
            {
                "actor": actor,
                "target": {"id": session_id, "name": TITLE},
                "extra": {"session_id": session_id},
            },
        )
    rows[str(uuid4())] = (
        ActionType.ASSISTANT_UPDATED,
        "Updated assistant 'Case support': knowledge sources",
        {
            "actor": actor,
            "target": {"id": str(uuid4()), "name": "Case support"},
            "changes": {
                "knowledge_sources": {
                    "collections": {
                        "added": [
                            {"id": group_id, "name": "Policies", "scope": "space"}
                        ]
                    },
                    "attachments": {
                        "added": [{"id": "a", "name": NAME, "scope": "space"}],
                        "removed": [{"id": "r", "name": NAME}],
                        "mode_changed": [{"id": "m", "name": NAME, "mode": "lookup"}],
                    },
                }
            },
        },
    )
    rows[str(uuid4())] = (
        ActionType.SPACE_UPDATED,
        "Updated space 'Social services'",
        {"actor": actor, "target": {"id": str(uuid4()), "name": "Social services"}},
    )
    return rows


def _insert(database_url: str, rows: dict[str, tuple[ActionType, str, dict[str, Any]]]):
    tenant_id, user_id = str(uuid4()), str(uuid4())
    connection = _connect(database_url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO tenants (id, name, quota_limit, state) "
                "VALUES (%s, %s, 1000000, 'active')",
                (tenant_id, f"audit-names-{uuid4().hex[:8]}"),
            )
            cursor.execute(
                "INSERT INTO users (id, tenant_id, username, email, used_tokens, state) "
                "VALUES (%s, %s, %s, %s, 0, 'active')",
                (
                    user_id,
                    tenant_id,
                    f"audit-names-{uuid4().hex[:8]}",
                    f"audit-names-{uuid4().hex[:12]}@example.test",
                ),
            )
            for row_id, (action, description, metadata) in rows.items():
                cursor.execute(
                    "INSERT INTO audit_logs (id, tenant_id, actor_id, action, "
                    "entity_type, entity_id, timestamp, description, metadata) "
                    "VALUES (%s, %s, %s, %s, 'file', %s, "
                    "'2026-01-01T00:00:00Z', %s, %s)",
                    (
                        row_id,
                        tenant_id,
                        user_id,
                        action.value,
                        str(uuid4()),
                        description,
                        json.dumps(metadata),
                    ),
                )
            cursor.execute(
                "INSERT INTO audit_logs (tenant_id, actor_id, action, entity_type, "
                "entity_id, description, metadata) "
                "SELECT %s, %s, 'file_signed_url_minted', 'file', gen_random_uuid(), "
                "%s, jsonb_build_object('target', jsonb_build_object("
                "'id', gen_random_uuid(), 'name', %s::text)) "
                "FROM generate_series(1, %s)",
                (
                    tenant_id,
                    user_id,
                    f"Minted signed URL for file '{NAME}' for LLM/MCP context",
                    NAME,
                    _FILE_ROWS,
                ),
            )
    finally:
        connection.close()


def _stored(database_url: str) -> dict[str, tuple[str, str, str, dict[str, Any]]]:
    connection = _connect(database_url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id::text, actor_id::text, timestamp::text, description, "
                "metadata FROM audit_logs"
            )
            return {
                row_id: (actor_id, at, description, metadata)
                for row_id, actor_id, at, description, metadata in cursor.fetchall()
            }
    finally:
        connection.close()


def _interrupt_after_first_batch(database_url: str) -> str:
    """Make the upgrade fail on the first row past its first batch, so that
    batch is committed and the rest is not; the last id of that batch."""
    connection = _connect(database_url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT id::text FROM audit_logs WHERE action = ANY(%s) "
                "ORDER BY id OFFSET %s LIMIT 1",
                (_REWRITTEN_ACTIONS, _BATCH_ROWS - 1),
            )
            (boundary,) = cursor.fetchone()
            cursor.execute(
                "CREATE FUNCTION interrupt_upgrade() RETURNS trigger "
                "LANGUAGE plpgsql AS $$ BEGIN "
                "RAISE EXCEPTION 'upgrade interrupted'; END $$"
            )
            cursor.execute(
                "CREATE TRIGGER interrupt_upgrade BEFORE UPDATE ON audit_logs "
                f"FOR EACH ROW WHEN (OLD.id > '{boundary}'::uuid) "
                "EXECUTE FUNCTION interrupt_upgrade()"
            )
        return boundary
    finally:
        connection.close()


def _allow_upgrade(database_url: str) -> None:
    connection = _connect(database_url)
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("DROP TRIGGER interrupt_upgrade ON audit_logs")
            cursor.execute("DROP FUNCTION interrupt_upgrade()")
    finally:
        connection.close()


def _expected(
    action: ActionType, description: str, metadata: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    target = metadata["target"]
    if action in FILE_DESCRIPTIONS and "group_id" not in target:
        return FILE_DESCRIPTIONS[action], {
            **metadata,
            "target": {**target, "name": "file"},
        }
    if "filename" in target:
        return COLLECTION_UPLOAD_DESCRIPTION, {
            **metadata,
            "target": {
                key: value for key, value in target.items() if key != "filename"
            },
        }
    if action is ActionType.ASSISTANT_UPDATED:
        attachments = {
            "added": [{"id": "a", "scope": "space"}],
            "removed": [{"id": "r"}],
            "mode_changed": [{"id": "m", "mode": "lookup"}],
        }
        sources = metadata["changes"]["knowledge_sources"]
        return description, {
            **metadata,
            "changes": {"knowledge_sources": {**sources, "attachments": attachments}},
        }
    if "session_id" in metadata.get("extra", {}):
        return description, {**metadata, "target": {**target, "name": "conversation"}}
    return description, metadata


def test_names_are_removed_from_audit_rows_on_upgrade() -> None:
    """Mutants: a row past the first batch keeps its name; a file row keeps a
    variable description; a collection upload keeps its file name; a row of
    another action or one without a file name is rewritten; who or when
    changes; an upgrade interrupted after a committed batch and run again
    leaves a name or changes a row twice; the downgrade changes a row."""
    postgres = PostgresContainer(
        image=_POSTGRES_13_IMAGE,
        username="audit_names_migration",
        password="audit_names_migration_password",
        dbname="audit_names_migration",
    )
    with postgres:
        database_url = postgres.get_connection_url()
        config = _alembic_config(database_url)
        command.upgrade(config, _PREVIOUS_REVISION)
        written = _written_rows()
        _insert(database_url, written)
        before = _stored(database_url)

        boundary = _interrupt_after_first_batch(database_url)
        with pytest.raises(DBAPIError, match="upgrade interrupted"):
            command.upgrade(config, "head")
        interrupted = _stored(database_url)
        _allow_upgrade(database_url)
        command.upgrade(config, "head")
        after = _stored(database_url)
        command.downgrade(config, _PREVIOUS_REVISION)

        # The first batch was committed as it ends, and the rest was not.
        assert all(
            row == after[row_id]
            for row_id, row in interrupted.items()
            if row_id <= boundary
        )
        assert any(
            NAME in description + json.dumps(metadata)
            for row_id, (_, _, description, metadata) in interrupted.items()
            if row_id > boundary
        )

        assert _stored(database_url) == after
        assert len(after) == len(written) + _FILE_ROWS
        for row_id, (actor_id, at, description, metadata) in after.items():
            assert NAME not in description + json.dumps(metadata)
            assert TITLE not in json.dumps(metadata)
            assert (actor_id, at) == before[row_id][:2]
            if row_id in written:
                assert (description, metadata) == _expected(*written[row_id])
            else:
                assert (
                    description == FILE_DESCRIPTIONS[ActionType.FILE_SIGNED_URL_MINTED]
                )
                assert metadata["target"]["name"] == "file"
