"""Migration test for collapsing builder_plans proposal storage.

Run with:
    pytest -m migration_isolation tests/integration/flows/ai_builder/test_builder_plan_proposal_json_migration.py -v
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg2
import pytest
from psycopg2.extras import Json

from alembic import command
from alembic.config import Config
from intric.flows.ai_builder.ai_builder_domain_models import (
    FlowBuilderProposal,
    FlowBuilderProposalContent,
)
from intric.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    StepSpec,
)
from intric.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

_MIGRATION_REVISION = "20260620_plan_proposal_json"
_PRIOR_REVISION = "202606191530"

_OLD_COLUMNS = {
    "spec_json",
    "envelope_json",
    "resource_bindings_json",
    "edit_result_json",
}
_NEW_COLUMNS = {"proposal_json"}


@dataclass(frozen=True, slots=True)
class _ExpectedPlanRow:
    plan_id: str
    proposal_json: dict[str, object]
    spec_json: dict[str, object]
    envelope_json: dict[str, object]
    resource_bindings_json: object
    edit_result_json: object | None
    spec_hash: str


@dataclass(frozen=True, slots=True)
class _SeedProposal:
    proposal: FlowBuilderProposal
    legacy_edit_result_json: dict[str, object] | None


def _alembic_config(database_url: str) -> Config:
    backend_dir = Path(__file__).parent.parent.parent.parent.parent
    cfg = Config(str(backend_dir / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def _present_columns(cur: psycopg2.extensions.cursor) -> set[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'builder_plans'
        AND column_name = ANY(%s)
        """,
        (list(_OLD_COLUMNS | _NEW_COLUMNS),),
    )
    return {row[0] for row in cur.fetchall()}


def _current_revision(cur: psycopg2.extensions.cursor) -> str | None:
    cur.execute("SELECT version_num FROM alembic_version LIMIT 1")
    row = cur.fetchone()
    return row[0] if row else None


def _make_proposal(
    *,
    flow_name: str,
    include_edit_result: bool = False,
    reasoning: str | None = "Use one step.",
) -> _SeedProposal:
    model_id = uuid4()
    binding = LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.MODEL,
            slot="fast-model",
            label="Fast model",
        ),
        local_kind=LocalResourceKind.COMPLETION_MODEL,
        local_id=model_id,
    )
    spec = FlowDraftSpecCore(
        flow_name=flow_name,
        flow_description="Migration round-trip.",
        steps=[
            StepSpec(
                plan_step_ref="step_a",
                name="Summarize",
                assistant_spec=AssistantSpec(
                    instructions="Summarize the input.",
                    model_ref="model.fast-model",
                ),
                input_source=InputSource.FLOW_INPUT,
            )
        ],
    )
    legacy_edit_result_json = None
    if include_edit_result:
        legacy_edit_result_json = _legacy_edit_result_json(spec)
    return _SeedProposal(
        proposal=FlowBuilderProposal(
            content=FlowBuilderProposalContent(
                spec=spec,
                assumptions=["Text input"],
                risk_acknowledgments=["Review output"],
                plan_rationale="Smallest valid migrated proposal.",
            ),
            reasoning=reasoning,
            resource_bindings=(binding,),
        ),
        legacy_edit_result_json=legacy_edit_result_json,
    )


def _legacy_edit_result_json(spec: FlowDraftSpecCore) -> dict[str, object]:
    diff = {
        "step_changes": [
            {
                "kind": "unchanged",
                "step_name": "Summarize",
            },
            # Keep removals out of sorted order so the migration must normalize them.
            {
                "kind": "removed",
                "step_name": "Legacy removed step B",
                "step_ref": "existing_step_2",
            },
            {
                "kind": "removed",
                "step_name": "Legacy removed step A",
                "step_ref": "existing_step_1",
            },
        ],
        "form_changes": [],
        "metadata_changes": [],
        "flow_property_changes": {},
        "net_steps_added": 0,
        "net_steps_removed": 2,
    }
    return {
        "description_override_manual": True,
        "compiled_edit": {
            "compiled_spec": spec.model_dump(mode="json"),
            "diff": diff,
            "original_draft": {
                "operations": [
                    {
                        "op": "remove",
                        "target_ref": "existing_step_1",
                    },
                    {
                        "op": "remove",
                        "target_ref": "existing_step_2",
                    },
                ]
            },
            "base_flow_revision": 1,
            "warnings": [],
            "advisories": [],
            "risk_flags": [],
            "confidence": "ready",
        },
    }


def _expected_plan_row(
    *,
    plan_id: str,
    seed: _SeedProposal,
) -> _ExpectedPlanRow:
    proposal = seed.proposal
    spec_json = proposal.spec.model_dump(mode="json")
    envelope_json = proposal.content.model_dump(
        mode="json",
        exclude={"spec", "description_override_manual", "edit"},
        exclude_none=True,
    )
    if proposal.reasoning is not None:
        envelope_json["reasoning"] = proposal.reasoning
    resource_bindings_json = proposal.storage_json()["resource_bindings"]
    edit_result_json = seed.legacy_edit_result_json
    content_json = {
        key: value for key, value in envelope_json.items() if key != "reasoning"
    }
    content_json["spec"] = spec_json
    content_json["description_override_manual"] = (
        bool(edit_result_json.get("description_override_manual"))
        if edit_result_json is not None
        else False
    )
    if edit_result_json is not None:
        compiled_edit = edit_result_json["compiled_edit"]
        assert isinstance(compiled_edit, dict)
        diff = compiled_edit["diff"]
        assert isinstance(diff, dict)
        step_changes = diff["step_changes"]
        assert isinstance(step_changes, list)
        content_json["edit"] = {
            "base_flow_revision": compiled_edit["base_flow_revision"],
            "removed_existing_step_refs": sorted(
                change["step_ref"]
                for change in step_changes
                if isinstance(change, dict)
                and change.get("kind") == "removed"
                and change.get("step_ref") is not None
            ),
            "diff": diff,
            "warnings": compiled_edit.get("warnings", []),
            "advisories": compiled_edit.get("advisories", []),
            "risk_flags": compiled_edit.get("risk_flags", []),
            "confidence": compiled_edit.get("confidence", "ready"),
        }
    proposal_json = {
        "content": content_json,
        "resource_bindings": resource_bindings_json,
    }
    if proposal.reasoning is not None:
        proposal_json["reasoning"] = proposal.reasoning

    return _ExpectedPlanRow(
        plan_id=plan_id,
        proposal_json=proposal_json,
        spec_json=spec_json,
        envelope_json=envelope_json,
        resource_bindings_json=resource_bindings_json,
        edit_result_json=edit_result_json,
        spec_hash=proposal.spec_hash,
    )


def _seed_old_plan_row(
    cur: psycopg2.extensions.cursor,
    seed: _SeedProposal,
) -> _ExpectedPlanRow:
    tenant_id = uuid4()
    user_id = uuid4()
    space_id = uuid4()
    session_id = uuid4()
    plan_id = uuid4()
    expected = _expected_plan_row(plan_id=str(plan_id), seed=seed)

    cur.execute(
        """
        INSERT INTO tenants (id, name, quota_limit, state)
        VALUES (%s, %s, %s, %s)
        """,
        (
            str(tenant_id),
            f"proposal-json-tenant-{tenant_id}",
            1073741824,
            "active",
        ),
    )
    cur.execute(
        """
        INSERT INTO users (
            id, email, state, used_tokens, tenant_id, quota_limit
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            str(user_id),
            f"proposal-json-{user_id}@example.test",
            "active",
            0,
            str(tenant_id),
            1073741824,
        ),
    )
    cur.execute(
        """
        INSERT INTO spaces (id, name, tenant_id, user_id)
        VALUES (%s, %s, %s, %s)
        """,
        (str(space_id), "Proposal migration", str(tenant_id), str(user_id)),
    )
    cur.execute(
        """
        INSERT INTO builder_sessions (
            id, tenant_id, space_id, target_kind, actor_user_id
        )
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            str(session_id),
            str(tenant_id),
            str(space_id),
            "create",
            str(user_id),
        ),
    )
    cur.execute(
        """
        INSERT INTO builder_plans (
            id,
            session_id,
            tenant_id,
            spec_json,
            spec_hash,
            envelope_json,
            resource_bindings_json,
            edit_result_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            expected.plan_id,
            str(session_id),
            str(tenant_id),
            Json(expected.spec_json),
            expected.spec_hash,
            Json(expected.envelope_json),
            Json(expected.resource_bindings_json),
            Json(expected.edit_result_json)
            if expected.edit_result_json is not None
            else None,
        ),
    )
    return expected


@pytest.fixture(autouse=True)
def cleanup_database():
    """Suppress the session-level cleanup fixture; migration tests own DB state."""
    yield


@pytest.fixture(autouse=True)
def seed_default_models():
    """Suppress auto-seeding; migration tests own the schema."""
    yield


@pytest.fixture(scope="module")
def migration_round_trip(test_settings):
    conn = psycopg2.connect(
        host=test_settings.postgres_host,
        port=test_settings.postgres_port,
        dbname=test_settings.postgres_db,
        user=test_settings.postgres_user,
        password=test_settings.postgres_password,
    )
    conn.autocommit = True
    cfg = _alembic_config(test_settings.sync_database_url)
    proposals = (
        _make_proposal(flow_name="Migrated proposal"),
        _make_proposal(flow_name="Migrated edit proposal", include_edit_result=True),
        _make_proposal(flow_name="Migrated proposal without reasoning", reasoning=None),
    )

    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, _PRIOR_REVISION)

        with conn.cursor() as cur:
            assert _current_revision(cur) == _PRIOR_REVISION
            assert _present_columns(cur) == _OLD_COLUMNS
            expected_rows = {
                expected.plan_id: expected
                for expected in (
                    _seed_old_plan_row(cur, proposal) for proposal in proposals
                )
            }

        command.upgrade(cfg, _MIGRATION_REVISION)
        with conn.cursor() as cur:
            first_up_columns = _present_columns(cur)
            cur.execute(
                """
                SELECT id::text, proposal_json, spec_hash
                FROM builder_plans
                ORDER BY id
                """
            )
            first_up_rows = {
                row[0]: {"proposal_json": row[1], "spec_hash": row[2]}
                for row in cur.fetchall()
            }

        command.downgrade(cfg, "-1")
        with conn.cursor() as cur:
            down_columns = _present_columns(cur)
            cur.execute(
                """
                SELECT
                    id::text,
                    spec_json,
                    envelope_json,
                    resource_bindings_json,
                    edit_result_json,
                    spec_hash
                FROM builder_plans
                ORDER BY id
                """
            )
            down_rows = {row[0]: row[1:] for row in cur.fetchall()}

        command.upgrade(cfg, _MIGRATION_REVISION)
        with conn.cursor() as cur:
            second_up_columns = _present_columns(cur)
            cur.execute(
                """
                SELECT id::text, proposal_json, spec_hash
                FROM builder_plans
                ORDER BY id
                """
            )
            second_up_rows = {
                row[0]: {"proposal_json": row[1], "spec_hash": row[2]}
                for row in cur.fetchall()
            }

        command.upgrade(cfg, "head")

        yield {
            "expected_rows": expected_rows,
            "after_first_upgrade": {
                "columns": first_up_columns,
                "rows": first_up_rows,
            },
            "after_downgrade": {
                "columns": down_columns,
                "rows": down_rows,
            },
            "after_second_upgrade": {
                "columns": second_up_columns,
                "rows": second_up_rows,
            },
        }
    finally:
        conn.close()


def test_upgrade_replaces_split_columns_with_proposal_json(migration_round_trip):
    state = migration_round_trip["after_first_upgrade"]
    expected_rows = migration_round_trip["expected_rows"]

    assert state["columns"] == _NEW_COLUMNS
    assert set(state["rows"]) == set(expected_rows)
    for plan_id, expected in expected_rows.items():
        row = state["rows"][plan_id]
        assert row["proposal_json"] == expected.proposal_json
        assert row["spec_hash"] == expected.spec_hash
        assert (
            FlowBuilderProposal.model_validate(
                row["proposal_json"],
                strict=False,
            ).spec_hash
            == row["spec_hash"]
        )


def test_downgrade_reconstructs_split_columns(migration_round_trip):
    state = migration_round_trip["after_downgrade"]
    expected_rows = migration_round_trip["expected_rows"]

    assert state["columns"] == _OLD_COLUMNS
    assert set(state["rows"]) == set(expected_rows)
    for plan_id, expected in expected_rows.items():
        (
            spec_json,
            envelope_json,
            resource_bindings_json,
            edit_result_json,
            spec_hash,
        ) = state["rows"][plan_id]
        assert spec_json == expected.spec_json
        assert envelope_json == expected.envelope_json
        assert resource_bindings_json == expected.resource_bindings_json
        assert edit_result_json == expected.edit_result_json
        assert spec_hash == expected.spec_hash


def test_second_upgrade_preserves_proposal_json(migration_round_trip):
    state = migration_round_trip["after_second_upgrade"]
    expected_rows = migration_round_trip["expected_rows"]

    assert state["columns"] == _NEW_COLUMNS
    assert set(state["rows"]) == set(expected_rows)
    for plan_id, expected in expected_rows.items():
        row = state["rows"][plan_id]
        assert row["proposal_json"] == expected.proposal_json
        assert row["spec_hash"] == expected.spec_hash
