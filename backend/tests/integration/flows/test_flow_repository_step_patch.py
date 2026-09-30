"""The repository patches a retained step row: what differs is written, and
nothing else.

Each case saves a flow through the real services, then updates it through the
repository with the same steps (ids kept) and one difference, and reads the
`flow_steps` rows back with plain SQL. A value is "different" when its JSON
differs: `True` is not `1`, `1.0` is not `1`, and the order of keys is not a
difference. A row nothing changed is not written, so its `updated_at` stays.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.flow_tables import Flows, FlowSteps
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.flow_review_policy import FlowStepReviewMode, FlowStepReviewPolicy
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.main.models import ModelId
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.users.user import UserUpdate

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_TABLE = FlowSteps.__table__
_IDENTITY = {"id", "created_at", "updated_at"}


async def _space(client, db_container, admin_user) -> UUID:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"step-patch-{uuid4().hex[:8]}",
                permissions=[
                    Permission.ASSISTANTS,
                    Permission.SHARED_SPACES,
                    Permission.FLOWS_MANAGE,
                ],
                tenant_id=admin_user.tenant_id,
            )
        )
    async with db_container() as container:
        admin = await container.user_repo().update(
            UserUpdate(id=admin_user.id, roles=[ModelId(id=role.id)])
        )
        assert admin is not None
        token = container.auth_service().create_access_token_for_user(admin)
    response = await client.post(
        "/api/v1/spaces/",
        json={"name": f"step-patch-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


class Saved:
    def __init__(self, flow_id: UUID, assistant_ids: list[UUID]) -> None:
        self.flow_id = flow_id
        self.assistant_ids = assistant_ids


@pytest.fixture
async def saved(client, db_container, admin_user, patch_auth_service_jwt) -> Saved:
    space_id = await _space(client, db_container, admin_user)
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id, name="Tre steg", description="", steps=[]
        )
        assistants = [
            (await service.create_flow_assistant(flow_id=flow.id, name=f"s{order}"))[0]
            for order in (1, 2, 3, 4)
        ]
        await service.update_flow(
            flow_id=flow.id,
            steps=[
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=order,
                    user_description=f"Steg {order}",
                    input_source="flow_input" if order == 1 else "previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                )
                for order, assistant in enumerate(assistants[:3], 1)
            ],
        )
    return Saved(flow.id, [assistant.id for assistant in assistants])


async def _rows(db_container, flow_id: UUID) -> list[dict[str, Any]]:
    async with db_container() as container:
        result = await container.session().execute(
            sa.select(_TABLE)
            .where(FlowSteps.flow_id == flow_id)
            .order_by(FlowSteps.step_order)
        )
        return [dict(row._mapping) for row in result]  # pyright: ignore[reportPrivateUsage]


async def _flow_row(db_container, flow_id: UUID) -> dict[str, Any]:
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(Flows.updated_at, Flows.draft_revision).where(
                    Flows.id == flow_id
                )
            )
        ).one()
    return dict(row._mapping)  # pyright: ignore[reportPrivateUsage]


async def _set_raw(db_container, step_id: UUID, **columns: Any) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowSteps).where(FlowSteps.id == step_id).values(**columns)
        )


async def _update(
    db_container, flow_id: UUID, edit: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    """The flow updated through the repository with its own steps, `edit`
    laid over the step at each position; the rows before and after."""

    async with db_container() as container:
        service = container.flow_service()
        flow: Flow = await service.get_flow(flow_id)
        steps = [
            step.model_copy(update=edit.get(step.step_order, {})) for step in flow.steps
        ]
        await service.flow_repo.update(
            flow.model_copy(update={"steps": steps}),
            tenant_id=container.user().tenant_id,
            expected_revision=flow.draft_revision,
        )
    return await _rows(db_container, flow_id)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


@pytest.mark.parametrize(
    ("saved_value", "edited", "written"),
    [
        ({"custom": {"n": 1, "f": 1.0}}, {"custom": {"n": True, "f": 1}}, True),
        ({"n": 1}, {"n": True}, True),
        ({"f": 1.0}, {"f": 1}, True),
        ({"a": {"b": [1, {"c": True}]}}, {"a": {"b": [1, {"c": 1}]}}, True),
        ({"k": "åäö"}, {"k": "åäo"}, True),
        (None, {}, True),
        (
            {"a": 1, "b": [2, {"c": 3, "d": 4}]},
            {"b": [2, {"d": 4, "c": 3}], "a": 1},
            False,
        ),
        ({"k": "åäö", "n": {"x": 1.5}}, {"n": {"x": 1.5}, "k": "åäö"}, False),
    ],
    ids=[
        "bool and float for int in one config",
        "bool for int",
        "int for float",
        "nested bool for int",
        "one letter of unicode",
        "null for an empty object",
        "key order only",
        "unicode and float, key order only",
    ],
)
async def test_a_json_column_is_patched_when_its_json_differs_and_only_then(
    db_container, saved: Saved, saved_value: Any, edited: Any, written: bool
) -> None:
    step_id = (await _rows(db_container, saved.flow_id))[1]["id"]
    await _set_raw(db_container, step_id, output_config=saved_value)
    before = (await _rows(db_container, saved.flow_id))[1]

    after = (
        await _update(db_container, saved.flow_id, {2: {"output_config": edited}})
    )[1]

    assert after["id"] == before["id"]
    assert _json(after["output_config"]) == _json(edited if written else saved_value)
    assert (after["updated_at"] != before["updated_at"]) is written
    assert {
        column
        for column in before
        if column != "updated_at" and before[column] != after[column]
    } <= {"output_config"}


def _mutations(saved: Saved) -> dict[str, Any]:
    """One different, valid value for every mutable column of a step row."""

    return {
        "assistant_id": saved.assistant_ids[3],
        "timeout_seconds": 45,
        "user_description": "Granska",
        "input_source": "all_previous_steps",
        "input_type": "json",
        "input_contract": {"type": "object", "properties": {"a": {"type": "string"}}},
        "output_mode": "render_verbatim",
        "output_type": "json",
        "output_contract": {"type": "object", "properties": {"b": {"type": "string"}}},
        "input_bindings": {"question": "Vad är {{ step_1.output.text }}?"},
        "output_classification_override": 3,
        "input_config": {"runtime_input": {"enabled": False}},
        "output_config": {"citation_mode": "off"},
        "review_policy": FlowStepReviewPolicy(mode=FlowStepReviewMode.VIEW),
    }


async def test_the_mutations_cover_every_mutable_column_of_a_step_row(
    saved: Saved,
) -> None:
    """A column added to `flow_steps` without a case here fails this test."""

    mutable = (
        {c.name for c in _TABLE.columns}
        - _IDENTITY
        - {
            "flow_id",
            "tenant_id",
            "step_order",
        }
    )
    assert set(_mutations(saved)) == mutable


async def test_the_columns_a_step_is_written_by_are_every_column_the_table_maps() -> (
    None
):
    """The patch compares the columns `_step_to_db_row` names: a column the
    table maps and that list lacks would never be written or compared."""

    row = FlowRepository._step_to_db_row(  # pyright: ignore[reportPrivateUsage]
        MagicMock(),
        flow_id=uuid4(),
        tenant_id=uuid4(),
        step=FlowStep(
            assistant_id=uuid4(),
            step_order=1,
            input_source="flow_input",
            input_type="text",
            output_mode="pass_through",
            output_type="text",
        ),
    )

    assert set(row) == {c.name for c in _TABLE.columns} - _IDENTITY
    assert set(row) == set(FlowStep.model_fields) - _IDENTITY


@pytest.mark.parametrize("column", sorted(_mutations(Saved(uuid4(), [uuid4()] * 4))))
async def test_a_column_changed_alone_is_patched_and_every_other_stays(
    db_container, saved: Saved, column: str
) -> None:
    before = await _rows(db_container, saved.flow_id)
    value = _mutations(saved)[column]

    after = await _update(db_container, saved.flow_id, {2: {column: value}})

    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert after[0] == before[0] and after[2] == before[2]
    differing = {c for c in before[1] if before[1][c] != after[1][c]}
    assert differing == {column, "updated_at"}


async def test_a_saved_row_in_a_legacy_shape_is_not_written_when_nothing_changed(
    db_container, saved: Saved
) -> None:
    """A review policy stored with a null field, and a padded question, are
    what an older writer saved. A step nothing changed keeps its exact bytes
    and its `updated_at`; the step that changed is written alone."""

    rows = await _rows(db_container, saved.flow_id)
    await _set_raw(
        db_container,
        rows[1]["id"],
        review_policy={"mode": "view", "expires_after_seconds": None},
        input_bindings={"question": "  {{ step_1.output.text }}\n"},
    )
    before = await _rows(db_container, saved.flow_id)

    after = await _update(db_container, saved.flow_id, {1: {"user_description": "Läs"}})

    assert after[1] == before[1]
    assert after[2] == before[2]
    assert {c for c in before[0] if before[0][c] != after[0][c]} == {
        "user_description",
        "updated_at",
    }


@pytest.mark.parametrize(
    ("saved_value", "repaired", "written"),
    [
        ({"n": 1}, {"n": True}, True),
        ({"f": 1.0}, {"f": 1}, True),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}, False),
    ],
    ids=["bool for int", "int for float", "key order only"],
)
async def test_the_config_repair_writes_a_config_when_its_json_differs_and_only_then(
    db_container, saved: Saved, saved_value: Any, repaired: Any, written: bool
) -> None:
    """The repair compares configs by their JSON like every other step write:
    Python calls `{"n": True}` equal to `{"n": 1}`, and the repair would then
    skip the row."""

    step_id = (await _rows(db_container, saved.flow_id))[1]["id"]
    await _set_raw(db_container, step_id, input_config=saved_value)
    before = (await _rows(db_container, saved.flow_id))[1]
    flow_before = await _flow_row(db_container, saved.flow_id)

    async with db_container() as container:
        repo = container.flow_service().flow_repo
        flow = await repo.get_step_config_repair_flow(
            flow_id=saved.flow_id, tenant_id=container.user().tenant_id
        )
        steps = [
            step.model_copy(update={"input_config": repaired})
            if step.step_order == 2
            else step
            for step in flow.steps
        ]
        await repo.repair_step_configs(flow=flow, steps=steps)
    after = (await _rows(db_container, saved.flow_id))[1]

    assert _json(after["input_config"]) == _json(repaired if written else saved_value)
    assert after["updated_at"] == before["updated_at"], "a repair keeps updated_at"
    # A repair is not an edit of the draft, yet a plan prepared before it must
    # not write over it: the revision moves, the flow's edit time does not.
    flow_after = await _flow_row(db_container, saved.flow_id)
    assert flow_after["updated_at"] == flow_before["updated_at"]
    assert flow_after["draft_revision"] == flow_before["draft_revision"] + written
