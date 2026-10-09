"""A flow-managed assistant is reclaimed only when no draft step and no version
that can still execute references it, and a run resolves its transcription
model's space from its flow, never through a step assistant it may have lost.

A version can execute while it is the published version of a live flow or while
a run of it has not finished (a retry or a transcript regeneration starts on the
published version only). Editing a draft needs the flow unpublished, so a run
that was in flight when the author unpublished is what the snapshot protects.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from eneo.assistants.assistant_service import AssistantService
from eneo.assistants.assistant_update import AssistantUpdateCommand
from eneo.database.tables.assistant_table import Assistants
from eneo.database.tables.flow_tables import FlowRuns, Flows, FlowSteps
from eneo.flows.domain.flow import Flow, FlowRunStatus, FlowStep
from eneo.flows.enums import (
    NON_TERMINAL_FLOW_RUN_STATUS_VALUES,
    TERMINAL_FLOW_RUN_STATUS_VALUES,
)
from eneo.flows.infrastructure.flow_repo import (
    AssistantReclaimBlocker,
    FlowRepository,
)
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.runtime.transcription import (
    load_flow_space,
    select_transcription_model,
)
from eneo.flows.transcription_config import FlowTranscriptionConfig
from eneo.main.exceptions import BadRequestException, NotFoundException
from eneo.prompts.api.prompt_models import PromptCreate
from tests.integration.flows.test_ai_builder_session_api_regressions import (
    _create_default_transcription_model,  # pyright: ignore[reportPrivateUsage]
)
from tests.integration.flows.test_flow_assistant_fencing import (
    _TIMEOUT,  # pyright: ignore[reportPrivateUsage]
    _second_writer,  # pyright: ignore[reportPrivateUsage]
    _until_waiting_on_a_lock,  # pyright: ignore[reportPrivateUsage]
)
from tests.integration.flows.test_flow_assistant_update_siblings import (
    _admin_token_and_space,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _step(assistant_id: UUID, order: int) -> FlowStep:
    return FlowStep(
        assistant_id=assistant_id,
        step_order=order,
        user_description=f"Steg {order}",
        input_source="flow_input" if order == 1 else "previous_step",
        input_type="text",
        output_mode="pass_through",
        output_type="text",
    )


async def _flow_with_steps(
    db_container, space_id: UUID, *, steps: int, name: str = "Referenser"
):
    """A draft flow of ``steps`` steps, plus one managed assistant no step uses."""
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.create_flow(
            space_id=space_id, name=name, description=None, steps=[]
        )
        assistants = []
        for index in range(steps + 1):
            assistant, _ = await service.create_flow_assistant(
                flow_id=flow.id, name=f"steg-{index}"
            )
            await service.update_flow_assistant(
                flow_id=flow.id,
                assistant_id=assistant.id,
                update=AssistantUpdateCommand(prompt=PromptCreate(text="Gör det.")),
            )
            assistants.append(assistant.id)
        flow = await service.update_flow(
            flow_id=flow.id,
            steps=[_step(a, order) for order, a in enumerate(assistants[:steps], 1)],
        )
    return flow, assistants


async def _publish(db_container, flow_id: UUID) -> Flow:
    async with db_container() as container:
        return await container.flow_service().publish_flow(flow_id=flow_id)


async def _unpublish(db_container, flow_id: UUID) -> Flow:
    async with db_container() as container:
        return await container.flow_service().unpublish_flow(flow_id=flow_id)


async def _add_run(
    db_container, *, flow_id: UUID, version: int, status: str, tenant_id: UUID, user_id
) -> UUID:
    async with db_container() as container:
        session = container.session()
        run = FlowRuns(
            flow_id=flow_id,
            flow_version=version,
            principal_type="user",
            principal_user_id=user_id,
            tenant_id=tenant_id,
            status=status,
            input_payload_json={},
            execution_heartbeat_at=sa.func.now() if status == "running" else None,
        )
        session.add(run)
        await session.flush()
        return run.id


async def _set_run_status(db_container, run_id: UUID, status: str) -> None:
    async with db_container() as container:
        await container.session().execute(
            sa.update(FlowRuns).where(FlowRuns.id == run_id).values(status=status)
        )


async def _existing(db_container, assistant_ids: list[UUID]) -> set[UUID]:
    async with db_container() as container:
        return set(
            await container.session().scalars(
                sa.select(Assistants.id).where(Assistants.id.in_(assistant_ids))
            )
        )


async def _reclaimable(db_container, flow_id: UUID, tenant_id: UUID, ids) -> set[UUID]:
    async with db_container() as container:
        return set(
            await FlowRepository(
                session=container.session()
            ).orphaned_flow_managed_assistant_ids(
                flow_id=flow_id, tenant_id=tenant_id, assistant_ids=ids
            )
        )


async def _edit_steps(db_container, flow_id: UUID, kept: list[UUID]) -> None:
    async with db_container() as container:
        service = container.flow_service()
        flow = await service.get_flow(flow_id)
        by_assistant = {step.assistant_id: step for step in flow.steps}
        await service.update_flow(
            flow_id=flow_id,
            steps=[
                by_assistant[assistant_id].model_copy(update={"step_order": order})
                for order, assistant_id in enumerate(kept, 1)
            ],
        )


async def test_a_step_removed_while_a_run_of_its_version_is_unfinished_keeps_its_assistant(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (kept, removed, _) = await _flow_with_steps(db_container, space_id, steps=2)
    published = await _publish(db_container, flow.id)
    assert published.published_version == 1
    run_id = await _add_run(
        db_container,
        flow_id=flow.id,
        version=1,
        status="queued",
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
    )
    await _unpublish(db_container, flow.id)

    await _edit_steps(db_container, flow.id, [kept])

    # The run executes version 1, whose second step is the removed assistant's.
    assert await _existing(db_container, [kept, removed]) == {kept, removed}
    assert (
        await _reclaimable(db_container, flow.id, admin_user.tenant_id, {removed})
        == set()
    )

    # Version 2 does not have the step; the run still does until it finishes.
    await _publish(db_container, flow.id)
    assert await _existing(db_container, [removed]) == {removed}
    await _set_run_status(db_container, run_id, "completed")
    assert await _reclaimable(
        db_container, flow.id, admin_user.tenant_id, {removed}
    ) == {removed}


async def test_the_assistant_endpoint_refuses_one_a_run_in_flight_still_uses(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    token, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (kept, removed, _) = await _flow_with_steps(db_container, space_id, steps=2)
    await _publish(db_container, flow.id)
    run_id = await _add_run(
        db_container,
        flow_id=flow.id,
        version=1,
        status="queued",
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
    )
    await _unpublish(db_container, flow.id)
    await _edit_steps(db_container, flow.id, [kept])
    url = f"/api/v1/flows/{flow.id}/assistants/{removed}/"
    headers = {"Authorization": f"Bearer {token}"}

    refused = await client.delete(url, headers=headers)

    assert refused.status_code == 400, refused.text
    body = refused.json()
    assert body["code"] == "flow_managed_assistant"
    assert body["message"] == (
        "An unfinished run of version 1 still uses this assistant. Retry after "
        "it finishes."
    )
    assert body["context"] == {
        "flow_id": str(flow.id),
        "assistant_ids": [str(removed)],
        "reason": "unfinished_run_reference",
        "flow_version": 1,
    }
    assert await _existing(db_container, [removed]) == {removed}

    await _set_run_status(db_container, run_id, "completed")
    deleted = await client.delete(url, headers=headers)

    assert deleted.status_code == 204, deleted.text
    assert await _existing(db_container, [removed]) == set()


async def test_a_step_removed_with_no_run_in_flight_still_deletes_its_assistant(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (kept, removed, _) = await _flow_with_steps(db_container, space_id, steps=2)
    await _publish(db_container, flow.id)
    await _add_run(
        db_container,
        flow_id=flow.id,
        version=1,
        status="completed",
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
    )
    await _unpublish(db_container, flow.id)

    await _edit_steps(db_container, flow.id, [kept])

    assert await _existing(db_container, [kept, removed]) == {kept}


async def test_deleting_a_published_flow_without_runs_deletes_its_step_assistants(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (first, second, _) = await _flow_with_steps(db_container, space_id, steps=2)
    await _publish(db_container, flow.id)

    async with db_container() as container:
        await container.flow_service().delete_flow(flow.id)

    assert await _existing(db_container, [first, second]) == set()


_X = "assistant"  # stands for the assistant under test in the cases below


@pytest.mark.parametrize(
    ("steps", "published", "run", "deleted", "reclaimable"),
    [
        ([{"assistant_id": _X}], True, None, False, False),
        ([{"step_id": "s0"}, {"assistant_id": _X}], True, None, False, False),
        ([{"assistant_id": _X}], False, None, False, True),
        ([{"assistant_id": _X}], False, "queued", False, False),
        ([{"assistant_id": _X}], False, "running", False, False),
        ([{"assistant_id": _X}], False, "awaiting_review", False, False),
        ([{"assistant_id": _X}], False, "completed", False, True),
        ([{"assistant_id": _X}], False, "failed", False, True),
        ([{"assistant_id": _X}], False, "cancelled", False, True),
        ([{"assistant_id": _X}], True, None, True, True),
        ([{"assistant_id": _X}], True, "queued", True, False),
        ("absent", True, None, False, True),
        ([{"assistant_id": None}], True, None, False, True),
        ([{}], True, None, False, True),
        ([], True, None, False, True),
        ("a string", True, None, False, True),
        ({"assistant_id": _X}, True, None, False, True),
        ([None, 3, "x"], True, None, False, True),
    ],
    ids=[
        "published",
        "published_among_steps",
        "unpublished_unreferenced_by_runs",
        "queued_run",
        "running_run",
        "awaiting_review_run",
        "completed_run",
        "failed_run",
        "cancelled_run",
        "published_of_a_deleted_flow",
        "queued_run_of_a_deleted_flow",
        "no_steps_key",
        "null_assistant_id",
        "step_without_assistant_id",
        "empty_steps",
        "steps_is_a_string",
        "steps_is_an_object",
        "steps_hold_scalars",
    ],
)
async def test_the_snapshot_reads_any_shape_and_blocks_only_an_executable_version(
    steps: Any,
    published: bool,
    run: str | None,
    deleted: bool,
    reclaimable: bool,
    client,
    db_container,
    admin_user,
    patch_auth_service_jwt,
):
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (_, unused) = await _flow_with_steps(db_container, space_id, steps=1)
    definition: dict[str, Any] = {} if steps == "absent" else {"steps": steps}
    definition = _with_assistant(definition, unused)
    async with db_container() as container:
        await FlowVersionRepository(session=container.session()).create(
            flow_id=flow.id,
            version=1,
            definition_json=definition,
            tenant_id=admin_user.tenant_id,
        )
        if published:
            await container.session().execute(
                sa.update(Flows).where(Flows.id == flow.id).values(published_version=1)
            )
        if deleted:
            await container.session().execute(
                sa.update(Flows)
                .where(Flows.id == flow.id)
                .values(deleted_at=sa.func.now())
            )
    if run is not None:
        await _add_run(
            db_container,
            flow_id=flow.id,
            version=1,
            status=run,
            tenant_id=admin_user.tenant_id,
            user_id=admin_user.id,
        )

    found = await _reclaimable(db_container, flow.id, admin_user.tenant_id, {unused})

    assert found == ({unused} if reclaimable else set())


def _with_assistant(definition: dict[str, Any], assistant_id: UUID) -> dict[str, Any]:
    def swap(value: Any) -> Any:
        if value == _X:
            return str(assistant_id)
        if isinstance(value, list):
            return [swap(item) for item in value]
        if isinstance(value, dict):
            return {key: swap(item) for key, item in value.items()}
        return value

    return swap(definition)


async def test_an_assistant_two_versions_hold_stays_while_either_can_execute(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (_, shared) = await _flow_with_steps(db_container, space_id, steps=1)
    snapshot = {"steps": [{"assistant_id": str(shared)}]}
    async with db_container() as container:
        versions = FlowVersionRepository(session=container.session())
        for version in (1, 2):
            await versions.create(
                flow_id=flow.id,
                version=version,
                definition_json=snapshot,
                tenant_id=admin_user.tenant_id,
            )
    first = await _add_run(
        db_container,
        flow_id=flow.id,
        version=1,
        status="running",
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
    )

    async def reclaimable() -> set[UUID]:
        return await _reclaimable(db_container, flow.id, admin_user.tenant_id, {shared})

    assert await reclaimable() == set()
    await _set_run_status(db_container, first, "completed")
    assert await reclaimable() == {shared}
    async with db_container() as container:
        await container.session().execute(
            sa.update(Flows).where(Flows.id == flow.id).values(published_version=2)
        )
    assert await reclaimable() == set()


async def test_a_draft_step_still_holds_its_assistant_without_any_version(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (used, unused) = await _flow_with_steps(db_container, space_id, steps=1)

    assert await _reclaimable(
        db_container, flow.id, admin_user.tenant_id, {used, unused}
    ) == {unused}
    async with db_container() as container:
        step_count = await container.session().scalar(
            sa.select(sa.func.count())
            .select_from(FlowSteps)
            .where(FlowSteps.flow_id == flow.id)
        )
    assert step_count == 1


async def _flow_and_model(client, db_container, admin_user):
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (assistant, _) = await _flow_with_steps(db_container, space_id, steps=1)
    model_id = await _create_default_transcription_model(
        db_container=db_container,
        space_id=str(space_id),
        tenant_id=admin_user.tenant_id,
    )
    return flow, assistant, model_id


async def _resolve(db_container, *, flow_id: UUID, tenant_id: UUID, model_id: UUID):
    async with db_container() as container:
        space = await load_flow_space(
            flow_repo=container.flow_repo(),
            space_repo=container.space_repo(),
            flow_id=flow_id,
            tenant_id=tenant_id,
        )
        return select_transcription_model(
            space,
            config=FlowTranscriptionConfig(
                enabled=True, model_id=model_id, language="sv", diarization=False
            ),
            step_order=1,
        )


@pytest.mark.parametrize("flow_state", ["live", "soft_deleted"])
async def test_transcription_model_resolves_from_the_flow_space_without_the_step_assistant(
    flow_state: str, client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    flow, assistant, model_id = await _flow_and_model(client, db_container, admin_user)
    async with db_container() as container:
        session = container.session()
        await session.execute(sa.delete(FlowSteps).where(FlowSteps.flow_id == flow.id))
        await session.execute(sa.delete(Assistants).where(Assistants.id == assistant))
        if flow_state == "soft_deleted":
            await session.execute(
                sa.update(Flows)
                .where(Flows.id == flow.id)
                .values(deleted_at=sa.func.now())
            )
    assert await _existing(db_container, [assistant]) == set()

    model = await _resolve(
        db_container,
        flow_id=flow.id,
        tenant_id=admin_user.tenant_id,
        model_id=model_id,
    )

    assert model.id == model_id


async def test_transcription_of_a_run_whose_flow_is_unknown_is_not_found(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    _, _, model_id = await _flow_and_model(client, db_container, admin_user)

    with pytest.raises(NotFoundException):
        await _resolve(
            db_container,
            flow_id=uuid4(),
            tenant_id=admin_user.tenant_id,
            model_id=model_id,
        )


async def _add_version(db_container, *, flow_id: UUID, version: int, tenant_id, steps):
    async with db_container() as container:
        await FlowVersionRepository(session=container.session()).create(
            flow_id=flow_id,
            version=version,
            definition_json={"steps": [{"assistant_id": str(a)} for a in steps]},
            tenant_id=tenant_id,
        )


async def test_only_a_run_of_a_version_that_holds_the_assistant_blocks_it(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    tenant = admin_user.tenant_id
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (_, held) = await _flow_with_steps(db_container, space_id, steps=1)
    await _add_version(
        db_container, flow_id=flow.id, version=1, tenant_id=tenant, steps=[held]
    )
    await _add_version(
        db_container, flow_id=flow.id, version=2, tenant_id=tenant, steps=[]
    )
    await _add_run(
        db_container,
        flow_id=flow.id,
        version=1,
        status="completed",
        tenant_id=tenant,
        user_id=admin_user.id,
    )
    # An unfinished run of version 2, which does not hold the assistant.
    await _add_run(
        db_container,
        flow_id=flow.id,
        version=2,
        status="queued",
        tenant_id=tenant,
        user_id=admin_user.id,
    )

    assert await _reclaimable(db_container, flow.id, tenant, {held}) == {held}


async def test_a_run_of_another_flow_with_the_same_version_number_does_not_block(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    tenant = admin_user.tenant_id
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (_, held) = await _flow_with_steps(db_container, space_id, steps=1)
    other, _ = await _flow_with_steps(
        db_container, space_id, steps=1, name="Annat flöde"
    )
    await _add_version(
        db_container, flow_id=flow.id, version=1, tenant_id=tenant, steps=[held]
    )
    await _add_version(
        db_container, flow_id=other.id, version=1, tenant_id=tenant, steps=[]
    )
    run_id = await _add_run(
        db_container,
        flow_id=other.id,
        version=1,
        status="queued",
        tenant_id=tenant,
        user_id=admin_user.id,
    )

    assert await _reclaimable(db_container, flow.id, tenant, {held}) == {held}

    # The same shape on the flow itself does block, so the case above is real.
    await _add_run(
        db_container,
        flow_id=flow.id,
        version=1,
        status="queued",
        tenant_id=tenant,
        user_id=admin_user.id,
    )
    assert await _reclaimable(db_container, flow.id, tenant, {held}) == set()
    await _set_run_status(db_container, run_id, "completed")


async def test_another_tenant_sees_neither_a_reclaimable_assistant_nor_a_blocker(
    client, db_container, admin_user, patch_auth_service_jwt
):
    # Runs and versions carry the flow's tenant through composite foreign keys,
    # so a row of another tenant cannot exist; the tenant filters of the
    # predicate are scoping only, and this pins that a foreign tenant id
    # reaches nothing of the flow.
    _ = patch_auth_service_jwt
    tenant = admin_user.tenant_id
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (_, held) = await _flow_with_steps(db_container, space_id, steps=1)
    await _add_version(
        db_container, flow_id=flow.id, version=1, tenant_id=tenant, steps=[held]
    )
    await _add_run(
        db_container,
        flow_id=flow.id,
        version=1,
        status="queued",
        tenant_id=tenant,
        user_id=admin_user.id,
    )
    foreign = uuid4()

    assert await _reclaimable(db_container, flow.id, foreign, {held}) == set()
    async with db_container() as container:
        repo = FlowRepository(session=container.session())
        assert (
            await repo.assistant_reclaim_blocker(
                flow_id=flow.id, tenant_id=foreign, assistant_id=held
            )
            is None
        )
        own = await repo.assistant_reclaim_blocker(
            flow_id=flow.id, tenant_id=tenant, assistant_id=held
        )
    assert own == AssistantReclaimBlocker(reason="unfinished_run_reference", version=1)


async def test_the_blocker_names_a_step_before_a_run_and_the_oldest_unfinished_version(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    tenant = admin_user.tenant_id
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (used, spare) = await _flow_with_steps(db_container, space_id, steps=1)
    for version in (1, 2, 3):
        await _add_version(
            db_container,
            flow_id=flow.id,
            version=version,
            tenant_id=tenant,
            steps=[used, spare],
        )
    for version, status in ((2, "queued"), (3, "running"), (1, "failed")):
        await _add_run(
            db_container,
            flow_id=flow.id,
            version=version,
            status=status,
            tenant_id=tenant,
            user_id=admin_user.id,
        )

    async with db_container() as container:
        repo = FlowRepository(session=container.session())
        by_step = await repo.assistant_reclaim_blocker(
            flow_id=flow.id, tenant_id=tenant, assistant_id=used
        )
        by_run = await repo.assistant_reclaim_blocker(
            flow_id=flow.id, tenant_id=tenant, assistant_id=spare
        )
        by_nothing = await repo.assistant_reclaim_blocker(
            flow_id=flow.id, tenant_id=tenant, assistant_id=uuid4()
        )

    assert by_step == AssistantReclaimBlocker(reason="step_reference")
    assert by_run == AssistantReclaimBlocker(
        reason="unfinished_run_reference", version=2
    )
    assert by_nothing is None


# --- The assistant endpoint holds the flow lock -------------------------------


async def _unpublished_flow_with_a_spare_assistant(db_container, admin_user, client):
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (used, spare) = await _flow_with_steps(db_container, space_id, steps=1)
    return flow, used, spare


async def test_the_assistant_endpoint_holds_the_flow_lock_through_the_delete(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """DELETE passes eligibility and is held before the delete runs. A publish
    of the same flow waits for it, so no version, step or run can start using
    the assistant between the check and the delete; the publish then reads the
    draft without it."""
    _ = patch_auth_service_jwt
    flow, used, spare = await _unpublished_flow_with_a_spare_assistant(
        db_container, admin_user, client
    )
    reached = asyncio.Event()
    proceed = asyncio.Event()
    delete = AssistantService.delete_flow_managed_assistants

    async def hold_before_the_delete(self: Any, **kwargs: Any) -> Any:
        reached.set()
        await proceed.wait()
        return await delete(self, **kwargs)

    async def delete_spare() -> object:
        async with db_container() as container:
            return await container.flow_service().delete_flow_assistant(
                flow_id=flow.id, assistant_id=spare
            )

    with patch.object(
        AssistantService, "delete_flow_managed_assistants", hold_before_the_delete
    ):
        deleting = asyncio.create_task(delete_spare())
        await asyncio.wait_for(reached.wait(), timeout=_TIMEOUT)
        publishing, pid = await _second_writer(
            db_container,
            lambda container: container.flow_service().publish_flow(flow_id=flow.id),
        )
        await _until_waiting_on_a_lock(db_container, pid)
        proceed.set()
        deleted, published = await asyncio.wait_for(
            asyncio.gather(deleting, publishing, return_exceptions=True),
            timeout=_TIMEOUT,
        )

    assert not isinstance(deleted, BaseException), deleted
    assert not isinstance(published, BaseException), published
    assert await _existing(db_container, [used, spare]) == {used}


async def test_a_flow_published_before_the_endpoint_holds_the_lock_is_refused(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """Another session publishes between the caller's first read and the lock;
    the delete reads the pointer under the lock and refuses."""
    _ = patch_auth_service_jwt
    flow, used, spare = await _unpublished_flow_with_a_spare_assistant(
        db_container, admin_user, client
    )
    lock = FlowRepository.lock_publication_pointer

    async def publish_first_then_lock(self: Any, **kwargs: Any) -> Any:
        if not published:
            published.append(None)  # the publish below locks through this too
            published[0] = await _publish(db_container, flow.id)
        return await lock(self, **kwargs)

    published: list[Flow | None] = []
    with patch.object(
        FlowRepository, "lock_publication_pointer", publish_first_then_lock
    ):
        with pytest.raises(BadRequestException):
            async with db_container() as container:
                await container.flow_service().delete_flow_assistant(
                    flow_id=flow.id, assistant_id=spare
                )

    assert len(published) == 1
    assert await _existing(db_container, [used, spare]) == {used, spare}


# --- The cost of the version lookup ------------------------------------------


async def test_the_non_terminal_statuses_are_the_taxonomys_complement_of_the_terminal_ones():
    assert set(NON_TERMINAL_FLOW_RUN_STATUS_VALUES) == {
        status.value for status in FlowRunStatus
    } - set(TERMINAL_FLOW_RUN_STATUS_VALUES)
    assert "awaiting_review" in NON_TERMINAL_FLOW_RUN_STATUS_VALUES


async def test_the_unfinished_run_lookup_is_positive_membership_on_the_non_terminal_statuses():
    """`NOT IN` the terminal statuses cannot use ix_flow_runs_flow_id_status:
    it reads every run of the flow, so the cost would grow with its history."""
    sql = str(
        FlowRepository._unfinished_run_versions_statement(  # pyright: ignore[reportPrivateUsage]
            flow_id=uuid4(), tenant_id=uuid4()
        ).compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )

    assert "NOT IN" not in sql and "!=" not in sql and "<>" not in sql
    assert "status IN (" in sql
    for status in NON_TERMINAL_FLOW_RUN_STATUS_VALUES:
        assert f"'{status}'" in sql
    for status in TERMINAL_FLOW_RUN_STATUS_VALUES:
        assert f"'{status}'" not in sql


async def test_the_executable_versions_are_read_once_for_all_candidates(
    client, db_container, admin_user, patch_auth_service_jwt
):
    _ = patch_auth_service_jwt
    tenant = admin_user.tenant_id
    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, assistants = await _flow_with_steps(db_container, space_id, steps=3)
    await _add_version(
        db_container, flow_id=flow.id, version=1, tenant_id=tenant, steps=assistants[:1]
    )
    await _add_run(
        db_container,
        flow_id=flow.id,
        version=1,
        status="queued",
        tenant_id=tenant,
        user_id=admin_user.id,
    )
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    async with db_container() as container:
        session = container.session()
        bind = session.sync_session.get_bind()
        engine = getattr(bind, "engine", bind)
        sa.event.listen(engine, "before_cursor_execute", record)
        try:
            found = await FlowRepository(
                session=session
            ).orphaned_flow_managed_assistant_ids(
                flow_id=flow.id, tenant_id=tenant, assistant_ids=set(assistants)
            )
        finally:
            sa.event.remove(engine, "before_cursor_execute", record)

    # One lookup of the flow's unfinished runs serves every candidate.
    assert sum("FROM flow_runs" in statement for statement in seen) == 1
    assert found == {assistants[3]}


async def test_a_large_executable_set_is_one_array_bind_not_one_argument_per_version(
    client, db_container, admin_user, patch_auth_service_jwt
):
    """asyncpg refuses more than 32,767 bind arguments in one statement."""
    _ = patch_auth_service_jwt
    tenant = admin_user.tenant_id
    versions = set(range(1, 40_001))
    flow_id, held, other = uuid4(), uuid4(), uuid4()
    holds = FlowRepository._executable_version_holds(  # pyright: ignore[reportPrivateUsage]
        flow_id=flow_id,
        tenant_id=tenant,
        versions=versions,
        assistant_id=sa.literal(str(held)),
    )
    oldest = FlowRepository._oldest_holding_version_statement(  # pyright: ignore[reportPrivateUsage]
        flow_id=flow_id, tenant_id=tenant, versions=versions, assistant_id=held
    )
    for statement in (sa.select(holds), oldest):
        compiled = statement.compile(dialect=postgresql.dialect())
        assert len(compiled.params) < 20
        assert len(compiled.params["executable_versions"]) == len(versions)

    _, space_id = await _admin_token_and_space(client, db_container, admin_user)
    flow, (_, spare) = await _flow_with_steps(db_container, space_id, steps=1)
    await _add_version(
        db_container, flow_id=flow.id, version=7, tenant_id=tenant, steps=[spare]
    )
    async with db_container() as container:
        session = container.session()
        executed_holds = await session.scalar(
            sa.select(
                FlowRepository._executable_version_holds(  # pyright: ignore[reportPrivateUsage]
                    flow_id=flow.id,
                    tenant_id=tenant,
                    versions=versions,
                    assistant_id=sa.literal(str(spare)),
                )
            )
        )
        oldest_holder = await session.scalar(
            FlowRepository._oldest_holding_version_statement(  # pyright: ignore[reportPrivateUsage]
                flow_id=flow.id, tenant_id=tenant, versions=versions, assistant_id=spare
            )
        )
        oldest_of_other = await session.scalar(
            FlowRepository._oldest_holding_version_statement(  # pyright: ignore[reportPrivateUsage]
                flow_id=flow.id, tenant_id=tenant, versions=versions, assistant_id=other
            )
        )

    assert executed_holds is True
    assert oldest_holder == 7
    assert oldest_of_other is None
