"""An edit writes the assistant fields it changes and nothing else.

The saved step's assistant holds state the authoring spec cannot list: a
website, integration knowledge, settings of its own. Each case applies an edit
command through the authoring service against a real database and reads the
assistant back with plain SQL. A rename makes no assistant update at all; an
instruction, knowledge or model change writes only that field; and after every
edit the assistant's row (`updated_at` aside), its attachment memberships and
its prompt text are what they were, except for the one thing the edit changed.

The assistants repository rewrites the association rows and re-versions the
prompt whenever it is called, so those rows are compared by membership and by
the selected prompt's text, never by row id or `created_at`; the rename case
makes no call and is compared row for row.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.assistant_table import (
    AssistantIntegrationKnowledge as AssistantIntegrationKnowledgeTable,
)
from eneo.database.tables.assistant_table import (
    Assistants,
    AssistantsGroups,
    AssistantsWebsites,
)
from eneo.database.tables.base_class import Base
from eneo.database.tables.collections_table import CollectionsTable
from eneo.database.tables.flow_tables import FlowSteps
from eneo.database.tables.integration_table import IntegrationKnowledge
from eneo.database.tables.spaces_table import (
    SpacesCompletionModels,
    SpacesEmbeddingModels,
)
from eneo.database.tables.tenant_table import Tenants
from eneo.database.tables.websites_table import Websites
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
)
from eneo.flows.flow_resource_bindings import (
    LocalResourceBinding,
    LocalResourceKind,
    ResourceSlotKind,
    ResourceSlotRef,
)
from eneo.main.exceptions import BadRequestException
from eneo.prompts.api.prompt_models import PromptCreate
from tests.integration.flows.test_flow_authoring_edit_step_rows import _space
from tests.unittests.flows.ai_builder.proposal_turn_builders import _make_turn

if TYPE_CHECKING:
    from eneo.flows.application.flow_draft_materialization import AssistantField

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

State = dict[str, Any]
_PROMPTS = {
    1: "Gör uppgift 1.",
    2: "Gör uppgift 2.",
    3: "Sammanfatta {{ step_2.output.text }} kort.",
}
_OWN_SETTINGS = {
    "description": "Läser underlaget noga.",
    "logging_enabled": True,
    "insight_enabled": True,
    "inline_file_text": False,
    "knowledge_mode": "tool",
    "data_retention_days": 30,
    "metadata_json": {"anteckning": "behåll"},
}


@dataclass
class Seeded:
    space_id: UUID
    flow_id: UUID
    revision: int
    assistant_ids: list[UUID]
    model_ids: list[UUID]
    group_ids: list[UUID]
    website_id: UUID
    knowledge_id: UUID


async def _seed(
    db_container, client, admin_user, completion_model_factory, user_integration_factory
) -> Seeded:
    space_id = await _space(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        tenant_id, user_id = container.user().tenant_id, container.user().id
        models = [
            await completion_model_factory(
                session, name, litellm_model_name=f"openai/{name}"
            )
            for name in ("gpt-4o", "gpt-4o-mini")
        ]
        for model in models:
            existing = await session.scalar(
                sa.select(SpacesCompletionModels.completion_model_id).where(
                    SpacesCompletionModels.space_id == space_id,
                    SpacesCompletionModels.completion_model_id == model.id,
                )
            )
            if existing is None:
                session.add(
                    SpacesCompletionModels(
                        space_id=space_id, completion_model_id=model.id
                    )
                )
        embedding_model_id = await session.scalar(
            sa.select(SpacesEmbeddingModels.embedding_model_id).where(
                SpacesEmbeddingModels.space_id == space_id
            )
        )
        assert embedding_model_id is not None
        groups = [
            CollectionsTable(
                name=label,
                size=0,
                user_id=user_id,
                tenant_id=tenant_id,
                embedding_model_id=embedding_model_id,
                space_id=space_id,
            )
            for label in ("Riktlinjer", "Lagar")
        ]
        website = Websites(
            name="Kommunen",
            url=f"https://example.invalid/{uuid4().hex[:8]}",
            download_files=False,
            crawl_type="crawl",
            update_interval="never",
            size=0,
            tenant_id=tenant_id,
            user_id=user_id,
            embedding_model_id=embedding_model_id,
            space_id=space_id,
        )
        integration = await user_integration_factory(session, tenant_id=tenant_id)
        knowledge = IntegrationKnowledge(
            name="Intranät",
            url="https://example.invalid/intranet",
            space_id=space_id,
            tenant_id=tenant_id,
            embedding_model_id=embedding_model_id,
            user_integration_id=integration.id,
        )
        session.add_all([*groups, website, knowledge])
        await session.flush()
        model_ids = [model.id for model in models]
        group_ids = [group.id for group in groups]
        website_id, knowledge_id = website.id, knowledge.id

    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id,
            name="Tre steg",
            description="Läser, analyserar och sammanfattar.",
            steps=[],
        )
        steps: list[FlowStep] = []
        assistant_ids: list[UUID] = []
        for order in (1, 2, 3):
            assistant, _ = await service.create_flow_assistant(
                flow_id=flow.id, name=f"steg{order}"
            )
            await service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant.id,
                update=AssistantUpdateCommand(
                    prompt=PromptCreate(
                        text=_PROMPTS[order],
                    )
                ),
            )
            assistant_ids.append(assistant.id)
            steps.append(
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=order,
                    user_description=f"Steg {order}",
                    input_source="flow_input" if order == 1 else "previous_step",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                    input_bindings=(
                        {"question": "{{ step_2.output.text }}"} if order == 3 else None
                    ),
                )
            )
        flow = await service.update_flow(flow_id=flow.id, steps=steps)
        session = container.session()
        for index, assistant_id in enumerate(assistant_ids):
            await session.execute(
                sa.update(Assistants)
                .where(Assistants.id == assistant_id)
                .values(completion_model_id=model_ids[index % 2], **_OWN_SETTINGS)
            )
            await session.execute(
                sa.insert(AssistantsGroups).values(
                    assistant_id=assistant_id, group_id=group_ids[index % 2]
                )
            )
            await session.execute(
                sa.insert(AssistantsWebsites).values(
                    assistant_id=assistant_id, website_id=website_id
                )
            )
            await session.execute(
                sa.insert(AssistantIntegrationKnowledgeTable).values(
                    assistant_id=assistant_id, integration_knowledge_id=knowledge_id
                )
            )
    return Seeded(
        space_id,
        flow.id,
        flow.draft_revision,
        assistant_ids,
        model_ids,
        group_ids,
        website_id,
        knowledge_id,
    )


@pytest.fixture
async def seeded(
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
    completion_model_factory,
    user_integration_factory,
) -> Seeded:
    return await _seed(
        db_container,
        client,
        admin_user,
        completion_model_factory,
        user_integration_factory,
    )


def _plain(value: Any) -> Any:
    if isinstance(value, (UUID, datetime)):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}  # pyright: ignore
    if isinstance(value, list):
        return [_plain(v) for v in value]  # pyright: ignore
    return value


def _children_of_assistants() -> list[tuple[sa.Table, list[sa.Column[Any]]]]:
    assistants = Base.metadata.tables["assistants"]
    found: list[tuple[sa.Table, list[sa.Column[Any]]]] = []
    for table in sorted(Base.metadata.tables.values(), key=lambda t: t.name):
        columns = [
            fk.parent for fk in table.foreign_keys if fk.column.table is assistants
        ]
        if columns and table.name not in {"flow_steps", "assistants"}:
            found.append((table, columns))
    return found


async def _state(db_container, assistant_id: UUID, *, strict: bool) -> State:
    """The assistant as the database holds it. Its row without `updated_at`,
    the rows that hang off it (every column when `strict`, otherwise their
    content without id and timestamps, as a sorted list: the membership), and
    the text of the selected prompt."""

    async with db_container() as container:
        session = container.session()
        table = Base.metadata.tables["assistants"]
        row = (
            (await session.execute(sa.select(table).where(table.c.id == assistant_id)))
            .one()
            ._mapping
        )  # pyright: ignore[reportPrivateUsage]
        state: State = {
            "row": {k: _plain(v) for k, v in row.items() if k != "updated_at"}
        }
        for child, columns in _children_of_assistants():
            rows = (
                await session.execute(
                    sa.select(child).where(
                        sa.or_(*(c == assistant_id for c in columns))
                    )
                )
            ).all()
            ignored = set() if strict else {"id", "created_at", "updated_at"}
            content = [
                {k: _plain(v) for k, v in r._mapping.items() if k not in ignored}  # pyright: ignore[reportPrivateUsage]
                for r in rows
            ]
            if child.name == "prompts_assistants" and not strict:
                continue  # a prompt is compared by its selected text below
            state[child.name] = sorted(
                content, key=lambda item: repr(sorted(item.items()))
            )
        state["prompt"] = await session.scalar(
            sa.text(
                "select p.text from prompts p join prompts_assistants pa "
                "on pa.prompt_id = p.id where pa.assistant_id = :a and pa.is_selected"
            ),
            {"a": assistant_id},
        )
    return state


async def _current_spec(db_container, seeded: Seeded) -> FlowDraftSpecCore:
    """The saved flow as the authoring spec an edit starts from."""

    async with db_container() as container:
        service = container.flow_service()
        flow = await service.get_flow(seeded.flow_id)
        return current_flow_authoring_spec(
            current_steps=list(flow.steps),
            flow_name=flow.name,
            flow_description=flow.description,
            assistant_snapshots=await service.get_flow_assistant_snapshots(flow),
            assistant_snapshot_projector=lambda snapshot: AssistantSpec(
                instructions=snapshot.instructions
            ),
        )


async def _apply_spec(
    db_container,
    seeded: Seeded,
    spec: FlowDraftSpecCore,
    fields: dict[str, frozenset[AssistantField]],
    *,
    bindings: tuple[LocalResourceBinding, ...] = (),
    updated: frozenset[str] = frozenset({"existing_step_2"}),
    removed: frozenset[str] = frozenset(),
) -> dict[UUID, int]:
    """The edit command applied; how many assistant updates it made, by assistant."""

    calls: dict[UUID, int] = {}
    original = FlowService.update_flow_assistant

    async def counted(self: FlowService, *, assistant_id: UUID, **kwargs: Any) -> Any:
        calls[assistant_id] = calls.get(assistant_id, 0) + 1
        return await original(self, assistant_id=assistant_id, **kwargs)

    origin = AIBuilderFlowAuthoringOrigin(
        session_id=uuid4(),
        plan_id=uuid4(),
        spec_hash=spec.spec_hash(),
        applied_at=datetime.now(timezone.utc),
    )
    async with db_container() as container:
        with patch.object(FlowService, "update_flow_assistant", counted):
            await FlowAuthoringCommandService().apply(
                command=EditFlowAuthoringCommand(
                    space_id=seeded.space_id,
                    flow_id=seeded.flow_id,
                    expected_revision=seeded.revision,
                    spec=spec,
                    removed_existing_step_refs=removed,
                    updated_existing_step_refs=updated,
                    updated_assistant_fields=fields,
                    origin=origin,
                    resource_bindings=bindings,
                ),
                flow_service=container.flow_service(),
                origin_policy=AIBuilderAuthoringPolicy(origin),
            )
    return {a: n for a, n in calls.items() if a in seeded.assistant_ids}


def _keep(order: int, **changes: Any) -> dict[str, Any]:
    """A saved step in the edit's ordered list, with what changes on it."""

    return {"kind": "modify", "existing_step_ref": f"existing_step_{order}", **changes}


async def _catalog(db_container, seeded: Seeded):
    async with db_container() as container:
        space = await container.space_service().get_space(seeded.space_id)
        return build_ai_builder_resource_catalog(
            available_models=serialize_space_models(space),
            available_kbs=serialize_space_kbs(space),
        )


async def _propose(
    db_container,
    seeded: Seeded,
    steps: list[dict[str, Any]],
    removed: tuple[str, ...] = (),
) -> ProposalReady:
    """The real edit compile of the model's ordered steps against the saved
    flow: the plan a person approves."""

    catalog = await _catalog(db_container, seeded)
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.get_flow(seeded.flow_id)
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
            resource_catalog=catalog,
            compile_context=create_compile_context_from_planning_state(
                None, ui_language="sv"
            ),
        )
    assert isinstance(outcome, ProposalReady), outcome
    return outcome


async def _apply_proposal(
    db_container, seeded: Seeded, outcome: ProposalReady
) -> dict[UUID, int]:
    """The plan applied with the assistant fields and step lists the
    lifecycle derives from its approval. Returns the assistant updates made,
    by saved assistant."""

    content = outcome.compiled.content
    session = SimpleNamespace(target_kind=TargetKind.EDIT, id=uuid4())
    plan = SimpleNamespace(id=uuid4(), proposal=SimpleNamespace(content=content))
    return await _apply_spec(
        db_container,
        seeded,
        content.spec,
        _updated_assistant_fields_for_apply(session=session, plan=plan),  # type: ignore[arg-type]
        bindings=outcome.compiled.resource_bindings,
        updated=_updated_existing_step_refs_for_apply(session=session, plan=plan),  # type: ignore[arg-type]
        removed=_removed_existing_step_refs_for_apply(session=session, plan=plan),  # type: ignore[arg-type]
    )


async def _edit(
    db_container,
    seeded: Seeded,
    steps: list[dict[str, Any]],
    removed: tuple[str, ...] = (),
) -> dict[UUID, int]:
    """The whole chain a plan goes through: proposed, then applied at once."""

    return await _apply_proposal(
        db_container, seeded, await _propose(db_container, seeded, steps, removed)
    )


async def _prompt(db_container, assistant_id: UUID) -> str:
    return (await _state(db_container, assistant_id, strict=False))["prompt"]


def _collection_binding(group_id: UUID) -> LocalResourceBinding:
    return LocalResourceBinding(
        slot_ref=ResourceSlotRef(
            kind=ResourceSlotKind.KNOWLEDGE, slot="riktlinjer", label="Riktlinjer"
        ),
        local_kind=LocalResourceKind.COLLECTION,
        local_id=group_id,
    )


async def _states(db_container, seeded: Seeded, *, strict: bool) -> list[State]:
    return [await _state(db_container, a, strict=strict) for a in seeded.assistant_ids]


async def test_a_rename_makes_no_assistant_update_and_leaves_every_assistant_row_for_row(
    db_container, seeded: Seeded
) -> None:
    before = await _states(db_container, seeded, strict=True)

    calls = await _edit(
        db_container, seeded, [_keep(1), _keep(2, name="Granska"), _keep(3)]
    )

    assert calls == {}
    assert await _states(db_container, seeded, strict=True) == before


async def test_an_instruction_edit_changes_the_prompt_and_keeps_everything_else(
    db_container, seeded: Seeded
) -> None:
    await _direct_prompt_edit(
        db_container, seeded, "Gör uppgift 2.", description="Skriven av Anna."
    )
    before = await _states(db_container, seeded, strict=False)

    calls = await _edit(
        db_container,
        seeded,
        [
            _keep(1),
            _keep(2, assistant_spec={"instructions": "Gör uppgift 2 och sammanfatta."}),
            _keep(3),
        ],
    )
    after = await _states(db_container, seeded, strict=False)

    assert calls == {seeded.assistant_ids[1]: 1}
    assert after[0] == before[0] and after[2] == before[2]
    assert after[1]["prompt"] == "Gör uppgift 2 och sammanfatta."
    assert await _selected_prompt(db_container, seeded.assistant_ids[1]) == (
        "Gör uppgift 2 och sammanfatta.",
        "Skriven av Anna.",
    )
    # Model, settings, and every membership: the group, the website and the
    # integration knowledge the spec has no way to list.
    assert {**after[1], "prompt": None} == {**before[1], "prompt": None}


async def test_a_knowledge_edit_changes_the_collections_and_keeps_everything_else(
    db_container, seeded: Seeded
) -> None:
    before = await _states(db_container, seeded, strict=False)
    catalog = await _catalog(db_container, seeded)
    first = next(
        entry
        for entry in catalog.knowledge_bases
        if entry.local_ref == str(seeded.group_ids[0])
    )

    calls = await _edit(
        db_container,
        seeded,
        [
            _keep(1),
            _keep(2, assistant_spec={"knowledge_refs": [first.authoring_ref]}),
            _keep(3),
        ],
    )
    after = await _states(db_container, seeded, strict=False)

    assert calls == {seeded.assistant_ids[1]: 1}
    assert after[0] == before[0] and after[2] == before[2]
    assert [row["group_id"] for row in after[1]["assistants_groups"]] == [
        str(seeded.group_ids[0])
    ]
    without_groups = lambda state: {  # noqa: E731
        key: value for key, value in state.items() if key != "assistants_groups"
    }
    assert without_groups(after[1]) == without_groups(before[1])
    assert after[1]["assistants_websites"] == before[1]["assistants_websites"] != []
    assert (
        after[1]["assistant_integration_knowledge"]
        == before[1]["assistant_integration_knowledge"]
        != []
    )


async def test_a_step_turned_into_one_without_a_model_loses_the_model_and_nothing_else(
    db_container, seeded: Seeded
) -> None:
    before = await _states(db_container, seeded, strict=False)

    calls = await _edit(
        db_container, seeded, [_keep(1), _keep(2, output_type="pdf"), _keep(3)]
    )
    after = await _states(db_container, seeded, strict=False)

    assert calls == {seeded.assistant_ids[1]: 1}
    assert after[0] == before[0] and after[2] == before[2]
    assert after[1]["row"]["completion_model_id"] is None
    assert {
        **after[1],
        "row": {**after[1]["row"], "completion_model_id": None},
    } == {**before[1], "row": {**before[1]["row"], "completion_model_id": None}}


async def _without_a_completion_model(db_container, seeded: Seeded) -> None:
    """The second step already renders a PDF and its assistant still holds the
    model it had when the step read text."""

    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowSteps)
            .where(FlowSteps.flow_id == seeded.flow_id, FlowSteps.step_order == 2)
            .values(output_type="pdf", output_mode="render_verbatim")
        )


async def test_editing_the_prompt_of_a_step_that_runs_no_model_leaves_its_stored_model(
    db_container, seeded: Seeded
) -> None:
    await _without_a_completion_model(db_container, seeded)
    before = await _state(db_container, seeded.assistant_ids[1], strict=False)
    assert before["row"]["completion_model_id"] is not None

    calls = await _edit(
        db_container,
        seeded,
        [
            _keep(1),
            _keep(2, assistant_spec={"instructions": "Rendera svaret."}),
            _keep(3),
        ],
    )
    after = await _state(db_container, seeded.assistant_ids[1], strict=False)

    assert calls == {seeded.assistant_ids[1]: 1}
    assert after["prompt"] == "Rendera svaret."
    assert after["row"] == before["row"]


async def test_editing_the_knowledge_of_a_step_that_runs_no_model_leaves_its_stored_model(
    db_container, seeded: Seeded
) -> None:
    await _without_a_completion_model(db_container, seeded)
    before = await _state(db_container, seeded.assistant_ids[1], strict=False)
    catalog = await _catalog(db_container, seeded)
    first = next(
        entry
        for entry in catalog.knowledge_bases
        if entry.local_ref == str(seeded.group_ids[0])
    )

    calls = await _edit(
        db_container,
        seeded,
        [
            _keep(1),
            _keep(2, assistant_spec={"knowledge_refs": [first.authoring_ref]}),
            _keep(3),
        ],
    )
    after = await _state(db_container, seeded.assistant_ids[1], strict=False)

    assert calls == {seeded.assistant_ids[1]: 1}
    assert after["row"] == before["row"]


async def test_steps_are_written_whatever_the_assistants_fields_are(
    db_container, seeded: Seeded
) -> None:
    """The step row is patched by the edit itself; the assistant update is a
    separate write that only an assistant field triggers."""

    await _edit(db_container, seeded, [_keep(1), _keep(2, name="Granska"), _keep(3)])

    async with db_container() as container:
        names = list(
            (
                await container.session().scalars(
                    sa.select(FlowSteps.user_description)
                    .where(FlowSteps.flow_id == seeded.flow_id)
                    .order_by(FlowSteps.step_order)
                )
            ).all()
        )
    assert names == ["Steg 1", "Granska", "Steg 3"]


_PREP = {"kind": "add", "step": {"name": "Förbered", "instructions": "Förbered."}}


async def test_a_prompt_that_reads_a_step_an_added_step_pushes_down_is_rewritten(
    db_container, seeded: Seeded
) -> None:
    """The consumer only gets a new name, and its prompt reads step 2, which is
    now the added step."""

    calls = await _edit(
        db_container,
        seeded,
        [_keep(1), _PREP, _keep(2), _keep(3, name="Använd analysen")],
    )

    assert calls == {seeded.assistant_ids[2]: 1}
    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "Sammanfatta {{ step_3.output.text }} kort."
    )


async def test_a_prompt_that_reads_a_step_after_the_first_is_removed_is_rewritten(
    db_container, seeded: Seeded
) -> None:
    """Step 1 goes, so the producer is step 1 and the consumer step 2: reading
    step 2 would be reading itself."""

    calls = await _edit(
        db_container,
        seeded,
        [_keep(2, input_source="flow_input"), _keep(3, name="Använd analysen")],
        removed=("existing_step_1",),
    )

    assert calls == {seeded.assistant_ids[2]: 1}
    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "Sammanfatta {{ step_1.output.text }} kort."
    )


async def test_a_prompt_that_reads_a_step_two_steps_swap_places_around_is_rewritten(
    db_container, seeded: Seeded
) -> None:
    calls = await _edit(
        db_container,
        seeded,
        [
            _keep(2, input_source="flow_input"),
            _keep(1, input_source="previous_step"),
            _keep(3, name="Använd analysen"),
        ],
    )

    assert calls == {seeded.assistant_ids[2]: 1}
    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "Sammanfatta {{ step_1.output.text }} kort."
    )


async def test_a_renumbered_step_whose_prompt_reads_no_step_is_not_written(
    db_container, seeded: Seeded
) -> None:
    calls = await _edit(db_container, seeded, [_keep(1), _PREP, _keep(2), _keep(3)])

    assert seeded.assistant_ids[0] not in calls
    assert seeded.assistant_ids[1] not in calls


def _renamed_second_step(spec: FlowDraftSpecCore) -> FlowDraftSpecCore:
    steps = list(spec.steps)
    steps[1] = steps[1].model_copy(update={"name": "Granska"})
    return spec.model_copy(update={"steps": steps})


async def _direct_prompt_edit(
    db_container,
    seeded: Seeded,
    text: str,
    *,
    order: int = 2,
    description: str | None = None,
) -> None:
    """Someone else edits a step's assistant directly (the second by default)."""

    async with db_container() as container:
        await container.flow_service().update_flow_assistant(
            flow_id=seeded.flow_id,
            assistant_id=seeded.assistant_ids[order - 1],
            update=AssistantUpdateCommand(
                prompt=PromptCreate(text=text, description=description)
            ),
        )


async def test_a_rename_applied_after_someone_edits_the_assistant_keeps_that_edit(
    db_container, seeded: Seeded
) -> None:
    """The approval was made against the old prompt. A rename does not write
    the assistant, so it cannot put the old prompt back."""

    spec = _renamed_second_step(await _current_spec(db_container, seeded))
    await _direct_prompt_edit(db_container, seeded, "Ändrad av någon annan.")

    calls = await _apply_spec(db_container, seeded, spec, fields={})

    assert calls == {}
    assert (await _state(db_container, seeded.assistant_ids[1], strict=False))[
        "prompt"
    ] == "Ändrad av någon annan."


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Fencing gap, not fixed here: FlowService.update_flow_assistant does "
        "not advance the flow's draft_revision, so a plan approved before a "
        "direct assistant edit still applies on top of it."
    ),
)
async def test_an_assistant_edit_advances_the_draft_revision_that_fences_approvals(
    db_container, seeded: Seeded
) -> None:
    await _direct_prompt_edit(db_container, seeded, "Ändrad av någon annan.")

    async with db_container() as container:
        revision = (
            await container.flow_service().get_flow(seeded.flow_id)
        ).draft_revision

    assert revision != seeded.revision


_COLLEAGUE = "Direktredigerad {{ step_2.output.text }} av kollega."


@pytest.mark.parametrize(
    "consumer",
    [_keep(3), _keep(3, name="Använd analysen")],
    ids=["not in the plan", "renamed in the plan"],
)
async def test_a_moved_step_keeps_a_direct_edit_made_after_the_plan_with_its_alias_renumbered(
    db_container, seeded: Seeded, consumer: dict[str, Any]
) -> None:
    """The plan was made before a colleague rewrote step 3's prompt. The edit
    only moves step 3's producer, so the prompt written is the colleague's,
    reading the producer where it now is; the plan's copy is not put back."""

    proposal = await _propose(
        db_container, seeded, [_keep(1), _PREP, _keep(2), consumer]
    )
    await _direct_prompt_edit(db_container, seeded, _COLLEAGUE, order=3)

    calls = await _apply_proposal(db_container, seeded, proposal)

    assert calls == {seeded.assistant_ids[2]: 1}
    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "Direktredigerad {{ step_3.output.text }} av kollega."
    )


async def test_a_moved_alias_is_renumbered_with_the_authors_spacing(
    db_container, seeded: Seeded
) -> None:
    await _direct_prompt_edit(
        db_container,
        seeded,
        "A {{step_2.output.text}} B {{ step_1.output.text }} C",
        order=3,
    )

    await _edit(db_container, seeded, [_keep(1), _PREP, _keep(2), _keep(3)])

    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "A {{step_3.output.text}} B {{ step_1.output.text }} C"
    )


async def _classify_first_step_unread(
    db_container,
    seeded: Seeded,
    second_step: dict[str, Any],
    *,
    classifications_on: bool = True,
) -> None:
    """Step 1 is classified above what the other steps' models may read, and
    nothing reads it: `second_step` is how step 2 is kept from it. The level
    only applies while the organization has classifications turned on."""

    async with db_container() as container:
        await container.session().execute(
            sa.update(Tenants)
            .where(Tenants.id == container.user().tenant_id)
            .values(security_enabled=classifications_on)
        )
        await container.session().execute(
            sa.update(FlowSteps)
            .where(FlowSteps.flow_id == seeded.flow_id, FlowSteps.step_order == 1)
            .values(output_classification_override=2)
        )
        await container.session().execute(
            sa.update(FlowSteps)
            .where(FlowSteps.flow_id == seeded.flow_id, FlowSteps.step_order == 2)
            .values(**second_step)
        )


async def test_a_prompt_renumbered_by_a_removal_is_judged_against_the_steps_it_is_saved_with(
    db_container, seeded: Seeded
) -> None:
    """Step 1 is classified above what step 3's model may read, and nothing
    reads it. Removing it makes step 3's prompt read `{{ step_1 }}`, which is
    then the unclassified producer: judged against the saved steps, it would
    read the classified step that is being removed."""

    await _classify_first_step_unread(
        db_container, seeded, {"input_source": "flow_input"}
    )

    calls = await _edit(
        db_container,
        seeded,
        [_keep(2), _keep(3)],
        removed=("existing_step_1",),
    )

    assert calls == {seeded.assistant_ids[2]: 1}
    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "Sammanfatta {{ step_1.output.text }} kort."
    )


async def test_a_prompt_that_reads_a_classified_step_in_the_saved_flow_is_refused(
    db_container, seeded: Seeded
) -> None:
    """The flow update still judges every prompt against the steps it is saved
    with: an instruction edit that makes step 3 read the classified step 1 is
    refused, and nothing of the edit is kept."""

    await _classify_first_step_unread(
        db_container, seeded, {"input_bindings": {"question": "Granska underlaget."}}
    )
    before = await _states(db_container, seeded, strict=False)

    with pytest.raises(BadRequestException, match="security classification"):
        await _edit(
            db_container,
            seeded,
            [
                _keep(1),
                _keep(2),
                _keep(
                    3, assistant_spec={"instructions": "Läs {{ step_1.output.text }}."}
                ),
            ],
        )

    assert await _states(db_container, seeded, strict=False) == before


async def test_a_prompt_that_reads_a_classified_step_is_kept_while_classifications_are_off(
    db_container, seeded: Seeded
) -> None:
    """The stored level stays on step 1, but with the organization's
    classifications turned off nothing applies it: the edit the test above
    refuses is saved."""

    await _classify_first_step_unread(
        db_container,
        seeded,
        {"input_bindings": {"question": "Granska underlaget."}},
        classifications_on=False,
    )

    calls = await _edit(
        db_container,
        seeded,
        [
            _keep(1),
            _keep(2),
            _keep(3, assistant_spec={"instructions": "Läs {{ step_1.output.text }}."}),
        ],
    )

    assert calls == {seeded.assistant_ids[2]: 1}
    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "Läs {{ step_1.output.text }}."
    )


async def test_a_prompt_that_reads_both_steps_before_an_added_first_step_reads_them_moved(
    db_container, seeded: Seeded
) -> None:
    await _direct_prompt_edit(
        db_container,
        seeded,
        "Jämför {{step_1.output.text}} med {{ step_2.output.text }}.",
        order=3,
    )

    calls = await _edit(
        db_container,
        seeded,
        [
            {"kind": "add", "step": {"name": "Först", "instructions": "Börja."}},
            _keep(1, input_source="previous_step"),
            _keep(2),
            _keep(3),
        ],
    )

    assert calls == {seeded.assistant_ids[2]: 1}
    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "Jämför {{step_2.output.text}} med {{ step_3.output.text }}."
    )


async def test_a_prompt_that_reads_two_steps_that_swap_names_them_in_their_new_places(
    db_container, seeded: Seeded
) -> None:
    """The steps swap; the prompt still compares the first step's result with
    the second's, by their new aliases, in the same order its bindings do."""

    await _direct_prompt_edit(
        db_container,
        seeded,
        "Jämför {{ step_1.output.text }} med {{ step_2.output.text }}.",
        order=3,
    )

    calls = await _edit(
        db_container,
        seeded,
        [
            _keep(2, input_source="flow_input"),
            _keep(1, input_source="previous_step"),
            _keep(3),
        ],
    )

    assert calls == {seeded.assistant_ids[2]: 1}
    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "Jämför {{ step_2.output.text }} med {{ step_1.output.text }}."
    )


async def _selected_prompt(db_container, assistant_id: UUID) -> tuple[str, str | None]:
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.text(
                    "select p.text, p.description from prompts p join "
                    "prompts_assistants pa on pa.prompt_id = p.id "
                    "where pa.assistant_id = :a and pa.is_selected"
                ),
                {"a": assistant_id},
            )
        ).one()
    return row.text, row.description


async def test_a_renumbered_prompt_keeps_its_whitespace_and_description(
    db_container, seeded: Seeded
) -> None:
    """Byte for byte the stored prompt apart from the alias: its surrounding
    whitespace and its description stay."""

    await _direct_prompt_edit(
        db_container,
        seeded,
        "\nLäs {{ step_2.output.text }}\n",
        order=3,
        description="Skriven av Anna.",
    )

    await _edit(db_container, seeded, [_keep(1), _PREP, _keep(2), _keep(3)])

    assert await _selected_prompt(db_container, seeded.assistant_ids[2]) == (
        "\nLäs {{ step_3.output.text }}\n",
        "Skriven av Anna.",
    )


async def _share_the_second_steps_assistant(db_container, seeded: Seeded) -> UUID:
    """Step 3 is given step 2's assistant, whose prompt reads step 1."""

    shared = seeded.assistant_ids[1]
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowSteps)
            .where(FlowSteps.flow_id == seeded.flow_id, FlowSteps.step_order == 3)
            .values(assistant_id=shared)
        )
    await _direct_prompt_edit(db_container, seeded, "Läs {{ step_1.output.text }}.")
    return shared


async def test_an_instruction_change_to_an_assistant_two_steps_share_is_refused(
    db_container, seeded: Seeded
) -> None:
    """The change is asked for step 2 only; written to the assistant it would
    change step 3 too. The apply is refused and nothing of it is kept."""

    shared = await _share_the_second_steps_assistant(db_container, seeded)
    before = await _state(db_container, shared, strict=False)
    rows_before = await _step_rows(db_container, seeded)

    with pytest.raises(BadRequestException, match="Ask the Builder again"):
        await _edit(
            db_container,
            seeded,
            [
                _keep(1),
                _keep(2, assistant_spec={"instructions": "Läs noga."}),
                _keep(3),
            ],
        )

    assert await _state(db_container, shared, strict=False) == before
    assert await _step_rows(db_container, seeded) == rows_before


async def test_a_rename_of_a_step_that_shares_its_assistant_makes_no_assistant_call(
    db_container, seeded: Seeded
) -> None:
    await _share_the_second_steps_assistant(db_container, seeded)

    calls = await _edit(
        db_container, seeded, [_keep(1), _keep(2), _keep(3, name="Sammanfatta")]
    )

    assert calls == {}


async def test_a_move_writes_an_assistant_two_steps_share_once(
    db_container, seeded: Seeded
) -> None:
    shared = await _share_the_second_steps_assistant(db_container, seeded)

    calls = await _edit(
        db_container,
        seeded,
        [
            {"kind": "add", "step": {"name": "Först", "instructions": "Börja."}},
            _keep(1, input_source="previous_step"),
            _keep(2),
            _keep(3),
        ],
    )

    assert calls == {shared: 1}
    assert await _prompt(db_container, shared) == "Läs {{ step_2.output.text }}."


async def _step_rows(db_container, seeded: Seeded) -> list[dict[str, Any]]:
    async with db_container() as container:
        result = await container.session().execute(
            sa.select(FlowSteps.__table__)
            .where(FlowSteps.flow_id == seeded.flow_id)
            .order_by(FlowSteps.step_order)
        )
        return [dict(row._mapping) for row in result]  # pyright: ignore[reportPrivateUsage]
