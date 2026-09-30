"""An edit patches the step rows it retains and writes nothing else.

The saved flow's steps carry state the authoring spec has no field for (a
timeout, a classification override). Each case applies an edit command through
the authoring service against a real database and reads the `flow_steps` rows
back with plain SQL: a step the edit keeps is the same row (id, creation time,
every column), a step it removes is gone, a step it adds is new, and a column
changes only when the edit changed it, `updated_at` included.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.flow_tables import FlowSteps, FlowVersions
from eneo.flows.ai_builder.ai_builder_authoring_policy import AIBuilderAuthoringPolicy
from eneo.flows.ai_builder.ai_builder_context import (
    serialize_space_kbs,
    serialize_space_models,
)
from eneo.flows.ai_builder.ai_builder_create_compile_context import (
    create_compile_context_from_planning_state,
)
from eneo.flows.ai_builder.ai_builder_domain_models import TargetKind
from eneo.flows.ai_builder.ai_builder_edit_proposal import process_edit_arguments
from eneo.flows.ai_builder.ai_builder_plan_lifecycle import (
    _removed_existing_step_refs_for_apply,
    _updated_assistant_fields_for_apply,
    _updated_existing_step_refs_for_apply,
)
from eneo.flows.ai_builder.ai_builder_proposal_tool_contracts import ProposalReady
from eneo.flows.ai_builder.ai_builder_resource_catalog import (
    build_ai_builder_resource_catalog,
)
from eneo.flows.application.flow_authoring_command import (
    AIBuilderFlowAuthoringOrigin,
    EditFlowAuthoringCommand,
    FlowAuthoringCommandService,
)
from eneo.flows.application.flow_authoring_snapshot import current_flow_authoring_spec
from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_authoring_spec import (
    AssistantSpec,
    FlowDraftSpecCore,
    InputSource,
    InputType,
    StepSpec,
)
from eneo.flows.flow_resource_bindings import LocalResourceBinding
from eneo.flows.step_lineage import existing_step_ref_for_order
from eneo.main.exceptions import BadRequestException
from eneo.main.models import ModelId
from eneo.prompts.api.prompt_models import PromptCreate
from eneo.roles.permissions import Permission
from eneo.roles.role import RoleCreate
from eneo.settings.encryption_service import EncryptionService
from eneo.users.user import UserUpdate
from tests.unittests.flows.ai_builder.proposal_turn_builders import _make_turn

if TYPE_CHECKING:
    from eneo.flows.application.flow_draft_materialization import AssistantField

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Saved state the authoring spec cannot express, one distinct value per step.
_TIMEOUTS = {1: 30, 2: 90, 3: None}
_CLASSIFICATIONS = {1: 1, 2: 2, 3: None}
# The overrides are valid in every order the cases put the steps in: steps 2
# and 3 (and a step an edit adds) ask a question that names no other step, so
# they read no classified output, and the one step that reads its predecessor
# (step 1, once moved down) reads the step without an override.
_OWN_QUESTION = {"question": "Gör uppgiften."}
_ROW_COLUMNS = [column.name for column in FlowSteps.__table__.columns]


@dataclass
class Saved:
    space_id: UUID
    flow_id: UUID
    revision: int


Row = dict[str, Any]


async def _space(client, db_container, admin_user) -> UUID:
    async with db_container() as container:
        role = await container.role_repo().create_role(
            RoleCreate(
                name=f"edit-step-rows-{uuid4().hex[:8]}",
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
        json={"name": f"edit-step-rows-{uuid4().hex[:8]}"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


async def _saved_flow(db_container, space_id: UUID) -> Saved:
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id,
            name="Tre steg",
            description="Läser, bedömer, skriver.",
            steps=[],
        )
        steps: list[FlowStep] = []
        for order in (1, 2, 3):
            assistant, _ = await service.create_flow_assistant(
                flow_id=flow.id, name=f"steg{order}"
            )
            await service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant.id,
                update=AssistantUpdateCommand(
                    prompt=PromptCreate(text=f"Gör uppgift {order}.")
                ),
            )
            steps.append(
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=order,
                    user_description=f"Steg {order}",
                    input_source="flow_input" if order == 1 else "previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                    timeout_seconds=_TIMEOUTS[order],
                    output_classification_override=_CLASSIFICATIONS[order],
                    input_bindings=None if order == 1 else _OWN_QUESTION,
                )
            )
        flow = await service.update_flow(flow_id=flow.id, steps=steps)
    return Saved(space_id, flow.id, flow.draft_revision)


async def _rows(db_container, flow_id: UUID) -> list[Row]:
    """Every column of every step row of the flow, in step order, by plain SQL."""

    async with db_container() as container:
        result = await container.session().execute(
            sa.select(FlowSteps.__table__)
            .where(FlowSteps.flow_id == flow_id)
            .order_by(FlowSteps.step_order)
        )
        return [dict(row._mapping) for row in result]  # pyright: ignore[reportPrivateUsage]


async def _version_count(db_container, flow_id: UUID) -> int:
    async with db_container() as container:
        return int(
            await container.session().scalar(
                sa.select(sa.func.count())
                .select_from(FlowVersions)
                .where(FlowVersions.flow_id == flow_id)
            )
            or 0
        )


Edit = Callable[[FlowDraftSpecCore], tuple[FlowDraftSpecCore, frozenset[str]]]


def _rename(spec: FlowDraftSpecCore) -> tuple[FlowDraftSpecCore, frozenset[str]]:
    steps = list(spec.steps)
    steps[1] = steps[1].model_copy(update={"name": "Granska"})
    return spec.model_copy(update={"steps": steps}), frozenset()


def _reading(step: StepSpec, source: InputSource) -> StepSpec:
    return step.model_copy(update={"input_source": source})


def _move(spec: FlowDraftSpecCore) -> tuple[FlowDraftSpecCore, frozenset[str]]:
    """Step 3 first: only the first step reads the run input, so the two
    steps that trade places trade their input sources."""

    first, second, third = spec.steps
    steps = [
        _reading(third, InputSource.FLOW_INPUT),
        _reading(first, InputSource.PREVIOUS_STEP),
        second,
    ]
    return spec.model_copy(update={"steps": steps}), frozenset()


def _add(spec: FlowDraftSpecCore) -> tuple[FlowDraftSpecCore, frozenset[str]]:
    added = StepSpec(
        plan_step_ref="n1",
        name="Ny",
        assistant_spec=AssistantSpec(instructions="Gör en ny uppgift."),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        input_bindings=_OWN_QUESTION,
    )
    first, *rest = spec.steps
    return spec.model_copy(update={"steps": [first, added, *rest]}), frozenset()


def _remove(spec: FlowDraftSpecCore) -> tuple[FlowDraftSpecCore, frozenset[str]]:
    first, second, third = spec.steps
    return (
        spec.model_copy(update={"steps": [first, third]}),
        frozenset({second.existing_step_ref or ""}),
    )


def _everything(spec: FlowDraftSpecCore) -> tuple[FlowDraftSpecCore, frozenset[str]]:
    """Step 2 removed, step 3 moved first and renamed, a step added last."""

    first, second, third = spec.steps
    added = StepSpec(
        plan_step_ref="n1",
        name="Ny",
        assistant_spec=AssistantSpec(instructions="Gör en ny uppgift."),
        input_source=InputSource.PREVIOUS_STEP,
        input_type=InputType.TEXT,
        input_bindings=_OWN_QUESTION,
    )
    third = _reading(third, InputSource.FLOW_INPUT).model_copy(update={"name": "Skriv"})
    return (
        spec.model_copy(
            update={"steps": [third, _reading(first, InputSource.PREVIOUS_STEP), added]}
        ),
        frozenset({second.existing_step_ref or ""}),
    )


# Per case: what the final sequence is (by the saved step it was, 1-3, or "new"),
# the columns the edit itself changes on a kept step, and the steps it removes.
CASES: dict[str, tuple[Edit, list[int | str], dict[int, set[str]], set[int]]] = {
    "rename": (_rename, [1, 2, 3], {2: {"user_description"}}, set()),
    "move": (_move, [3, 1, 2], {3: {"input_source"}, 1: {"input_source"}}, set()),
    "add": (_add, [1, "new", 2, 3], {}, set()),
    "remove": (_remove, [1, 3], {}, {2}),
    "everything": (
        _everything,
        [3, 1, "new"],
        {3: {"user_description", "input_source"}, 1: {"input_source"}},
        {2},
    ),
}


def _updated(changed: dict[int, set[str]]) -> frozenset[str]:
    """The steps a plan's approval lists as modified: the ones the edit changes."""

    return frozenset(existing_step_ref_for_order(order) for order in changed)


async def _apply_spec(
    db_container,
    saved: Saved,
    spec: FlowDraftSpecCore,
    *,
    removed: frozenset[str],
    updated: frozenset[str],
    assistant_fields: dict[str, frozenset[AssistantField]] | None = None,
    bindings: tuple[LocalResourceBinding, ...] = (),
) -> None:
    async with db_container() as container:
        origin = AIBuilderFlowAuthoringOrigin(
            session_id=uuid4(),
            plan_id=uuid4(),
            spec_hash=spec.spec_hash(),
            applied_at=datetime.now(timezone.utc),
        )
        await FlowAuthoringCommandService().apply(
            command=EditFlowAuthoringCommand(
                space_id=saved.space_id,
                flow_id=saved.flow_id,
                expected_revision=saved.revision,
                spec=spec,
                removed_existing_step_refs=removed,
                updated_existing_step_refs=updated,
                updated_assistant_fields=assistant_fields or {},
                resource_bindings=bindings,
                origin=origin,
            ),
            flow_service=container.flow_service(),
            origin_policy=AIBuilderAuthoringPolicy(origin),
        )


async def _apply(
    db_container,
    saved: Saved,
    edit: Edit,
    updated: frozenset[str] = frozenset(),
    assistant_fields: dict[str, frozenset[AssistantField]] | None = None,
) -> None:
    """The edit laid over the saved flow's own authoring spec, applied with the
    step refs a plan's approval lists as modified."""

    async with db_container() as container:
        service = container.flow_service()
        flow = await service.get_flow(saved.flow_id)
        snapshots = await service.get_flow_assistant_snapshots(flow)
        spec, removed = edit(
            current_flow_authoring_spec(
                current_steps=list(flow.steps),
                flow_name=flow.name,
                flow_description=flow.description,
                assistant_snapshots=snapshots,
                # Steps are edited here, not assistants: the model and
                # knowledge an assistant holds are not part of the spec.
                assistant_snapshot_projector=lambda snapshot: AssistantSpec(
                    instructions=snapshot.instructions
                ),
            )
        )
    await _apply_spec(
        db_container,
        saved,
        spec,
        removed=removed,
        updated=updated,
        assistant_fields=assistant_fields,
    )


def _keep(order: int, **changes: Any) -> dict[str, Any]:
    """A saved step in the edit's ordered list, with what changes on it."""

    return {"kind": "modify", "existing_step_ref": f"existing_step_{order}", **changes}


def _new_step(name: str = "Ny") -> dict[str, Any]:
    return {
        "kind": "add",
        "step": {"name": name, "instructions": "Gör en ny uppgift."},
    }


async def _edit(
    db_container,
    saved: Saved,
    steps: list[dict[str, Any]],
    removed: tuple[str, ...] = (),
) -> None:
    """The whole chain a plan goes through, from what the model sends: the real
    edit compile against the saved flow, the step lists the lifecycle derives
    from the approval that compile made, and the apply."""

    async with db_container() as container:
        service = container.flow_service()
        flow = await service.get_flow(saved.flow_id)
        space = await container.space_service().get_space(saved.space_id)
        outcome = await process_edit_arguments(
            turn=_make_turn(),
            conversation=[],
            arguments={
                "plan_rationale": "Ändra flödet.",
                "steps": steps,
                "removed_existing_step_refs": list(removed),
            },
            available_model_refs=None,
            available_kb_refs=None,
            flow=flow,
            assistant_snapshots=await service.get_flow_assistant_snapshots(flow),
            resource_catalog=build_ai_builder_resource_catalog(
                available_models=serialize_space_models(space),
                available_kbs=serialize_space_kbs(space),
            ),
            compile_context=create_compile_context_from_planning_state(
                None, ui_language="sv"
            ),
        )
    assert isinstance(outcome, ProposalReady), outcome
    content = outcome.compiled.content
    session = SimpleNamespace(target_kind=TargetKind.EDIT, id=uuid4())
    plan = SimpleNamespace(id=uuid4(), proposal=SimpleNamespace(content=content))
    await _apply_spec(
        db_container,
        saved,
        content.spec,
        removed=_removed_existing_step_refs_for_apply(session=session, plan=plan),  # type: ignore[arg-type]
        updated=_updated_existing_step_refs_for_apply(session=session, plan=plan),  # type: ignore[arg-type]
        assistant_fields=_updated_assistant_fields_for_apply(
            session=session, plan=plan
        ),  # type: ignore[arg-type]
        bindings=outcome.compiled.resource_bindings,
    )


@pytest.fixture
async def saved(client, db_container, admin_user, patch_auth_service_jwt) -> Saved:
    return await _saved_flow(
        db_container, await _space(client, db_container, admin_user)
    )


@pytest.mark.parametrize("case", list(CASES))
async def test_an_edit_keeps_the_state_the_spec_has_no_field_for(
    db_container, saved: Saved, case: str
) -> None:
    """Judged by what the saved step was, not by its id: a step that kept its
    place, or moved, still has its timeout and classification override."""

    edit, sequence, changed, _ = CASES[case]
    before = {
        row["step_order"]: row for row in await _rows(db_container, saved.flow_id)
    }

    await _apply(db_container, saved, edit, _updated(changed))
    after = await _rows(db_container, saved.flow_id)

    expected = {
        column: [
            None if saved_step == "new" else before[saved_step][column]
            for saved_step in sequence
        ]
        for column in ("timeout_seconds", "output_classification_override")
    }
    assert {column: [row[column] for row in after] for column in expected} == expected


@pytest.mark.parametrize("case", list(CASES))
async def test_an_edit_patches_the_step_rows_it_keeps(
    db_container, saved: Saved, case: str
) -> None:
    edit, sequence, changed, removed = CASES[case]
    before = await _rows(db_container, saved.flow_id)
    by_position = {row["step_order"]: row for row in before}

    await _apply(db_container, saved, edit, _updated(changed))
    after = await _rows(db_container, saved.flow_id)

    assert [row["step_order"] for row in after] == list(range(1, len(sequence) + 1))
    for position, (row, expected) in enumerate(zip(after, sequence, strict=True), 1):
        if expected == "new":
            assert row["id"] not in {r["id"] for r in before}
            continue
        kept = by_position[expected]
        moved = {"step_order"} if kept["step_order"] != position else set()
        touched = changed.get(expected, set()) | moved
        differing = {c for c in _ROW_COLUMNS if kept[c] != row[c]}
        assert row["id"] == kept["id"], f"step {expected} was written as a new row"
        assert differing - {"updated_at"} == touched, (expected, differing)
        assert ("updated_at" in differing) == bool(touched), (
            f"step {expected}: updated_at moves only with a changed column"
        )
    assert {row["id"] for row in before if row["step_order"] in removed}.isdisjoint(
        row["id"] for row in after
    )
    assert await _version_count(db_container, saved.flow_id) == 0


async def test_a_rename_leaves_every_unnamed_step_row_exactly_as_saved(
    db_container, saved: Saved
) -> None:
    """The plainest statement of the rule: the rows of the steps the edit does
    not name are equal to what was saved, column for column."""

    before = await _rows(db_container, saved.flow_id)

    await _apply(db_container, saved, _rename, _updated({2: set()}))
    after = await _rows(db_container, saved.flow_id)

    assert [after[0], after[2]] == [before[0], before[2]]
    assert {c for c in _ROW_COLUMNS if before[1][c] != after[1][c]} == {
        "user_description",
        "updated_at",
    }


async def _set_raw(db_container, step_id: UUID, **columns: Any) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowSteps).where(FlowSteps.id == step_id).values(**columns)
        )


async def test_a_step_the_edit_leaves_keeps_the_shape_an_older_writer_saved(
    db_container, saved: Saved
) -> None:
    """A padded question and a review policy with a null field are how an
    older writer saved two steps. The edit names neither: their rows are
    byte for byte what they were, `updated_at` included, though the authoring
    spec shows both normalized."""

    before = await _rows(db_container, saved.flow_id)
    for row in before:
        await _set_raw(db_container, row["id"], output_classification_override=None)
    await _set_raw(
        db_container,
        before[1]["id"],
        input_bindings={"question": "  {{ step_1.output.text }}\n"},
    )
    await _set_raw(
        db_container,
        before[2]["id"],
        review_policy={"mode": "view", "expires_after_seconds": None},
    )
    before = await _rows(db_container, saved.flow_id)

    def rename_first(
        spec: FlowDraftSpecCore,
    ) -> tuple[FlowDraftSpecCore, frozenset[str]]:
        steps = list(spec.steps)
        steps[0] = steps[0].model_copy(update={"name": "Läs"})
        return spec.model_copy(update={"steps": steps}), frozenset()

    await _apply(db_container, saved, rename_first, _updated({1: set()}))
    after = await _rows(db_container, saved.flow_id)

    assert after[1] == before[1] and after[2] == before[2]
    assert {c for c in _ROW_COLUMNS if before[0][c] != after[0][c]} == {
        "user_description",
        "updated_at",
    }


async def test_a_step_that_reads_a_step_the_edit_moves_reads_it_where_it_now_is(
    db_container, saved: Saved
) -> None:
    """Keeping a row as it was must not keep a reference to a position its
    producer left: the consumer names its producer by its plan ref, and the
    row is written with the producer's new place."""

    rows = await _rows(db_container, saved.flow_id)
    for row in rows:
        await _set_raw(db_container, row["id"], output_classification_override=None)
    await _set_raw(
        db_container,
        rows[2]["id"],
        input_bindings={"question": "Sammanfatta {{ step_2.output.text }}"},
    )

    def insert_before_the_producer(
        spec: FlowDraftSpecCore,
    ) -> tuple[FlowDraftSpecCore, frozenset[str]]:
        first, producer, consumer = spec.steps
        consumer = consumer.model_copy(
            update={
                "input_bindings": {
                    "question": f"Sammanfatta {{{{ {producer.plan_step_ref}.output.text }}}}"
                }
            }
        )
        added = StepSpec(
            plan_step_ref="n1",
            name="Ny",
            assistant_spec=AssistantSpec(instructions="Gör en ny uppgift."),
            input_source=InputSource.PREVIOUS_STEP,
            input_type=InputType.TEXT,
        )
        return (
            spec.model_copy(update={"steps": [first, added, producer, consumer]}),
            frozenset(),
        )

    await _apply(db_container, saved, insert_before_the_producer)
    after = await _rows(db_container, saved.flow_id)

    assert after[3]["input_bindings"] == {
        "question": "Sammanfatta {{ step_3.output.text }}"
    }


async def test_a_modified_retained_step_is_patched_alone_through_the_apply(
    db_container, saved: Saved
) -> None:
    """The step is marked modified and its assistant's instructions are
    written too; at the flow_steps level the row is patched in the changed
    columns only."""

    before = await _rows(db_container, saved.flow_id)

    def change_two_columns(
        spec: FlowDraftSpecCore,
    ) -> tuple[FlowDraftSpecCore, frozenset[str]]:
        steps = list(spec.steps)
        steps[1] = steps[1].model_copy(
            update={"name": "Granska", "output_config": {"citation_mode": "off"}}
        )
        return spec.model_copy(update={"steps": steps}), frozenset()

    await _apply(
        db_container,
        saved,
        change_two_columns,
        updated=frozenset({"existing_step_2"}),
        assistant_fields={"existing_step_2": frozenset({"instructions"})},
    )
    after = await _rows(db_container, saved.flow_id)

    assert [row["id"] for row in after] == [row["id"] for row in before]
    assert after[0] == before[0] and after[2] == before[2]
    assert {c for c in _ROW_COLUMNS if before[1][c] != after[1][c]} == {
        "user_description",
        "output_config",
        "updated_at",
    }
    assert after[1]["timeout_seconds"] == before[1]["timeout_seconds"]


async def test_a_secret_shaped_value_in_a_retained_steps_plain_config_is_kept_as_data(
    db_container, saved: Saved
) -> None:
    """A bare `{"$secret": ...}` object in a config that is not an HTTP
    config is only JSON to the flow: nothing reads it as a credential. Before
    steps kept their ids, an id-less step carrying one was refused; now the
    retained step stores it, unchanged, and nothing is merged or read."""

    rows = await _rows(db_container, saved.flow_id)
    sentinel = {"custom": {"$secret": "stored"}}
    await _set_raw(db_container, rows[1]["id"], output_config=sentinel)
    before = await _rows(db_container, saved.flow_id)

    await _apply(db_container, saved, _rename, _updated({2: set()}))
    after = await _rows(db_container, saved.flow_id)

    assert after[1]["output_config"] == sentinel == before[1]["output_config"]


@pytest.fixture
async def frontend_saved(db_container, saved: Saved) -> Saved:
    """The three steps as the flow builder saves them: refs without spaces, a
    step with no description, `{}` and switched-off configs, a runtime input
    with no description, and no classification override."""

    rows = await _rows(db_container, saved.flow_id)
    for row in rows:
        await _set_raw(db_container, row["id"], output_classification_override=None)
    await _set_raw(
        db_container,
        rows[0]["id"],
        input_type="document",
        input_config={"runtime_input": {"enabled": True}},
        output_config={},
    )
    await _set_raw(
        db_container,
        rows[1]["id"],
        user_description=None,
        input_config={},
        input_bindings={"question": "{{step_1.output.text}}"},
    )
    await _set_raw(
        db_container,
        rows[2]["id"],
        input_config={"runtime_input": False},
        input_bindings={"question": "Sammanfatta {{step_2.output.text}}"},
        output_config={},
    )
    return saved


def _differing(before: Row, after: Row) -> set[str]:
    return {column for column in _ROW_COLUMNS if before[column] != after[column]}


async def test_an_edit_that_names_no_step_leaves_every_row_as_the_frontend_saved_it(
    db_container, frontend_saved: Saved
) -> None:
    before = await _rows(db_container, frontend_saved.flow_id)

    await _apply(db_container, frontend_saved, lambda spec: (spec, frozenset()))

    assert await _rows(db_container, frontend_saved.flow_id) == before


async def test_a_rename_leaves_the_steps_it_does_not_name_as_the_frontend_saved_them(
    db_container, frontend_saved: Saved
) -> None:
    """Through the real edit compile: the policy would derive a runtime input
    description for step 1 and turn the `{}` and `{"runtime_input": false}`
    configs into NULL, and the spec shows the question with the spaces the
    validators add. None of it reaches a step the edit does not name."""

    before = await _rows(db_container, frontend_saved.flow_id)

    await _edit(
        db_container,
        frontend_saved,
        [_keep(1), _keep(2, name="Granska"), _keep(3)],
    )
    after = await _rows(db_container, frontend_saved.flow_id)

    assert after[0] == before[0]
    assert after[2] == before[2]
    # Known residue: the step the edit names still gets the policy's derivation
    # for its runtime input, so its `{}` config is written as NULL.
    assert _differing(before[1], after[1]) == {
        "user_description",
        "input_config",
        "updated_at",
    }
    assert after[1]["user_description"] == "Granska"


async def test_a_step_saved_without_a_description_keeps_none_until_an_edit_names_it(
    db_container, frontend_saved: Saved
) -> None:
    before = await _rows(db_container, frontend_saved.flow_id)
    assert before[1]["user_description"] is None

    await _edit(
        db_container,
        frontend_saved,
        [
            _keep(1),
            _keep(2, assistant_spec={"instructions": "Granska texten noga."}),
            _keep(3),
        ],
    )
    after = await _rows(db_container, frontend_saved.flow_id)

    assert after[1]["user_description"] is None
    assert after[0] == before[0] and after[2] == before[2]


async def test_a_step_that_reads_a_moved_step_by_alias_has_only_that_token_renumbered(
    db_container, frontend_saved: Saved
) -> None:
    """A step added before the producer moves it from 2 to 3: the consumer's
    row is what was saved with `step_2` written `step_3`, its author's spacing
    and every other character untouched."""

    before = await _rows(db_container, frontend_saved.flow_id)

    await _edit(
        db_container,
        frontend_saved,
        [_keep(1), _new_step(), _keep(2), _keep(3)],
    )
    after = await _rows(db_container, frontend_saved.flow_id)

    assert after[0] == before[0]
    assert _differing(before[1], after[2]) == {"step_order", "updated_at"}
    assert _differing(before[2], after[3]) == {
        "step_order",
        "input_bindings",
        "updated_at",
    }
    assert after[3]["input_bindings"] == {
        "question": "Sammanfatta {{step_3.output.text}}"
    }


async def test_a_step_the_edit_names_and_a_moved_producer_change_only_what_the_edit_says(
    db_container, frontend_saved: Saved
) -> None:
    """The consumer is renamed while a step is added before its producer: its
    row changes in its description and in the one alias its producer's new
    place asks for, not in the way its author wrote the question."""

    before = await _rows(db_container, frontend_saved.flow_id)

    await _edit(
        db_container,
        frontend_saved,
        [_keep(1), _new_step(), _keep(2), _keep(3, name="Sammanfatta")],
    )
    after = await _rows(db_container, frontend_saved.flow_id)

    assert after[3]["input_bindings"] == {
        "question": "Sammanfatta {{step_3.output.text}}"
    }
    # Known residue: the runtime-input derivation of a step the edit names.
    assert _differing(before[2], after[3]) == {
        "step_order",
        "user_description",
        "input_bindings",
        "input_config",
        "updated_at",
    }


async def test_a_step_the_edit_leaves_keeps_configuration_of_modes_it_does_not_use(
    db_container, frontend_saved: Saved
) -> None:
    """An older writer left HTTP keys in the configs of a step that is not an
    HTTP step. The flow update drops such keys from the steps it is given;
    from a step the edit does not name that would be a change nobody made."""

    rows = await _rows(db_container, frontend_saved.flow_id)
    await _set_raw(
        db_container,
        rows[1]["id"],
        output_config={"body": "x", "url": "https://example.test"},
        input_config={"timeout_seconds": 9, "runtime_input": {"enabled": False}},
    )
    before = await _rows(db_container, frontend_saved.flow_id)

    await _edit(
        db_container, frontend_saved, [_keep(1, name="Läs"), _keep(2), _keep(3)]
    )

    assert (await _rows(db_container, frontend_saved.flow_id))[1] == before[1]


async def _prompts(db_container, flow_id: UUID) -> list[str]:
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.get_flow(flow_id)
        snapshots = await service.get_flow_assistant_snapshots(flow)
        return [snapshots[step.assistant_id].instructions for step in flow.steps]


async def test_a_step_the_edit_leaves_reads_its_producer_in_its_prompt_after_a_removal(
    db_container, saved: Saved
) -> None:
    rows = await _rows(db_container, saved.flow_id)
    for row in rows:
        await _set_raw(
            db_container,
            row["id"],
            output_classification_override=None,
            input_bindings=None,
        )
    async with db_container() as container:
        # The prompt edit moves the draft on; the edit below is planned after it.
        _, _, saved.revision = await container.flow_service().update_flow_assistant(
            flow_id=saved.flow_id,
            assistant_id=rows[2]["assistant_id"],
            update=AssistantUpdateCommand(
                prompt=PromptCreate(text="Sammanfatta {{ step_2.output.text }} kort.")
            ),
        )

    await _edit(
        db_container,
        saved,
        [_keep(2, input_source="flow_input"), _keep(3)],
        removed=("existing_step_1",),
    )

    assert (await _prompts(db_container, saved.flow_id))[1] == (
        "Sammanfatta {{ step_1.output.text }} kort."
    )


_KEY = Fernet.generate_key().decode()


@contextmanager
def _encryption(active: bool) -> Iterator[EncryptionService | None]:
    """The flow service writes with this encryption for the duration."""

    encryption = EncryptionService(_KEY) if active else None
    original = FlowService.update_flow

    async def with_encryption(self: FlowService, **kwargs: Any) -> Any:
        self.encryption_service = encryption
        return await original(self, **kwargs)

    with patch.object(FlowService, "update_flow", with_encryption):
        yield encryption


def _legacy_auth(token: str) -> dict[str, Any]:
    # An HTTP auth block an older writer left on a step that is not an HTTP
    # step: inactive, and still a stored credential.
    return {
        "url": "https://example.test/legacy",
        "auth": {"mode": "bearer_token", "token": token},
    }


@pytest.mark.parametrize(
    "active", [True, False], ids=["encryption on", "encryption off"]
)
async def test_a_step_the_edit_leaves_keeps_a_stored_credential_as_it_is(
    db_container, frontend_saved: Saved, active: bool
) -> None:
    """The credential was protected when it was stored. An edit that does not
    name the step neither encrypts it again nor, with encryption off, refuses
    it as a newly typed secret."""

    rows = await _rows(db_container, frontend_saved.flow_id)
    stored = EncryptionService(_KEY).encrypt("lagrad-hemlighet")
    await _set_raw(db_container, rows[1]["id"], input_config=_legacy_auth(stored))
    before = await _rows(db_container, frontend_saved.flow_id)

    with _encryption(active):
        await _edit(
            db_container, frontend_saved, [_keep(1, name="Läs"), _keep(2), _keep(3)]
        )

    assert (await _rows(db_container, frontend_saved.flow_id))[1] == before[1]


@pytest.mark.parametrize(
    "active", [True, False], ids=["encryption on", "encryption off"]
)
async def test_a_moved_step_the_edit_leaves_keeps_its_credential_beside_a_renumbered_alias(
    db_container, frontend_saved: Saved, active: bool
) -> None:
    """The step moves, so its config is written with one alias renumbered and
    is no longer equal to the saved one; the credential in it is still the
    stored one, not encrypted again nor refused."""

    rows = await _rows(db_container, frontend_saved.flow_id)
    stored = EncryptionService(_KEY).encrypt("lagrad-hemlighet")
    config = {
        "url": "https://example.test/{{step_2.output.text}}",
        "auth": {"mode": "bearer_token", "token": stored},
    }
    await _set_raw(
        db_container, rows[2]["id"], output_mode="http_post", output_config=config
    )

    with _encryption(active):
        await _keep_edit(db_container, frontend_saved, 1, "new", 2, 3)

    assert (await _rows(db_container, frontend_saved.flow_id))[3]["output_config"] == {
        **config,
        "url": "https://example.test/{{step_3.output.text}}",
    }


async def _update_second_step(db_container, saved: Saved, input_config: Any) -> None:
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.get_flow(saved.flow_id)
        steps = list(flow.steps)
        steps[1] = steps[1].model_copy(update={"input_config": input_config})
        await service.update_flow(
            flow_id=flow.id, steps=steps, expected_revision=flow.draft_revision
        )


async def test_a_saved_step_is_protected_only_in_what_its_author_typed(
    db_container, frontend_saved: Saved
) -> None:
    """Through the flow service itself, with an HTTP step: handed back with its
    stored credential, the step keeps it byte for byte; a credential typed
    into it is encrypted."""

    rows = await _rows(db_container, frontend_saved.flow_id)
    stored = EncryptionService(_KEY).encrypt("lagrad-hemlighet")
    await _set_raw(
        db_container,
        rows[1]["id"],
        input_source="http_get",
        input_bindings=None,
        input_config=_legacy_auth(stored),
    )
    before = await _rows(db_container, frontend_saved.flow_id)

    with _encryption(True) as encryption:
        await _update_second_step(db_container, frontend_saved, _legacy_auth(stored))
        kept = (await _rows(db_container, frontend_saved.flow_id))[1]
        await _update_second_step(
            db_container, frontend_saved, _legacy_auth("nyskriven-hemlighet")
        )
    typed = (await _rows(db_container, frontend_saved.flow_id))[1]

    assert kept["input_config"] == before[1]["input_config"]
    written = typed["input_config"]["auth"]["token"]
    assert written.startswith(EncryptionService.VERSION_PREFIX)
    assert encryption is not None
    assert encryption.decrypt(written) == "nyskriven-hemlighet"


# A step the edit keeps reads the step it read, or the edit is refused. An HTTP
# input step cannot be projected into an authoring spec, so these edits are
# written as the spec a caller that keeps the row would send.


def _kept_spec(*order: int | str) -> FlowDraftSpecCore:
    """The plan order of saved steps (by position) and added ones ("new")."""

    steps = [
        StepSpec(
            plan_step_ref="new" if step == "new" else f"p{step}",
            existing_step_ref=None
            if step == "new"
            else existing_step_ref_for_order(int(step)),
            name="Ny" if step == "new" else f"Steg {step}",
            assistant_spec=AssistantSpec(instructions="Gör uppgiften."),
            input_source=InputSource.FLOW_INPUT
            if position == 0
            else InputSource.PREVIOUS_STEP,
            input_type=InputType.TEXT,
            input_bindings=_OWN_QUESTION if step == "new" and position else None,
        )
        for position, step in enumerate(order)
    ]
    return FlowDraftSpecCore(flow_name="Tre steg", steps=steps)


def _http_input(url: str, **fields: Any) -> dict[str, Any]:
    return {
        "input_source": "http_get",
        "input_bindings": None,
        "input_config": {
            "url": url,
            "auth": {"mode": "none"},
            "timeout_seconds": 30,
            **fields,
        },
    }


async def _keep_edit(
    db_container,
    saved: Saved,
    *order: int | str,
    removed: tuple[int, ...] = (),
) -> None:
    await _apply_spec(
        db_container,
        saved,
        _kept_spec(*order),
        removed=frozenset(existing_step_ref_for_order(n) for n in removed),
        updated=frozenset(),
    )


def _by_id(rows: list[Row]) -> dict[UUID, Row]:
    return {row["id"]: row for row in rows}


@pytest.mark.parametrize(
    "active", [True, False], ids=["encryption on", "encryption off"]
)
async def test_an_http_input_step_reads_its_producer_where_the_edit_puts_it(
    db_container, frontend_saved: Saved, active: bool
) -> None:
    """A step is added before the producer of an HTTP input step. The step's
    url and plain header name the producer's new place, its stored credential
    is what was stored, and no other column changes."""

    rows = await _rows(db_container, frontend_saved.flow_id)
    stored = EncryptionService(_KEY).encrypt("lagrad-hemlighet")
    await _set_raw(
        db_container,
        rows[2]["id"],
        **_http_input(
            "https://example.test/{{step_2.output.text}}",
            auth={"mode": "bearer_token", "token": stored},
            custom_headers=[
                {"name": "X-Text", "value": "{{ step_2 }}", "secret": False},
                {"name": "X-Key", "value": stored, "secret": True},
            ],
        ),
    )
    before = await _rows(db_container, frontend_saved.flow_id)

    with _encryption(active):
        await _keep_edit(db_container, frontend_saved, 1, "new", 2, 3)
    after = _by_id(await _rows(db_container, frontend_saved.flow_id))

    first, producer, http_step = (after[row["id"]] for row in before)
    assert first == before[0]
    assert (producer["step_order"], http_step["step_order"]) == (3, 4)
    assert _differing(before[1], producer) == {"step_order", "updated_at"}
    saved_config = before[2]["input_config"]
    assert http_step["input_config"] == {
        **saved_config,
        "url": "https://example.test/{{step_3.output.text}}",
        "custom_headers": [
            {"name": "X-Text", "value": "{{ step_3 }}", "secret": False},
            {"name": "X-Key", "value": stored, "secret": True},
        ],
    }
    assert http_step["input_config"]["auth"] == saved_config["auth"]
    assert _differing(before[2], http_step) == {
        "step_order",
        "input_config",
        "updated_at",
    }


async def test_an_http_delivery_follows_its_producer_and_its_own_result(
    db_container, frontend_saved: Saved
) -> None:
    rows = await _rows(db_container, frontend_saved.flow_id)
    await _set_raw(
        db_container,
        rows[2]["id"],
        output_mode="http_post",
        output_config={
            "url": "https://example.test/{{step_3}}/{{step_2.output.text}}",
            "auth": {"mode": "none"},
            "timeout_seconds": 30,
            "body": {"mode": "json_template", "template": '{"t": "{{ step_2 }}"}'},
        },
    )
    before = await _rows(db_container, frontend_saved.flow_id)

    await _keep_edit(db_container, frontend_saved, 1, "new", 2, 3)
    after = _by_id(await _rows(db_container, frontend_saved.flow_id))

    assert after[before[2]["id"]]["output_config"] == {
        **before[2]["output_config"],
        "url": "https://example.test/{{step_4}}/{{step_3.output.text}}",
        "body": {"mode": "json_template", "template": '{"t": "{{ step_3 }}"}'},
    }


@pytest.mark.parametrize(
    ("order", "removed"),
    [((1, 3), (2,)), ((1, 3, 2), ())],
    ids=["the producer is removed", "the producer moves after its reader"],
)
async def test_an_edit_that_would_rebind_a_kept_read_writes_nothing(
    db_container,
    frontend_saved: Saved,
    order: tuple[int, ...],
    removed: tuple[int, ...],
) -> None:
    rows = await _rows(db_container, frontend_saved.flow_id)
    await _set_raw(
        db_container,
        rows[2]["id"],
        **_http_input("https://example.test/{{step_2.output.text}}"),
    )
    before = await _rows(db_container, frontend_saved.flow_id)
    prompts = await _prompts(db_container, frontend_saved.flow_id)
    versions = await _version_count(db_container, frontend_saved.flow_id)
    async with db_container() as container:
        flow = await container.flow_service().get_flow(frontend_saved.flow_id)
    revision = flow.draft_revision

    with pytest.raises(BadRequestException) as exc_info:
        await _keep_edit(db_container, frontend_saved, *order, removed=removed)

    assert exc_info.value.code == "invalid_existing_step_ref"
    assert exc_info.value.context == {
        "reason": "kept_read_lost_its_producer",
        "reader_ref": "existing_step_3",
        "site": "input_config.url",
        "producer_ref": "existing_step_2",
    }
    assert await _rows(db_container, frontend_saved.flow_id) == before
    assert await _prompts(db_container, frontend_saved.flow_id) == prompts
    assert await _version_count(db_container, frontend_saved.flow_id) == versions
    async with db_container() as container:
        flow = await container.flow_service().get_flow(frontend_saved.flow_id)
    assert flow.draft_revision == revision


async def test_an_edit_that_touches_no_active_read_leaves_the_http_row_as_saved(
    db_container, frontend_saved: Saved
) -> None:
    """The producer is removed, and the only place the HTTP step names it is a
    body template that is switched off."""

    rows = await _rows(db_container, frontend_saved.flow_id)
    await _set_raw(
        db_container,
        rows[2]["id"],
        **_http_input(
            "https://example.test/",
            body={"mode": "none", "template": "{{step_2.output.text}}"},
        ),
    )
    before = await _rows(db_container, frontend_saved.flow_id)

    await _keep_edit(db_container, frontend_saved, 1, 3, removed=(2,))
    after = await _rows(db_container, frontend_saved.flow_id)

    assert _differing(before[2], after[1]) == {"step_order", "updated_at"}
    assert after[1]["input_config"] == before[2]["input_config"]


async def test_configuration_of_a_mode_the_step_does_not_run_is_not_renumbered(
    db_container, frontend_saved: Saved
) -> None:
    """An older writer left an HTTP config on a step that delivers nothing. Its
    text is data: the step moves and the config stays as saved."""

    rows = await _rows(db_container, frontend_saved.flow_id)
    leftover = {"url": "https://example.test/{{step_2.output.text}}", "note": "x"}
    await _set_raw(db_container, rows[2]["id"], output_config=leftover)

    await _edit(
        db_container, frontend_saved, [_keep(1), _new_step(), _keep(2), _keep(3)]
    )

    assert (await _rows(db_container, frontend_saved.flow_id))[3][
        "output_config"
    ] == leftover
