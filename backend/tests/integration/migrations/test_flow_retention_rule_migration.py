"""The upgrade to one Flow retention rule, and back."""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from sqlalchemy.dialects.postgresql.psycopg2 import (
    PGDialect_psycopg2 as psycopg2_dialect,
)

from alembic import command
from alembic.config import Config
from eneo.flows.infrastructure.flow_retention_repo import FlowRetentionRepository
from tests.integration.migrations.alembic_test_utils import reset_public_schema

pytestmark = pytest.mark.migration_isolation

PREVIOUS_REVISION = "202611231020"
RULE_REVISION = "202611231030"

REMOVED_COLUMNS = {
    ("tenants", "flow_run_history_retention_mode"),
    ("tenants", "flow_run_history_retention_days"),
    ("spaces", "flow_run_history_retention_mode"),
    ("spaces", "flow_run_history_retention_days"),
    ("flows", "flow_run_history_retention_mode"),
}
REMOVED_CHECKS = {
    "ck_tenants_flow_run_history_retention_days_range",
    "ck_tenants_flow_run_history_retention_complete",
    "ck_tenants_flow_run_history_retention_mode",
    "ck_spaces_flow_run_history_retention_days_range",
    "ck_spaces_flow_run_history_retention_complete",
    "ck_spaces_flow_run_history_retention_mode",
    "ck_flows_flow_run_history_retention_complete",
    "ck_flows_flow_run_history_retention_mode",
}
GUIDE = (
    Path(__file__).parents[4]
    / "frontend/apps/docs-site/src/content/guides/flows/retention-policy.mdx"
)
KEPT_CHECKS = {
    "ck_spaces_data_retention_days_range",
    "ck_flows_flow_run_history_retention_days_range",
}


def _alembic_cfg(database_url: str) -> Config:
    backend_dir = Path(__file__).parents[3]
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(autouse=True)
def cleanup_database():
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    yield


@pytest.fixture
def migration_db(test_settings):
    cfg = _alembic_cfg(test_settings.sync_database_url)
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    reset_public_schema(conn)
    command.upgrade(cfg, PREVIOUS_REVISION)
    try:
        yield conn, cfg
    finally:
        reset_public_schema(conn)
        command.upgrade(cfg, "head")
        conn.close()


def _seed(conn) -> dict[str, object]:
    ids = {name: uuid4() for name in ("tenant", "space", "flow", "user", "role")}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (
                id, name, display_name, quota_limit, provisioning, security_enabled,
                state, flow_run_history_retention_mode, flow_run_history_retention_days
            ) VALUES (%s, %s, %s, 100000, false, false, 'active', 'preserve', 30)
            """,
            (ids["tenant"], f"rule-{ids['tenant']}", "Rule"),
        )
        cur.execute(
            """
            INSERT INTO spaces (
                id, name, tenant_id, data_retention_days,
                flow_run_history_retention_mode, flow_run_history_retention_days
            ) VALUES (%s, %s, %s, 60, 'review_required', 14)
            """,
            (ids["space"], f"Rule Space {ids['space']}", ids["tenant"]),
        )
        cur.execute(
            """
            INSERT INTO flows (
                id, name, tenant_id, space_id,
                flow_run_history_retention_mode, flow_run_history_retention_days
            ) VALUES (%s, %s, %s, %s, 'review_required', 10)
            """,
            (ids["flow"], f"Rule Flow {ids['flow']}", ids["tenant"], ids["space"]),
        )
        cur.execute(
            """
            INSERT INTO roles (
                id, name, permissions, tenant_id, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, now(), now())
            """,
            (
                ids["role"],
                f"rule-role-{ids['role']}",
                ["admin", "retention_manage"],
                ids["tenant"],
            ),
        )
        cur.execute(
            "INSERT INTO users (id, tenant_id, username, email, used_tokens, state) "
            "VALUES (%s, %s, %s, %s, 0, 'active')",
            (
                ids["user"],
                ids["tenant"],
                f"rule-{ids['user'].hex[:8]}",
                f"rule-{ids['user'].hex[:12]}@example.test",
            ),
        )
        cur.execute(
            """
            INSERT INTO flow_versions (
                flow_id, version, tenant_id, definition_checksum, definition_json
            ) VALUES (%s, 1, %s, %s, '{"schema_version": 1, "steps": []}')
            """,
            (ids["flow"], ids["tenant"], f"rule-{ids['flow']}"),
        )
        cur.execute(
            """
            INSERT INTO flow_runs (
                tenant_id, flow_id, flow_version, principal_user_id, status,
                created_at, finished_at
            ) VALUES (
                %s, %s, 1, %s, 'completed',
                now() - interval '40 days', now() - interval '40 days'
            )
            """,
            (ids["tenant"], ids["flow"], ids["user"]),
        )
    return ids


def _rows(conn, query: str, *params: object) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _columns(conn) -> set[tuple[str, str]]:
    return set(
        _rows(
            conn,
            """
            SELECT table_name, column_name FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN ('tenants', 'spaces', 'flows')
              AND column_name LIKE 'flow_run_history_retention_%%'
            """,
        )
    )


def _definitions(conn) -> dict[tuple[str, str], tuple]:
    return {
        (table, column): tuple(definition)
        for table, column, *definition in _rows(
            conn,
            """
            SELECT table_name, column_name, data_type, character_maximum_length,
                   is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name IN ('tenants', 'spaces', 'flows')
              AND column_name LIKE 'flow_run_history_retention_%%'
            """,
        )
    }


def _checks(conn) -> dict[str, bool]:
    return dict(
        _rows(
            conn,
            """
            SELECT conname, convalidated FROM pg_constraint
            WHERE contype = 'c' AND (
                conname LIKE 'ck_%%_flow_run_history_retention_%%'
                OR conname = 'ck_spaces_data_retention_days_range'
            )
            """,
        )
    )


def test_the_upgrade_keeps_only_the_space_time_and_the_flow_column(
    migration_db,
) -> None:
    """Mutants: a mode or a Flow-only organisation or space time survives; an
    earlier flow time carries over; the space's conversation time, a run or a
    retention grant changes."""
    conn, cfg = migration_db
    ids = _seed(conn)
    runs_before = _rows(conn, "SELECT id, finished_at FROM flow_runs ORDER BY id")

    command.upgrade(cfg, RULE_REVISION)

    assert _columns(conn) == {("flows", "flow_run_history_retention_days")}
    checks = _checks(conn)
    assert not REMOVED_CHECKS & set(checks)
    assert KEPT_CHECKS <= set(checks)
    assert _rows(
        conn,
        "SELECT flow_run_history_retention_days FROM flows WHERE id = %s",
        ids["flow"],
    ) == [(None,)]
    assert _rows(
        conn, "SELECT data_retention_days FROM spaces WHERE id = %s", ids["space"]
    ) == [(60,)]
    assert _rows(conn, "SELECT permissions FROM roles WHERE id = %s", ids["role"]) == [
        (["admin", "retention_manage"],)
    ]
    assert _rows(conn, "SELECT id, finished_at FROM flow_runs ORDER BY id") == (
        runs_before
    )
    assert _rows(
        conn,
        "SELECT 1 FROM pg_indexes "
        "WHERE indexname = 'ix_flow_runs_tenant_terminal_retention_anchor'",
    ) == [(1,)]


def test_the_downgrade_restores_valid_policies_and_upgrades_again(
    migration_db,
) -> None:
    """Mutants: a flow time chosen after the upgrade has no mode, so the
    restored completeness check fails; a check comes back unvalidated; a
    restored mode is outside the earlier values; a restored column differs
    from its earlier type, length, nullability or default."""
    conn, cfg = migration_db
    ids = _seed(conn)
    command.upgrade(cfg, RULE_REVISION)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE flows SET flow_run_history_retention_days = 3 WHERE id = %s",
            (ids["flow"],),
        )

    command.downgrade(cfg, PREVIOUS_REVISION)

    definitions = _definitions(conn)
    assert {column: definitions.get(column) for column in REMOVED_COLUMNS} == {
        (table, column): (
            ("character varying", 32, "YES", None)
            if column.endswith("_mode")
            else ("integer", None, "YES", None)
        )
        for table, column in REMOVED_COLUMNS
    }
    checks = _checks(conn)
    assert {name: checks.get(name) for name in REMOVED_CHECKS} == dict.fromkeys(
        REMOVED_CHECKS, True
    )
    for table in ("tenants", "spaces", "flows"):
        assert _rows(
            conn,
            f"""
            SELECT count(*) FROM {table}
            WHERE NOT (
                (flow_run_history_retention_mode IS NULL)
                = (flow_run_history_retention_days IS NULL)
            )
            OR flow_run_history_retention_mode NOT IN ('preserve', 'review_required')
            OR flow_run_history_retention_days NOT BETWEEN 1 AND 2555
            """,
        ) == [(0,)]
    assert _rows(
        conn,
        "SELECT flow_run_history_retention_mode, flow_run_history_retention_days "
        "FROM flows WHERE id = %s",
        ids["flow"],
    ) == [("preserve", 3)]
    assert _rows(
        conn,
        "SELECT flow_run_history_retention_mode, flow_run_history_retention_days "
        "FROM spaces WHERE id = %s",
        ids["space"],
    ) == [("preserve", 60)]
    assert _rows(
        conn,
        "SELECT flow_run_history_retention_mode, flow_run_history_retention_days "
        "FROM tenants WHERE id = %s",
        ids["tenant"],
    ) == [(None, None)]

    command.upgrade(cfg, "head")
    assert _columns(conn) == {("flows", "flow_run_history_retention_days")}


def _guide_listing() -> str:
    """The listing query exactly as the guide prints it for operators."""
    blocks = re.findall(r"```sql\n(.*?)```", GUIDE.read_text(), flags=re.DOTALL)
    [query] = [block for block in blocks if "before upgrading" in block]
    return query


def _listing_seed(conn) -> dict[str, object]:
    """Four runs, all 40 days old, far from every deadline: one the upgrade
    makes purgeable, the same held, one it makes no longer purgeable, and one
    it leaves due."""
    ids = {
        name: uuid4()
        for name in ("tenant", "user", "capped", "uncapped", "review", "held_flow")
        + ("tenant_time", "unchanged")
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO tenants (
                id, name, display_name, quota_limit, provisioning, security_enabled,
                state, flow_run_history_retention_mode, flow_run_history_retention_days
            ) VALUES (%s, %s, %s, 100000, false, false, 'active', 'preserve', 30)
            """,
            (ids["tenant"], f"listing-{ids['tenant']}", "Listing"),
        )
        cur.execute(
            "INSERT INTO users (id, tenant_id, username, email, used_tokens, state) "
            "VALUES (%s, %s, %s, %s, 0, 'active')",
            (
                ids["user"],
                ids["tenant"],
                f"listing-{ids['user'].hex[:8]}",
                f"listing-{ids['user'].hex[:12]}@example.test",
            ),
        )
        organization = uuid4()
        cur.execute(
            "INSERT INTO spaces (id, name, tenant_id) VALUES (%s, %s, %s)",
            (organization, f"Listing {organization}", ids["tenant"]),
        )
        for space, days in (("capped", 7), ("uncapped", None)):
            cur.execute(
                "INSERT INTO spaces (id, name, tenant_id, tenant_space_id, "
                "data_retention_days) VALUES (%s, %s, %s, %s, %s)",
                (
                    ids[space],
                    f"Listing {space} {ids[space]}",
                    ids["tenant"],
                    organization,
                    days,
                ),
            )
        flows = {
            # A review mode kept these runs out of every purge.
            "review": ("capped", "review_required", 10),
            "held_flow": ("capped", "review_required", 10),
            # The organisation's preserve time made it due; its space has none.
            "tenant_time": ("uncapped", None, None),
            # Due before through the organisation's 30 days, after through 7.
            "unchanged": ("capped", None, None),
        }
        runs = {}
        for flow, (space, mode, days) in flows.items():
            cur.execute(
                """
                INSERT INTO flows (
                    id, name, tenant_id, space_id,
                    flow_run_history_retention_mode, flow_run_history_retention_days
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (ids[flow], f"Listing {flow}", ids["tenant"], ids[space], mode, days),
            )
            cur.execute(
                """
                INSERT INTO flow_versions (
                    flow_id, version, tenant_id, definition_checksum, definition_json
                ) VALUES (%s, 1, %s, %s, '{"schema_version": 1, "steps": []}')
                """,
                (ids[flow], ids["tenant"], f"listing-{ids[flow]}"),
            )
            cur.execute(
                """
                INSERT INTO flow_runs (
                    tenant_id, flow_id, flow_version, principal_user_id, status,
                    created_at, finished_at
                ) VALUES (
                    %s, %s, 1, %s, 'completed',
                    now() - interval '40 days', now() - interval '40 days'
                ) RETURNING id
                """,
                (ids["tenant"], ids[flow], ids["user"]),
            )
            runs[flow] = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO flow_retention_holds (
                tenant_id, flow_id, flow_run_id, reason, review_by, created_by_actor
            ) VALUES (%s, %s, %s, 'Request', now() + interval '30 days', '{}')
            """,
            (ids["tenant"], ids["held_flow"], runs["held_flow"]),
        )
    return {"tenant": ids["tenant"], "runs": runs}


def test_the_guide_lists_the_runs_whose_eligibility_the_upgrade_changes(
    migration_db,
) -> None:
    """The guide's query, run before the upgrade, agrees with the selector after
    it at the same moment. Mutants: the query misses a review run, a held run or
    a run that only the organisation's time made due; it lists an unchanged run;
    the guide's text drifts from what this test runs."""
    conn, cfg = migration_db
    seeded = _listing_seed(conn)
    runs = {run: name for name, run in seeded["runs"].items()}
    listing = _guide_listing()
    with conn.cursor() as cur:
        # now() is fixed for a transaction: the listing and its moment agree.
        cur.execute("BEGIN READ ONLY")
        try:
            cur.execute("SELECT now()")
            moment = cur.fetchone()[0]
            cur.execute(listing)
            columns = [column.name for column in cur.description]
            rows = [dict(zip(columns, values)) for values in cur.fetchall()]
        finally:
            cur.execute("ROLLBACK")
    listed = {
        runs[row["run_id"]]: (row["change"], row["held"])
        for row in rows
        if row["run_id"] in runs
    }
    assert listed == {
        "review": ("becomes purgeable", False),
        "held_flow": ("becomes purgeable", True),
        "tenant_time": ("no longer purgeable", False),
    }

    command.upgrade(cfg, RULE_REVISION)

    repository = FlowRetentionRepository(session=None)  # type: ignore[arg-type]

    def selected(query) -> set[str]:
        compiled = query.compile(
            dialect=psycopg2_dialect(), compile_kwargs={"render_postcompile": True}
        )
        with conn.cursor() as cur:
            cur.execute(str(compiled), compiled.params)
            return {runs[run_id] for (run_id,) in cur.fetchall()}

    tenant = seeded["tenant"]
    due = selected(
        repository._build_due_flow_run_history_purge_query(now=moment, tenant_id=tenant)
    )
    purgeable = selected(
        repository._build_flow_run_history_purge_batch_query(
            now=moment, limit=100, tenant_id=tenant
        )
    )
    assert due == {"review", "held_flow", "unchanged"}
    assert purgeable == due - {"held_flow"}
