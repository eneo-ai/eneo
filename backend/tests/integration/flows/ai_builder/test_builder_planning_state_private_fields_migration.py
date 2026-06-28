"""Migration tests for removing private builder PlanningState fields.

Run explicitly:
    pytest -m migration_isolation tests/integration/flows/ai_builder/test_builder_planning_state_private_fields_migration.py -q
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple, cast
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extensions import connection as PsycopgConnection

from alembic import command
from alembic.config import Config

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRIOR_REVISION = "202606281300"
MIGRATION_REVISION = "202606281530_builder_state"
_TENANT_NAME_PREFIX = "builder-planning-state-private-fields-"

_OLD_PLANNING_STATE: dict[str, object] = {
    "fcm_version": 1,
    "planner_contract_version": 1,
    "builder_schema_version": 1,
    "phase": "plan_proposed",
    "evidence": {
        "conversation_message_ids": ["msg-1"],
        "attachment_digest_hashes": ["a" * 64],
        "raw_prompt_hash": "b" * 64,
    },
    "signals": [
        {
            "question_id": "result_obligations",
            "value": "risks",
            "confidence": "high",
            "source": "model",
            "provenance": ["model:result_obligations"],
        }
    ],
    "resolved_slots": {
        "primary_runtime_input": {
            "name": "primary_runtime_input",
            "value": "documents",
            "source": "heuristic",
            "evidence": ["heuristic:role-aware freeform analysis"],
            "confidence": "medium",
        }
    },
    "architecture_commit": None,
}

_DOWNGRADE_DEFAULT_EVIDENCE = {
    "conversation_message_ids": [],
    "attachment_digest_hashes": [],
    "raw_prompt_hash": "",
}
_CLEAN_PLANNING_STATE = {
    key: value
    for key, value in _OLD_PLANNING_STATE.items()
    if key not in {"phase", "evidence"}
}


class MigrationDb(NamedTuple):
    conn: PsycopgConnection
    cfg: Config


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database() -> Iterator[None]:
    """Shadow global cleanup; this test owns schema state while replaying Alembic."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models() -> Iterator[None]:
    """Shadow global model seeding; migrations under test create their own rows."""
    yield


@pytest.fixture
def migration_db(test_settings) -> Iterator[MigrationDb]:
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True

    command.upgrade(cfg, "head")
    command.downgrade(cfg, PRIOR_REVISION)
    _clear_seeded_rows(conn)

    try:
        yield MigrationDb(conn=conn, cfg=cfg)
    finally:
        command.upgrade(cfg, "head")
        _clear_seeded_rows(conn)
        conn.close()


def test_private_phase_and_root_evidence_keys_are_stripped_and_restored(
    migration_db: MigrationDb,
) -> None:
    session_id = _insert_builder_session(
        migration_db.conn,
        planning_state=_OLD_PLANNING_STATE,
    )

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    upgraded = _planning_state_payload(migration_db.conn, session_id)

    assert "phase" not in upgraded
    assert "evidence" not in upgraded
    assert upgraded["fcm_version"] == _OLD_PLANNING_STATE["fcm_version"]
    assert upgraded["planner_contract_version"] == (
        _OLD_PLANNING_STATE["planner_contract_version"]
    )
    assert upgraded["builder_schema_version"] == (
        _OLD_PLANNING_STATE["builder_schema_version"]
    )
    assert upgraded["signals"] == _OLD_PLANNING_STATE["signals"]
    assert upgraded["resolved_slots"] == _OLD_PLANNING_STATE["resolved_slots"]
    assert upgraded["architecture_commit"] is None

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)
    assert _planning_state_payload(migration_db.conn, session_id) == upgraded

    command.downgrade(migration_db.cfg, PRIOR_REVISION)
    downgraded = _planning_state_payload(migration_db.conn, session_id)

    assert downgraded["phase"] == "awaiting_input"
    assert downgraded["evidence"] == _DOWNGRADE_DEFAULT_EVIDENCE
    assert downgraded["fcm_version"] == _OLD_PLANNING_STATE["fcm_version"]
    assert downgraded["planner_contract_version"] == (
        _OLD_PLANNING_STATE["planner_contract_version"]
    )
    assert downgraded["builder_schema_version"] == (
        _OLD_PLANNING_STATE["builder_schema_version"]
    )
    assert downgraded["signals"] == _OLD_PLANNING_STATE["signals"]
    assert downgraded["resolved_slots"] == _OLD_PLANNING_STATE["resolved_slots"]
    assert downgraded["architecture_commit"] is None


def test_upgrade_preserves_null_and_already_clean_planning_state(
    migration_db: MigrationDb,
) -> None:
    null_session_id = _insert_builder_session(
        migration_db.conn,
        planning_state=None,
    )
    clean_session_id = _insert_builder_session(
        migration_db.conn,
        planning_state=_CLEAN_PLANNING_STATE,
    )

    command.upgrade(migration_db.cfg, MIGRATION_REVISION)

    assert _raw_planning_state_payload(migration_db.conn, null_session_id) is None
    assert _planning_state_payload(migration_db.conn, clean_session_id) == (
        _CLEAN_PLANNING_STATE
    )


def _insert_builder_session(
    conn: PsycopgConnection,
    *,
    planning_state: dict[str, object] | None,
) -> str:
    tenant_id = uuid4()
    user_id = uuid4()
    space_id = uuid4()
    session_id = uuid4()
    tenant_name = f"{_TENANT_NAME_PREFIX}{tenant_id}"

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (
                id,
                name,
                display_name,
                slug,
                quota_limit,
                privacy_policy,
                domain,
                zitadel_org_id,
                provisioning,
                security_enabled,
                state
            )
            VALUES (%s, %s, %s, %s, %s, NULL, NULL, NULL, false, false, 'active')
            """,
            (tenant_id, tenant_name, tenant_name, tenant_name[:63], 100000),
        )
        cur.execute(
            """
            INSERT INTO users (
                id,
                username,
                email,
                email_verified,
                salt,
                password,
                is_active,
                state,
                used_tokens,
                tenant_id,
                quota_limit
            )
            VALUES (%s, %s, %s, true, NULL, NULL, true, 'active', 0, %s, NULL)
            """,
            (user_id, f"user-{user_id}", f"{user_id}@example.test", tenant_id),
        )
        cur.execute(
            """
            INSERT INTO spaces (id, name, tenant_id, user_id)
            VALUES (%s, %s, %s, NULL)
            """,
            (space_id, f"Builder Planning State {space_id}", tenant_id),
        )
        cur.execute(
            """
            INSERT INTO builder_sessions (
                id,
                tenant_id,
                space_id,
                target_kind,
                status,
                actor_user_id,
                conversation,
                planning_state_jsonb,
                planning_state_version
            )
            VALUES (%s, %s, %s, 'create', 'chatting', %s, '[]'::jsonb, %s::jsonb, 7)
            """,
            (
                session_id,
                tenant_id,
                space_id,
                user_id,
                json.dumps(planning_state) if planning_state is not None else None,
            ),
        )

    return str(session_id)


def _planning_state_payload(
    conn: PsycopgConnection,
    session_id: str,
) -> dict[str, object]:
    payload = _raw_planning_state_payload(conn, session_id)
    assert isinstance(payload, dict)
    return cast(dict[str, object], payload)


def _raw_planning_state_payload(
    conn: PsycopgConnection,
    session_id: str,
) -> object:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT planning_state_jsonb
            FROM builder_sessions
            WHERE id = %s
            """,
            (session_id,),
        )
        row = cur.fetchone()
    assert row is not None
    return row[0]


def _clear_seeded_rows(conn: PsycopgConnection) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM tenants WHERE name LIKE %s",
            (_TENANT_NAME_PREFIX + "%",),
        )
