from __future__ import annotations

import asyncio
from time import monotonic
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.database.database import sessionmanager
from eneo.database.tables.flow_tables import FlowRuns, Flows, FlowVersions
from eneo.database.tables.spaces_table import Spaces
from eneo.flows.application.flow_run_service import CreateRunResult
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.infrastructure.flow_repo import FlowRepository
from eneo.flows.infrastructure.flow_version_repo import FlowVersionRepository
from eneo.flows.published_definition import build_published_definition_json
from eneo.main.container.container import Container
from eneo.main.exceptions import BadRequestException


async def _create_published_flow_with_two_versions(
    *,
    container: Container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> UUID:
    session = container.session()
    model = await completion_model_factory(session, "run-publication-lock-model")
    space = await space_factory(
        session,
        "Run publication lock space",
        [model.id],
    )
    assistant = await assistant_factory(
        session,
        "Run publication lock assistant",
        model.id,
        space_id=space.id,
    )
    flow_repo = FlowRepository(session)
    flow = await flow_repo.create(
        Flow(
            id=None,
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            name="Run publication lock flow",
            description="Proves that run creation pins the publication pointer.",
            created_by_user_id=admin_user.id,
            owner_user_id=admin_user.id,
            published_version=None,
            metadata_json=None,
            data_retention_days=None,
            created_at=None,
            updated_at=None,
            steps=[
                FlowStep(
                    id=None,
                    flow_id=None,
                    tenant_id=admin_user.tenant_id,
                    assistant_id=assistant.id,
                    step_order=1,
                    user_description="Return the submitted input",
                    input_source="flow_input",
                    input_type="text",
                    output_mode="pass_through",
                    output_type="text",
                )
            ],
        ),
        tenant_id=admin_user.tenant_id,
    )
    step = flow.steps[0]
    assert flow.id is not None
    assert step.id is not None
    definition = build_published_definition_json(
        flow_id=flow.id,
        name=flow.name,
        description=flow.description,
        metadata_json=flow.metadata_json,
        steps=[
            {
                "step_id": str(step.id),
                "assistant_id": str(step.assistant_id),
                "step_order": step.step_order,
                "user_description": step.user_description,
                "input_source": step.input_source.value,
                "input_type": step.input_type.value,
                "output_mode": step.output_mode.value,
                "output_type": step.output_type.value,
            }
        ],
    )
    version_repo = FlowVersionRepository(session)
    for version in (1, 2):
        await version_repo.create(
            flow_id=flow.id,
            version=version,
            definition_json=definition,
            tenant_id=admin_user.tenant_id,
        )
    await flow_repo.update(
        flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )
    return flow.id


async def _wait_for_postgres_lock(
    *,
    backend_pid: int,
    run_task: asyncio.Task[CreateRunResult],
    timeout_seconds: float = 5,
) -> None:
    deadline = monotonic() + timeout_seconds
    async with (
        sessionmanager.session() as observer_session,
        observer_session.begin(),
    ):
        while monotonic() < deadline:
            if run_task.done():
                if run_task.cancelled():
                    pytest.fail(
                        "Run creation was cancelled before waiting on the lock."
                    )
                failure = run_task.exception()
                if failure is not None:
                    pytest.fail(
                        "Run creation failed before waiting on the Flow lock: "
                        f"{failure}"
                    )
                result = run_task.result()
                pytest.fail(
                    "Run creation completed before waiting on the Flow lock: "
                    f"run_id={result.run.id}"
                )
            wait_event_type = await observer_session.scalar(
                sa.text(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"
                ),
                {"pid": backend_pid},
            )
            if wait_event_type == "Lock":
                return
            await asyncio.sleep(0.01)
    pytest.fail("Run creation did not wait on the locked Flow publication pointer.")


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("changed_published_version", "expected_error_code"),
    [
        (None, FlowApiErrorCode.FLOW_NOT_PUBLISHED),
        (2, FlowApiErrorCode.RUN_STALE_VERSION),
    ],
    ids=["unpublished", "republished"],
)
async def test_create_run_rejects_publication_change_committed_after_definition_read(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    test_tenant,
    changed_published_version: int | None,
    expected_error_code: FlowApiErrorCode,
) -> None:
    async with db_container() as setup_container:
        flow_id = await _create_published_flow_with_two_versions(
            container=setup_container,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        await setup_container.session().commit()

        async with (
            sessionmanager.session() as publication_session,
            sessionmanager.session() as run_session,
        ):
            await publication_session.begin()
            await publication_session.execute(
                sa.update(Flows)
                .where(Flows.id == flow_id)
                .where(Flows.tenant_id == admin_user.tenant_id)
                .values(published_version=changed_published_version)
            )
            await run_session.begin()
            backend_pid = await run_session.scalar(sa.text("SELECT pg_backend_pid()"))
            assert isinstance(backend_pid, int)
            run_container = Container(
                session=providers.Object(run_session),
                user=providers.Object(admin_user),
                tenant=providers.Object(test_tenant),
            )
            run_task = asyncio.create_task(
                run_container.flow_run_service().create_run(
                    flow_id=flow_id,
                    input_payload_json={"question": "race"},
                    idempotency_key=f"publication-race-{uuid4()}",
                )
            )
            try:
                await _wait_for_postgres_lock(
                    backend_pid=backend_pid,
                    run_task=run_task,
                )
                await publication_session.commit()
                with pytest.raises(FlowBadRequestException) as exc_info:
                    await asyncio.wait_for(run_task, timeout=5)
            finally:
                if not run_task.done():
                    run_task.cancel()
                    await asyncio.gather(run_task, return_exceptions=True)
                if publication_session.in_transaction():
                    await publication_session.rollback()
                if run_session.in_transaction():
                    await run_session.rollback()

        assert exc_info.value.code is expected_error_code
        if expected_error_code is FlowApiErrorCode.RUN_STALE_VERSION:
            assert exc_info.value.context == {
                "expected_flow_version": 1,
                "published_flow_version": 2,
            }
        else:
            assert exc_info.value.context == {"flow_id": str(flow_id)}

        async with (
            sessionmanager.session() as verification_session,
            verification_session.begin(),
        ):
            run_count = await verification_session.scalar(
                sa.select(sa.func.count())
                .select_from(FlowRuns)
                .where(FlowRuns.flow_id == flow_id)
                .where(FlowRuns.tenant_id == admin_user.tenant_id)
            )
        assert run_count == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_publication_pointer_lock_allows_concurrent_flow_version_insert(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> None:
    async with db_container() as setup_container:
        flow_id = await _create_published_flow_with_two_versions(
            container=setup_container,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        await setup_container.session().commit()

    async with (
        sessionmanager.session() as lock_session,
        sessionmanager.session() as version_session,
    ):
        await lock_session.begin()
        await FlowRepository(lock_session).lock_publication_pointer(
            flow_id=flow_id,
            tenant_id=admin_user.tenant_id,
        )
        await version_session.begin()
        insert_task = asyncio.create_task(
            version_session.execute(
                sa.insert(FlowVersions).values(
                    flow_id=flow_id,
                    version=3,
                    tenant_id=admin_user.tenant_id,
                    definition_checksum="concurrent-version-checksum",
                    definition_json={"schema_version": 1, "steps": []},
                )
            )
        )
        try:
            await asyncio.wait_for(asyncio.shield(insert_task), timeout=1)
        finally:
            await lock_session.rollback()
            if not insert_task.done():
                await asyncio.wait_for(insert_task, timeout=5)
            await version_session.rollback()


async def _create_unpublished_flow(
    *,
    container: Container,
    admin_user,
) -> UUID:
    """A publishable draft, built through the service so its step is flow-owned."""
    session = container.session()
    space = Spaces(
        tenant_id=admin_user.tenant_id,
        user_id=admin_user.id,
        name=f"flow-edit-publish-race-{uuid4().hex}",
    )
    session.add(space)
    await session.flush()
    flow_service = container.flow_service()
    flow = await flow_service.create_flow(
        space_id=space.id,
        name="Flow edit publish race flow",
        description="Proves a draft edit cannot revert a concurrent publish.",
        steps=[],
    )
    assert flow.id is not None
    assistant, _ = await flow_service.create_flow_assistant(
        flow_id=flow.id,
        name="Flow edit publish race assistant",
    )
    await flow_service.update_flow(
        flow_id=flow.id,
        steps=[
            FlowStep(
                id=None,
                flow_id=flow.id,
                tenant_id=admin_user.tenant_id,
                assistant_id=assistant.id,
                step_order=1,
                user_description="Return the submitted input",
                input_source="flow_input",
                input_type="text",
                output_mode="pass_through",
                output_type="text",
            )
        ],
    )
    return flow.id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flow_edit_rejects_publication_committed_after_its_read(
    db_container,
    admin_user,
    test_tenant,
    object_content_runtime_ready,
) -> None:
    """A draft edit must not silently unpublish a concurrently published Flow.

    `update_flow` refuses to mutate a published Flow, but that check reads the
    row while the write used to carry no precondition — so a publish landing in
    between was reverted by the stale `published_version` the edit wrote back,
    with no error to either caller.
    """
    async with db_container() as setup_container:
        flow_id = await _create_unpublished_flow(
            container=setup_container,
            admin_user=admin_user,
        )
        await setup_container.session().commit()

    async with (
        sessionmanager.session() as publish_session,
        sessionmanager.session() as edit_session,
    ):
        publish_container = Container(
            session=providers.Object(publish_session),
            user=providers.Object(admin_user),
            tenant=providers.Object(test_tenant),
        )
        edit_container = Container(
            session=providers.Object(edit_session),
            user=providers.Object(admin_user),
            tenant=providers.Object(test_tenant),
        )
        edit_service = edit_container.flow_service()
        original_validate = (
            edit_service._validate_step_security_classification_for_steps
        )
        publishes = 0

        async def _publish_between_read_and_write(**kwargs: object) -> None:
            nonlocal publishes
            await original_validate(**kwargs)  # pyright: ignore[reportArgumentType]
            if publishes:
                return
            publishes += 1
            await publish_session.begin()
            await publish_container.flow_service().publish_flow(flow_id=flow_id)
            await publish_session.commit()

        edit_service._validate_step_security_classification_for_steps = (
            _publish_between_read_and_write
        )

        await edit_session.begin()
        try:
            with pytest.raises(BadRequestException) as exc_info:
                await edit_service.update_flow(
                    flow_id=flow_id,
                    name="Edited while a publish was committing",
                )
        finally:
            if edit_session.in_transaction():
                await edit_session.rollback()

    assert publishes == 1
    assert exc_info.value.code == "stale_revision"

    async with (
        sessionmanager.session() as verification_session,
        verification_session.begin(),
    ):
        published_version, name = (
            await verification_session.execute(
                sa.select(Flows.published_version, Flows.name).where(
                    Flows.id == flow_id
                )
            )
        ).one()

    assert published_version == 1
    assert name == "Flow edit publish race flow"
