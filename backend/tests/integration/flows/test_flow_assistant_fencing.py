"""A step's assistant is part of its flow's draft, so writing it is a write to
the draft: it advances `draft_revision` once, fenced on the caller's revision,
in the transaction that writes the assistant. An apply locks the flow before it
writes any assistant and advances the revision once for all of them.

The concurrency cases hold one transaction open while the other writer runs and
wait until that writer is blocked on a lock before letting the first finish.
Every writer takes the flow row before an assistant row, so each pair either
completes or is refused with `stale_revision`; a writer taking them the other
way round deadlocks, and Postgres aborts one of the two.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.assistants.assistant_service import AssistantService
from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import Flows, FlowTemplateAssets
from eneo.flows.application.flow_authoring_command import (
    FlowAuthoringCommandService,
    TemplateAttachmentIntent,
)
from eneo.flows.application.flow_draft_materialization_executor import (
    FlowDraftMaterializer,
)
from eneo.flows.application.flow_service import FlowService
from eneo.flows.domain.flow import FlowStep
from eneo.flows.flow_resource_bindings import FlowResourceBindingSource
from eneo.flows.flow_template_asset_service import FlowTemplateAssetService
from eneo.main.exceptions import BadRequestException
from eneo.prompts.api.prompt_models import PromptCreate
from tests.integration.flows.test_flow_assistant_update_siblings import (
    _admin_token_and_space,
)
from tests.integration.flows.test_flow_authoring_edit_assistants import (
    Seeded,
    _apply_proposal,
    _edit,
    _keep,
    _prompt,
    _propose,
    _seed,
    _step_rows,
)
from tests.integration.flows.test_flow_template_attachment_persistence import (
    _create_flow_and_file,
    _template_changeset,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_TIMEOUT = 20


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


@dataclass
class Editable:
    """A draft flow of one step, edited over HTTP by its space's admin."""

    token: str
    flow_id: UUID
    assistant_id: UUID
    revision: int


@pytest.fixture
async def editable(
    client, db_container, admin_user, patch_auth_service_jwt
) -> Editable:
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id, name="Ett steg", description=None, steps=[]
        )
        assistant, _ = await service.create_flow_assistant(
            flow_id=flow.id, name="steg1"
        )
        await service.update_flow_assistant(
            flow_id=flow.id,
            assistant_id=assistant.id,
            update=_prompt_update("Gör uppgiften."),
        )
        flow = await service.update_flow(
            flow_id=flow.id,
            steps=[
                FlowStep(
                    assistant_id=assistant.id,
                    step_order=1,
                    user_description="Steg 1",
                    input_source="flow_input",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                )
            ],
        )
    return Editable(token, flow.id, assistant.id, flow.draft_revision)


async def _assistant_row(db_container, assistant_id: UUID) -> dict[str, Any]:
    async with db_container() as container:
        row = (
            await container.session().execute(
                sa.select(Assistants.__table__).where(Assistants.id == assistant_id)
            )
        ).one()
    return dict(row._mapping)  # pyright: ignore[reportPrivateUsage]


async def _revision(db_container, flow_id: UUID) -> int:
    async with db_container() as container:
        revision = await container.session().scalar(
            sa.select(Flows.draft_revision).where(Flows.id == flow_id)
        )
    assert revision is not None
    return revision


async def _flow_updated_at(db_container, flow_id: UUID) -> datetime:
    async with db_container() as container:
        updated_at = await container.session().scalar(
            sa.select(Flows.updated_at).where(Flows.id == flow_id)
        )
    assert updated_at is not None
    return updated_at


def _prompt_update(text: str) -> AssistantUpdateCommand:
    return AssistantUpdateCommand(prompt=PromptCreate(text=text))


async def _flow_assistant_ids(db_container, flow_id: UUID) -> set[UUID]:
    async with db_container() as container:
        return set(
            (
                await container.session().scalars(
                    sa.select(Assistants.id).where(
                        Assistants.managing_flow_id == flow_id
                    )
                )
            ).all()
        )


# --- The PATCH endpoint ------------------------------------------------------


def _assistant_url(editable: Editable) -> str:
    return f"/api/v1/flows/{editable.flow_id}/assistants/{editable.assistant_id}/"


def _auth(editable: Editable) -> dict[str, str]:
    return {"Authorization": f"Bearer {editable.token}"}


async def test_an_assistant_update_advances_the_draft_revision_once_and_returns_it(
    client, db_container, editable: Editable
) -> None:
    edited_before = await _flow_updated_at(db_container, editable.flow_id)
    response = await client.patch(
        _assistant_url(editable),
        json={"prompt": {"text": "Ändrad direkt."}},
        headers=_auth(editable),
    )

    assert response.status_code == 200, response.text
    assert response.json()["draft_revision"] == editable.revision + 1
    assert response.json()["prompt"]["text"] == "Ändrad direkt."
    flow = await client.get(
        f"/api/v1/flows/{editable.flow_id}/", headers=_auth(editable)
    )
    assert flow.json()["draft_revision"] == editable.revision + 1
    # An edit of a step's prompt is an edit of the draft.
    assert await _flow_updated_at(db_container, editable.flow_id) > edited_before


async def test_an_assistant_update_behind_the_draft_is_refused_and_writes_nothing(
    client, db_container, editable: Editable
) -> None:
    first = await client.patch(
        _assistant_url(editable),
        json={"prompt": {"text": "Först."}, "expected_revision": editable.revision},
        headers=_auth(editable),
    )
    assert first.status_code == 200, first.text
    before = await _assistant_row(db_container, editable.assistant_id)

    stale = await client.patch(
        _assistant_url(editable),
        json={
            "name": "Sent namn",
            "prompt": {"text": "Sent."},
            "expected_revision": editable.revision,
        },
        headers=_auth(editable),
    )

    assert stale.status_code == 400, stale.text
    assert stale.json()["code"] == "stale_revision"
    assert stale.json()["context"]["expected_revision"] == editable.revision
    assert await _assistant_row(db_container, editable.assistant_id) == before
    assert await _prompt(db_container, editable.assistant_id) == "Först."
    assert await _revision(db_container, editable.flow_id) == editable.revision + 1


async def test_a_refused_assistant_update_leaves_the_revision(
    client, db_container, editable: Editable
) -> None:
    before = await _assistant_row(db_container, editable.assistant_id)

    response = await client.patch(
        _assistant_url(editable),
        json={"name": "Nytt namn", "completion_model": {"id": str(uuid4())}},
        headers=_auth(editable),
    )

    assert 400 <= response.status_code < 500, response.text
    assert await _assistant_row(db_container, editable.assistant_id) == before
    assert await _revision(db_container, editable.flow_id) == editable.revision


async def test_an_assistant_update_of_a_published_flow_is_refused_without_advancing(
    client, db_container, editable: Editable
) -> None:
    async with db_container() as container:
        published = await container.flow_service().publish_flow(
            flow_id=editable.flow_id
        )

    response = await client.patch(
        _assistant_url(editable),
        json={"prompt": {"text": "Ändrad direkt."}},
        headers=_auth(editable),
    )

    assert response.status_code == 400, response.text
    assert await _revision(db_container, editable.flow_id) == published.draft_revision
    assert await _prompt(db_container, editable.assistant_id) == "Gör uppgiften."


async def test_creating_and_deleting_an_unused_assistant_leaves_the_revision(
    client, db_container, editable: Editable
) -> None:
    created = await client.post(
        f"/api/v1/flows/{editable.flow_id}/assistants/",
        json={"name": "Nästa steg"},
        headers=_auth(editable),
    )
    assert created.status_code == 201, created.text
    assert await _revision(db_container, editable.flow_id) == editable.revision

    deleted = await client.delete(
        f"/api/v1/flows/{editable.flow_id}/assistants/{created.json()['id']}/",
        headers=_auth(editable),
    )
    assert deleted.status_code == 204, deleted.text
    assert await _revision(db_container, editable.flow_id) == editable.revision


# --- The apply ---------------------------------------------------------------


async def test_an_apply_writing_several_assistants_advances_the_revision_once(
    db_container, seeded: Seeded
) -> None:
    calls = await _edit(
        db_container,
        seeded,
        [
            _keep(1, assistant_spec={"instructions": "Ny uppgift 1."}),
            _keep(2, assistant_spec={"instructions": "Ny uppgift 2."}),
            _keep(3),
        ],
    )

    assert calls == {seeded.assistant_ids[0]: 1, seeded.assistant_ids[1]: 1}
    assert await _revision(db_container, seeded.flow_id) == seeded.revision + 1


async def test_an_assistant_edit_committed_after_the_apply_was_prepared_refuses_it(
    db_container, seeded: Seeded
) -> None:
    """The plan was compiled and prepared against revision R; a colleague's
    prompt edit commits before the apply reaches the flow. The apply is
    refused before it writes anything, and the colleague's edit stays."""

    proposal = await _propose(
        db_container,
        seeded,
        [
            _keep(1, assistant_spec={"instructions": "Planens uppgift 1."}),
            _keep(2, assistant_spec={"instructions": "Planens uppgift 2."}),
            {"kind": "add", "step": {"name": "Sist", "instructions": "Avsluta."}},
            _keep(3),
        ],
    )
    apply_prepared = FlowAuthoringCommandService.apply_prepared

    async def colleague_edits_first(self: Any, **kwargs: Any) -> Any:
        async with db_container() as container:
            await container.flow_service().update_flow_assistant(
                flow_id=seeded.flow_id,
                assistant_id=seeded.assistant_ids[1],
                update=_prompt_update("Kollegans uppgift 2."),
            )
        return await apply_prepared(self, **kwargs)

    assistants_before = await _flow_assistant_ids(db_container, seeded.flow_id)
    rows_before = await _step_rows(db_container, seeded)
    with patch.object(
        FlowAuthoringCommandService, "apply_prepared", colleague_edits_first
    ):
        with pytest.raises(BadRequestException) as refused:
            await _apply_proposal(db_container, seeded, proposal)

    assert refused.value.code == "stale_revision"
    assert await _prompt(db_container, seeded.assistant_ids[0]) == "Gör uppgift 1."
    assert await _prompt(db_container, seeded.assistant_ids[1]) == (
        "Kollegans uppgift 2."
    )
    assert await _flow_assistant_ids(db_container, seeded.flow_id) == (
        assistants_before
    )
    assert await _step_rows(db_container, seeded) == rows_before
    assert await _revision(db_container, seeded.flow_id) == seeded.revision + 1


# --- Two writers at once -----------------------------------------------------


async def _backend_pid(container: Any) -> int:
    pid = await container.session().scalar(sa.text("select pg_backend_pid()"))
    assert isinstance(pid, int)
    return pid


async def _until_waiting_on_a_lock(db_container, pid: asyncio.Future[int]) -> None:
    backend = await asyncio.wait_for(pid, timeout=_TIMEOUT)
    for _ in range(_TIMEOUT * 10):
        async with db_container() as container:
            waiting = await container.session().scalar(
                sa.text("select wait_event_type from pg_stat_activity where pid = :p"),
                {"p": backend},
            )
        if waiting == "Lock":
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the second writer never waited on a lock")


async def _second_writer(
    db_container, write: Callable[[Any], Awaitable[object]]
) -> tuple[asyncio.Task[object], asyncio.Future[int]]:
    """`write` in a transaction of its own, started now; the future gives the
    database backend it runs on."""

    pid: asyncio.Future[int] = asyncio.get_running_loop().create_future()

    async def run() -> object:
        async with db_container() as container:
            pid.set_result(await _backend_pid(container))
            return await write(container)

    return asyncio.create_task(run()), pid


def _is_stale(outcome: object) -> bool:
    return isinstance(outcome, BadRequestException) and outcome.code == "stale_revision"


async def test_of_two_concurrent_assistant_edits_of_one_flow_the_second_is_refused(
    db_container, seeded: Seeded
) -> None:
    async with db_container() as first:
        await first.flow_service().update_flow_assistant(
            flow_id=seeded.flow_id,
            assistant_id=seeded.assistant_ids[0],
            update=_prompt_update("Första."),
        )
        second, pid = await _second_writer(
            db_container,
            lambda container: container.flow_service().update_flow_assistant(
                flow_id=seeded.flow_id,
                assistant_id=seeded.assistant_ids[1],
                update=_prompt_update("Andra."),
            ),
        )
        await _until_waiting_on_a_lock(db_container, pid)
    [outcome] = await asyncio.wait_for(
        asyncio.gather(second, return_exceptions=True), timeout=_TIMEOUT
    )

    assert _is_stale(outcome), outcome
    assert await _prompt(db_container, seeded.assistant_ids[0]) == "Första."
    assert await _prompt(db_container, seeded.assistant_ids[1]) == "Gör uppgift 2."
    assert await _revision(db_container, seeded.flow_id) == seeded.revision + 1


async def test_an_assistant_edit_and_the_removal_of_its_step_do_not_deadlock(
    db_container, seeded: Seeded
) -> None:
    """The edit has written the assistant when the removal starts. The removal
    waits for the edit's flow lock and is then refused; with the assistant
    locked before the flow, the two would wait for each other."""

    written = asyncio.Event()
    proceed = asyncio.Event()
    update_assistant = AssistantService.update_assistant

    async def hold_after_write(self: Any, **kwargs: Any) -> Any:
        result = await update_assistant(self, **kwargs)
        if not written.is_set():
            written.set()
            await proceed.wait()
        return result

    async def edit() -> object:
        async with db_container() as container:
            return await container.flow_service().update_flow_assistant(
                flow_id=seeded.flow_id,
                assistant_id=seeded.assistant_ids[2],
                update=_prompt_update("Ändrad medan steget tas bort."),
            )

    async def remove_third_step(container: Any) -> object:
        service = container.flow_service()
        flow = await service.get_flow(seeded.flow_id)
        return await service.update_flow(flow_id=seeded.flow_id, steps=flow.steps[:2])

    with patch.object(AssistantService, "update_assistant", hold_after_write):
        editing = asyncio.create_task(edit())
        await asyncio.wait_for(written.wait(), timeout=_TIMEOUT)
        removal, pid = await _second_writer(db_container, remove_third_step)
        await _until_waiting_on_a_lock(db_container, pid)
        proceed.set()
        edited, removed = await asyncio.wait_for(
            asyncio.gather(editing, removal, return_exceptions=True),
            timeout=_TIMEOUT,
        )

    assert not isinstance(edited, BaseException), edited
    assert _is_stale(removed), removed
    assert await _prompt(db_container, seeded.assistant_ids[2]) == (
        "Ändrad medan steget tas bort."
    )
    assert len(await _step_rows(db_container, seeded)) == 3
    assert await _revision(db_container, seeded.flow_id) == seeded.revision + 1


async def test_an_assistant_edit_during_an_apply_waits_for_it_and_is_refused(
    db_container, seeded: Seeded
) -> None:
    """The apply has written the first of its two assistants when a colleague
    edits that assistant. The apply holds the flow from before its first
    write, so the edit waits, the apply completes with one increment, and the
    edit is refused; an apply locking the flow only when it saves the steps
    would wait for the edit's flow lock while the edit waits for its
    assistant."""

    proposal = await _propose(
        db_container,
        seeded,
        [
            _keep(1, assistant_spec={"instructions": "Planens uppgift 1."}),
            _keep(2, assistant_spec={"instructions": "Planens uppgift 2."}),
            _keep(3),
        ],
    )
    written = asyncio.Event()
    proceed = asyncio.Event()
    update_reserved = FlowService.update_reserved_flow_assistant

    async def hold_after_first_apply_write(self: FlowService, **kwargs: Any) -> Any:
        result = await update_reserved(self, **kwargs)
        if kwargs.get("classification_judged_by_flow_update") and not written.is_set():
            written.set()
            await proceed.wait()
        return result

    with patch.object(
        FlowService, "update_reserved_flow_assistant", hold_after_first_apply_write
    ):
        applying = asyncio.create_task(_apply_proposal(db_container, seeded, proposal))
        await asyncio.wait_for(written.wait(), timeout=_TIMEOUT)
        colleague, pid = await _second_writer(
            db_container,
            lambda container: container.flow_service().update_flow_assistant(
                flow_id=seeded.flow_id,
                assistant_id=seeded.assistant_ids[0],
                update=_prompt_update("Kollegans uppgift 1."),
            ),
        )
        await _until_waiting_on_a_lock(db_container, pid)
        proceed.set()
        applied, edited = await asyncio.wait_for(
            asyncio.gather(applying, colleague, return_exceptions=True),
            timeout=_TIMEOUT,
        )

    assert applied == {seeded.assistant_ids[0]: 1, seeded.assistant_ids[1]: 1}
    assert _is_stale(edited), edited
    assert await _prompt(db_container, seeded.assistant_ids[0]) == "Planens uppgift 1."
    assert await _prompt(db_container, seeded.assistant_ids[1]) == "Planens uppgift 2."
    assert await _revision(db_container, seeded.flow_id) == seeded.revision + 1


async def test_an_apply_reads_its_template_before_it_locks_the_flow_and_a_stale_one_keeps_no_asset(
    db_container,
) -> None:
    """A colleague's edit holds the flow row while an apply that attaches a
    template runs. The apply reads the template's bytes from object storage
    before it locks the flow, so that remote read neither waits on the lock nor
    holds it; once the colleague commits, the apply is refused and the
    template asset it created is rolled back with it."""

    async with db_container() as setup:
        _user, space, flow, file = await _create_flow_and_file(
            setup, placeholder="case_id"
        )
        space_id = space.id
    promoted = asyncio.Event()
    create_asset = FlowTemplateAssetService.create_from_existing_attached_file

    async def promote(self: FlowTemplateAssetService, **kwargs: Any) -> Any:
        asset = await create_asset(self, **kwargs)
        promoted.set()
        return asset

    def apply(container: Any) -> Awaitable[object]:
        return FlowDraftMaterializer().execute(
            changeset=_template_changeset(),
            flow_service=container.flow_service(),
            space_id=space_id,
            flow_id=flow.id,
            expected_revision=flow.draft_revision,
            binding_source=FlowResourceBindingSource.AI_BUILDER,
            template_attachment_intent=TemplateAttachmentIntent(
                file_id=file.id, terminal_plan_step_ref="step_b"
            ),
            template_asset_service=container.flow_template_asset_service(),
        )

    with patch.object(
        FlowTemplateAssetService, "create_from_existing_attached_file", promote
    ):
        async with db_container() as colleague:
            await colleague.flow_service().update_flow(
                flow_id=flow.id, description="Kollegans beskrivning."
            )
            applying, pid = await _second_writer(db_container, apply)
            await asyncio.wait(
                {asyncio.ensure_future(promoted.wait()), applying},
                timeout=_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )
            assert promoted.is_set(), (
                applying.exception() if applying.done() else "blocked before it"
            )
            await _until_waiting_on_a_lock(db_container, pid)
        [outcome] = await asyncio.wait_for(
            asyncio.gather(applying, return_exceptions=True), timeout=_TIMEOUT
        )

    assert _is_stale(outcome), outcome
    async with db_container() as container:
        assets = await container.session().scalar(
            sa.select(sa.func.count(FlowTemplateAssets.id)).where(
                FlowTemplateAssets.flow_id == flow.id
            )
        )
    assert assets == 0
    assert await _revision(db_container, flow.id) == flow.draft_revision + 1
