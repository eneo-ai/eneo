"""An upgrade to head chooses nothing on the organisation's behalf.

The database starts at develop's newest revision with the predefined roles, two
custom roles and the upload policy an installation has before the Flows
revisions run. After ``upgrade head``: Flows stay off, no role holds a flow
permission, only the predefined Owner role holds the retention permissions, and
the upload limits and their revision are as they were. The claims are what the
chain promises, not equality with one revision, so a later develop revision may
add its own permissions without turning this red.

    pytest -m migration_isolation \
        tests/integration/migrations/test_upgrade_keeps_choices.py
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest

from alembic import command
from alembic.config import Config
from tests.integration.migrations.alembic_test_utils import at_revision

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

# Develop's newest revision: every revision after it belongs to the Flows chain.
DEVELOP_HEAD = "202611091200"
RETENTION_PERMISSIONS = {"retention_manage", "retention_holds"}
MIB = 1024 * 1024
# Upload limits as an installation upgraded from the last release has them.
POLICY = {
    "session_file_limit_bytes": 10 * MIB,
    "knowledge_file_limit_bytes": 10 * MIB,
    "transcription_audio_limit_bytes": 200 * MIB,
    "session_image_limit_bytes": 10 * MIB,
    "revision": 1,
}


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _seed(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO tenants (id, name, quota_limit, state) "
            "VALUES (gen_random_uuid(), %s, 1000000, 'active') RETURNING id",
            (f"upgrade-choices-{uuid4().hex[:8]}",),
        )
        tenant_id = cursor.fetchone()[0]
        for name, source, permissions in (
            ("Owner", "Owner", ["admin", "assistants"]),
            ("AI Configurator", "AI Configurator", ["AI", "assistants"]),
            ("User", "User", ["assistants"]),
            ("Delegated admin", None, ["admin", "assistants"]),
            ("Reviewer", None, ["assistants", "insights"]),
        ):
            cursor.execute(
                "INSERT INTO roles (id, name, permissions, predefined_source, "
                "tenant_id, created_at, updated_at) "
                "VALUES (gen_random_uuid(), %s, %s, %s, %s, now(), now())",
                (name, permissions, source, tenant_id),
            )
        # Set the row outright: the seed revision reads limits from the
        # environment, which must not decide what this test starts from.
        cursor.execute(
            "UPDATE object_content_deployment_policy SET "
            "session_file_limit_bytes = %(session_file_limit_bytes)s, "
            "knowledge_file_limit_bytes = %(knowledge_file_limit_bytes)s, "
            "transcription_audio_limit_bytes = %(transcription_audio_limit_bytes)s, "
            "session_image_limit_bytes = %(session_image_limit_bytes)s, "
            "revision = %(revision)s, updated_by_actor = 'migration', "
            "updated_by_user_id = NULL WHERE id = 1",
            POLICY,
        )
        assert cursor.rowcount == 1


def _snapshot(conn) -> dict[str, object]:
    with conn.cursor() as cursor:
        cursor.execute(
            "SELECT enabled FROM global_feature_flags WHERE name = 'flows_core'"
        )
        global_flag = cursor.fetchone()
        cursor.execute(
            "SELECT count(*) FROM tenant_feature_flags "
            "WHERE name = 'flows_core' AND enabled"
        )
        tenants_on = cursor.fetchone()[0]
        cursor.execute("SELECT name, predefined_source, permissions FROM roles")
        roles = {
            name: (source, set(permissions))
            for name, source, permissions in cursor.fetchall()
        }
        cursor.execute(
            f"SELECT {', '.join(POLICY)} FROM object_content_deployment_policy "
            "WHERE id = 1"
        )
        policy = dict(zip(POLICY, cursor.fetchone()))
    return {
        "global_flag": None if global_flag is None else global_flag[0],
        "tenants_on": tenants_on,
        "roles": roles,
        "policy": policy,
    }


@pytest.fixture(scope="module")
def upgraded(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(test_settings.sync_database_url.replace("+psycopg2", ""))
    conn.autocommit = True
    try:
        with at_revision(cfg, DEVELOP_HEAD):
            _seed(conn)
            before = _snapshot(conn)
            command.upgrade(cfg, "head")
            yield before, _snapshot(conn)
    finally:
        conn.close()


def test_flows_stay_off(upgraded):
    _, after = upgraded
    assert after["global_flag"] in (None, False)
    assert after["tenants_on"] == 0


def test_no_role_gains_a_flow_permission(upgraded):
    _, after = upgraded
    # The older "flows" value grants all four flow permissions.
    held = {
        name: sorted(p for p in permissions if p == "flows" or p.startswith("flows_"))
        for name, (_, permissions) in after["roles"].items()
    }
    assert held == {name: [] for name in after["roles"]}


def test_only_the_owner_role_gains_the_retention_permissions(upgraded):
    _, after = upgraded
    held = {
        name: sorted(permissions & RETENTION_PERMISSIONS)
        for name, (_, permissions) in after["roles"].items()
    }
    owners = {name for name, (source, _) in after["roles"].items() if source == "Owner"}
    assert held == {
        name: sorted(RETENTION_PERMISSIONS) if name in owners else []
        for name in after["roles"]
    }


def test_upload_policy_and_its_revision_are_unchanged(upgraded):
    before, after = upgraded
    assert before["policy"] == POLICY
    assert after["policy"] == before["policy"]
