import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from dependency_injector import providers

from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
from eneo.data_retention.application.retention_runner import RetentionBatch
from eneo.data_retention.domain.retention import RetentionBudget, RetentionJobOutcome
from eneo.data_retention.infrastructure.retention_worker import retention_runner
from eneo.database.database import sessionmanager
from eneo.database.tables.assistant_table import AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowLiveTranscripts,
    FlowRunReleasedInputs,
    FlowRuns,
    FlowRunStepInputFiles,
    FlowRuntimeUploadedFiles,
    Flows,
    FlowStepResults,
    FlowVersions,
)
from eneo.database.tables.retention_tables import RetentionReceipts
from eneo.files.file_models import FileType
from eneo.flows.application.flow_housekeeping_task import FlowHousekeepingTask
from eneo.flows.application.flow_transcript_regeneration_service import (
    render_original_segments,
)
from eneo.flows.domain.flow_run_retention_policy import (
    resolve_transcription_audio_after_use,
)
from eneo.flows.flow_runtime_upload_repo import FlowRuntimeUploadRepository
from eneo.flows.infrastructure.flow_audio_after_use_repo import (
    FlowAudioAfterUseRepository,
)
from eneo.flows.infrastructure.flow_retention_hold_repo import (
    FlowRetentionHoldRepository,
)
from eneo.flows.infrastructure.flow_run_released_input_repo import (
    FlowRunReleasedInputRepository,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_run_retention_policy_query import (
    effective_transcription_audio_after_use_sql,
)
from eneo.flows.principal import FlowPrincipal
from eneo.main.config import get_settings
from eneo.main.container.container import Container
from tests.integration.flows.test_flow_consumer_api_contract import (
    _create_published_flow,
    _create_space,
    admin_token,  # noqa: F401
)
from tests.integration.flows.test_flow_delete_fencing import (
    _backend_pid,
    _until_blocked_by_or_done,
)
from tests.integration.flows.test_flow_live_transcription_session import (
    LiveFlow,
    _published_flow,
)
from tests.integration.flows.test_flow_run_transcription_options import (
    dispatched,  # noqa: F401
)
from tests.integration.flows.test_transcript_corrections import (
    SEGMENTS,
    _store_segments,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def audio_source_run(
    client,
    flow_process_auth_headers,
    db_container,
    admin_user,
    dispatched,  # noqa: F811
) -> tuple[LiveFlow, UUID, UUID]:
    headers = dict(flow_process_auth_headers)
    flow = await _published_flow(client, headers, db_container, summarize=True)
    async with db_container(user=admin_user) as container:
        file = await container.file_service().save_generated_file(
            payload=b"The seeded transcription does not decode source audio.",
            name="source.wav",
            mimetype="audio/wav",
            file_type=FileType.AUDIO,
        )
        file_id = file.id
        await FlowRuntimeUploadRepository(container.session()).create(
            file_id=file_id,
            flow_id=UUID(flow.flow_id),
            tenant_id=admin_user.tenant_id,
            uploaded_for_step_id=UUID(flow.step_id),
            principal=FlowPrincipal.from_user(admin_user),
        )
    created = await client.post(
        f"/api/v1/flows/{flow.flow_id}/runs/",
        headers=headers,
        json={"step_inputs": {flow.step_id: {"file_ids": [str(file_id)]}}},
    )
    assert created.status_code == 201, created.text
    run_id = UUID(created.json()["id"])
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(Flows)
            .where(Flows.id == UUID(flow.flow_id))
            .values(delete_transcription_audio_after_use=True)
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .values(status="failed", finished_at=datetime.now(timezone.utc))
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .values(status="failed")
        )
    return flow, run_id, file_id


@pytest.mark.parametrize(
    ("status", "policy", "locked"),
    [("running", True, False), ("failed", False, False), ("failed", True, True)],
)
async def test_audio_discovery_locks_only_an_eligible_source(
    db_container,
    audio_source_run: tuple[LiveFlow, UUID, UUID],
    status: str,
    policy: bool,
    locked: bool,
) -> None:
    """Kills G5-A12: lock active or policy-disabled sources before eligibility."""
    flow, run_id, _ = audio_source_run
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .values(
                status=status,
                execution_heartbeat_at=datetime.now(timezone.utc),
                finished_at=None if status == "running" else datetime.now(timezone.utc),
            )
        )
        await session.execute(
            sa.update(Flows)
            .where(Flows.id == UUID(flow.flow_id))
            .values(delete_transcription_audio_after_use=policy)
        )
    async with sessionmanager.session() as source, source.begin():
        await FlowAudioAfterUseRepository(source).lock_source(run_id)
        blocked = False
        try:
            async with sessionmanager.session() as contender, contender.begin():
                await contender.execute(
                    sa.select(FlowRuns.id)
                    .where(FlowRuns.id == run_id)
                    .with_for_update(nowait=True)
                )
        except sa.exc.DBAPIError as exc:
            assert exc.orig.sqlstate == "55P03"
            blocked = True
        assert blocked is locked


@pytest.mark.parametrize("corruption", [None, "checksum", "schema"])
async def test_invalid_audio_definition_keeps_the_file_and_advances_housekeeping(
    db_container,
    audio_source_run: tuple[LiveFlow, UUID, UUID],
    corruption: Literal["checksum", "schema"] | None,
) -> None:
    """Kills G5-A13: one invalid pinned definition poisons the nightly cursor."""
    from eneo.flows.published_definition import published_definition_checksum

    flow, run_id, file_id = audio_source_run
    async with db_container() as container:
        session = container.session()
        version = await session.scalar(
            sa.select(FlowVersions).where(FlowVersions.flow_id == UUID(flow.flow_id))
        )
        assert version is not None
        if corruption == "checksum":
            version.definition_checksum = "0" * 64
        elif corruption == "schema":
            version.definition_json = {**version.definition_json, "schema_version": 999}
            version.definition_checksum = published_definition_checksum(
                version.definition_json
            )
    async with sessionmanager.session() as session:
        container = Container()
        container.session.override(providers.Object(session))
        report = await retention_runner(
            session=session,
            container=container,
            settings=get_settings(),
            budget=RetentionBudget(rows=5000, files=5000, seconds=60),
        ).run(FlowHousekeepingTask(session))
        assert report.outcome is RetentionJobOutcome.SUCCEEDED
        assert report.blocked.get("audio_after_use.audio_definition_invalid", 0) == (
            0 if corruption is None else 1
        )
    async with db_container() as container:
        session = container.session()
        assert (await session.get(Files, file_id) is None) == (corruption is None)
        detail = await FlowRunReleasedInputRepository(session).list_for_run(
            run_id=run_id, tenant_id=(await session.get(FlowRuns, run_id)).tenant_id
        )
        assert bool(detail) == (corruption is None)


@pytest.mark.parametrize("first", ["release", "retry"])
async def test_audio_release_serializes_with_the_actual_retry_copy(
    client,
    flow_process_auth_headers,
    db_container,
    admin_user,
    audio_source_run: tuple[LiveFlow, UUID, UUID],
    monkeypatch,
    first: Literal["release", "retry"],
) -> None:
    """Kills G5-A10/A11: missing source lock or input copy before the source lock."""
    flow, run_id, file_id = audio_source_run
    async with db_container() as container:
        session = container.session()
        await _store_segments(
            session=session,
            run_id=run_id,
            step_id=UUID(flow.step_id),
            segments=SEGMENTS,
        )
        current_attempt = await session.scalar(
            sa.select(FlowStepResults.current_attempt_no).where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.step_id == UUID(flow.step_id),
            )
        )
        assert current_attempt is not None
        await session.execute(
            sa.update(FlowRunStepInputFiles)
            .where(FlowRunStepInputFiles.flow_run_id == run_id)
            .values(attempt_no=current_attempt)
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == run_id,
                FlowStepResults.step_order == 1,
            )
            .values(
                status="completed",
                output_payload_json={"text": render_original_segments(SEGMENTS)},
            )
        )

    locked = asyncio.Event()
    proceed = asyncio.Event()
    holder_pid: int | None = None
    source_lock = FlowAudioAfterUseRepository.lock_source
    copy_lock = FlowRunRepository.lock_source_run

    async def hold_release(self, source_id):
        nonlocal holder_pid
        source = await source_lock(self, source_id)
        if source_id == run_id and first == "release":
            assert source is not None
            holder_pid = await _backend_pid(self.session)
            locked.set()
            await asyncio.wait_for(proceed.wait(), timeout=20)
        return source

    async def hold_copy(self, **kwargs):
        nonlocal holder_pid
        await copy_lock(self, **kwargs)
        if kwargs["run_id"] == run_id and first == "retry":
            holder_pid = await _backend_pid(self.session)
            locked.set()
            await asyncio.wait_for(proceed.wait(), timeout=20)

    monkeypatch.setattr(FlowAudioAfterUseRepository, "lock_source", hold_release)
    monkeypatch.setattr(FlowRunRepository, "lock_source_run", hold_copy)

    async def release_audio():
        async with sessionmanager.session() as session, session.begin():
            step = next(
                step
                for step in FlowHousekeepingTask(session).steps()
                if step.name == "audio_after_use"
            )
            return await step.run(
                RetentionBatch(job_run_id=uuid4(), batch_seq=0, rows=5000, files=5000)
            )

    async def retry():
        return await client.post(
            f"/api/v1/flows/{flow.flow_id}/runs/{run_id}/retry/",
            headers={**flow_process_auth_headers, "Idempotency-Key": "audio-race"},
        )

    holder = asyncio.create_task(release_audio() if first == "release" else retry())
    contender = None
    try:
        await asyncio.wait_for(locked.wait(), timeout=20)
        contender = asyncio.create_task(
            retry() if first == "release" else release_audio()
        )
        if first == "release":
            assert holder_pid is not None
            await _until_blocked_by_or_done(holder_pid=holder_pid, task=contender)
            assert not contender.done(), (
                "Retry read the source before audio release committed."
            )
        else:
            deferred = await asyncio.wait_for(contender, timeout=20)
            assert deferred.blocked == {"lock_deferred": 1}
    finally:
        proceed.set()
        if contender is None:
            await asyncio.wait_for(holder, timeout=20)
        else:
            results = await asyncio.wait_for(
                asyncio.gather(holder, contender), timeout=20
            )
    assert contender is not None
    retried = results[1 if first == "release" else 0]
    assert retried.status_code == 201, retried.text
    child_id = UUID(retried.json()["run"]["id"])
    async with db_container() as container:
        session = container.session()
        # A copy that committed first is a real outside owner on the next fresh pass.
        monkeypatch.setattr(FlowAudioAfterUseRepository, "lock_source", source_lock)
        step = next(
            step
            for step in FlowHousekeepingTask(session).steps()
            if step.name == "audio_after_use"
        )
        await step.run(
            RetentionBatch(job_run_id=uuid4(), batch_seq=1, rows=5000, files=5000)
        )
        assert (await session.get(Files, file_id) is None) == (first == "release")
        bindings = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunStepInputFiles)
            .where(
                FlowRunStepInputFiles.flow_run_id == child_id,
                FlowRunStepInputFiles.file_id == file_id,
            )
        )
        assert bool(bindings) == (first == "retry")
        assert await session.get(FlowRuns, run_id) is not None


@pytest.mark.parametrize(
    ("status", "canonical_transcript", "policy", "owner", "released"),
    [
        ("cancelled", False, True, "exclusive", True),
        ("failed", False, True, "exclusive", True),
        ("completed", True, True, "exclusive", True),
        ("completed", False, True, "exclusive", False),
        ("queued", True, True, "exclusive", False),
        ("completed", True, False, "exclusive", False),
        ("completed", True, True, "run", False),
        ("completed", True, True, "live_transcript", False),
        ("completed", True, True, "assistant", False),
        ("completed", True, True, "hold", False),
    ],
)
async def test_audio_after_use_is_atomic_terminal_policy_checked_and_exclusive(
    client,
    flow_process_auth_headers,
    db_container,
    admin_user,
    audio_source_run: tuple[LiveFlow, UUID, UUID],
    status: str,
    canonical_transcript: bool,
    policy: bool,
    owner: Literal["exclusive", "run", "live_transcript", "assistant", "hold"],
    released: bool,
) -> None:
    """Kills G5-A01-A05: nonterminal release, lost transcript, false override, owner/hold bypass."""
    flow, run_id, file_id = audio_source_run
    headers = dict(flow_process_auth_headers)
    async with db_container() as container:
        session = container.session()
        await session.execute(
            sa.update(Flows)
            .where(Flows.id == UUID(flow.flow_id))
            .values(
                delete_transcription_audio_after_use=policy,
            )
        )
        if canonical_transcript:
            await _store_segments(
                session=session,
                run_id=run_id,
                step_id=UUID(flow.step_id),
                segments=SEGMENTS,
            )
        await session.execute(
            sa.update(FlowStepResults)
            .where(FlowStepResults.flow_run_id == run_id)
            .values(
                status="completed" if status == "completed" else "failed",
            )
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == run_id)
            .values(
                status=status,
                finished_at=datetime.now(timezone.utc) if status != "queued" else None,
            )
        )
        if owner == "live_transcript":
            session.add(
                FlowLiveTranscripts(
                    tenant_id=admin_user.tenant_id,
                    user_id=admin_user.id,
                    flow_id=UUID(flow.flow_id),
                    flow_version=1,
                    step_id=UUID(flow.step_id),
                    model_id=uuid4(),
                    recording_id="retained-recording",
                    text="Retained transcript.",
                    received_audio_seconds=1,
                    expires_at=datetime.now(timezone.utc) - timedelta(days=1),
                    bound_file_id=file_id,
                )
            )
        elif owner == "assistant":
            version = await session.scalar(
                sa.select(FlowVersions).where(
                    FlowVersions.flow_id == UUID(flow.flow_id),
                    FlowVersions.version == 1,
                )
            )
            session.add(
                AssistantsFiles(
                    assistant_id=UUID(
                        version.definition_json["steps"][0]["assistant_id"]
                    ),
                    file_id=file_id,
                )
            )
        elif owner == "hold":
            await FlowRetentionHoldRepository(session).insert(
                tenant_id=admin_user.tenant_id,
                flow_id=UUID(flow.flow_id),
                run_ids=[run_id],
                reason="Pending disclosure request",
                review_by=datetime.now(timezone.utc) + timedelta(days=30),
                ends_at=None,
                actor={"type": "user", "id": str(admin_user.id)},
                user_id=admin_user.id,
            )
    if owner == "run":
        second = await client.post(
            f"/api/v1/flows/{flow.flow_id}/runs/",
            headers=headers,
            json={"step_inputs": {flow.step_id: {"file_ids": [str(file_id)]}}},
        )
        assert second.status_code == 201, second.text
    async with db_container() as container:
        task = FlowHousekeepingTask(container.session())
        audio_steps = [step for step in task.steps() if step.name == "audio_after_use"]
        assert len(audio_steps) == 1
        step = audio_steps[0]
        result = await step.run(
            RetentionBatch(job_run_id=uuid4(), batch_seq=0, rows=5000, files=5000)
        )
        assert result.rows <= 5000 and result.files <= 5000
        # A second fresh pass neither invents another release nor detaches a kept binding.
        repeat = await step.run(
            RetentionBatch(job_run_id=uuid4(), batch_seq=1, rows=5000, files=5000)
        )
        assert (
            sum(
                effect.counts.get("audio_inputs_released", 0)
                for effect in repeat.effects
            )
            == 0
        )
    async with db_container() as container:
        session = container.session()
        assert (await session.get(Files, file_id) is None) == released
        assert (
            await session.get(FlowRuntimeUploadedFiles, file_id) is None
        ) == released
        remaining = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunStepInputFiles)
            .where(
                FlowRunStepInputFiles.flow_run_id == run_id,
            )
        )
        assert remaining == (0 if released else 1)
        evidence = await FlowRunReleasedInputRepository(session).list_for_run(
            run_id=run_id, tenant_id=admin_user.tenant_id
        )
        assert [(item.step_id, item.file_id) for item in evidence] == (
            [(UUID(flow.step_id), file_id)] if released else []
        )
        assert await session.get(FlowRuns, run_id) is not None


@pytest.mark.parametrize(
    ("case", "rows", "files", "cap", "released"),
    [
        ("row_tail", 16, 5000, 5000, False),
        ("file_tail", 5000, 1, 5000, False),
        ("family_cap", 5000, 5000, 16, False),
        ("exact_fit", 17, 5000, 5000, True),
        ("required_audit", 5000, 5000, 5000, False),
    ],
)
async def test_audio_after_use_reserves_its_whole_unit_and_rolls_back_required_audit(
    db_container,
    admin_user,
    audio_source_run: tuple[LiveFlow, UUID, UUID],
    monkeypatch,
    case: str,
    rows: int,
    files: int,
    cap: int,
    released: bool,
) -> None:
    """Kills G5-A06/A07: binding/state work outside the cap, tail cursor loss or detached audit."""
    flow, run_id, file_id = audio_source_run
    if case == "required_audit":

        async def unavailable(self, audit_log):
            raise RuntimeError("audit store unavailable")

        monkeypatch.setattr(AuditLogRepositoryImpl, "create_if_absent", unavailable)
    async with sessionmanager.session() as session:
        container = Container(session=providers.Object(session))
        task = FlowHousekeepingTask(session, family_rows=cap)
        if case == "required_audit":
            runner = retention_runner(
                session=session,
                container=container,
                settings=get_settings(),
                budget=RetentionBudget(rows=rows, files=files, seconds=60),
            )
            report = await runner.run(task)
            assert report.outcome is RetentionJobOutcome.FAILED
        else:
            async with session.begin():
                step = next(
                    step for step in task.steps() if step.name == "audio_after_use"
                )
                result = await step.run(
                    RetentionBatch(
                        job_run_id=uuid4(), batch_seq=0, rows=rows, files=files
                    )
                )
                assert result.rows <= rows and result.files <= files
                if case in {"row_tail", "file_tail"}:
                    assert result.deferred and result.cursor is None
                elif case == "family_cap":
                    assert result.blocked == {"family_exceeds_budget": 1}
                else:
                    assert result.rows == 17
    async with db_container() as container:
        session = container.session()
        assert (await session.get(Files, file_id) is None) == released
        assert (
            await session.get(FlowRuntimeUploadedFiles, file_id) is None
        ) == released
        remaining = await session.scalar(
            sa.select(sa.func.count())
            .select_from(FlowRunStepInputFiles)
            .where(FlowRunStepInputFiles.flow_run_id == run_id)
        )
        assert remaining == (0 if released else 1)
        evidence = await FlowRunReleasedInputRepository(session).list_for_run(
            run_id=run_id, tenant_id=admin_user.tenant_id
        )
        assert bool(evidence) == released
        proofs = (
            await session.scalars(
                sa.select(RetentionReceipts).where(
                    RetentionReceipts.entity_id == file_id
                )
            )
        ).all()
        if case == "family_cap":
            assert len(proofs) == 1 and proofs[0].phase == "paused"
            assert proofs[0].source_run_id == run_id
        elif not released:
            assert proofs == []


@pytest.mark.parametrize("held", [False, True])
async def test_a_run_hold_keeps_its_completed_audio_family_proof(
    db_container,
    admin_user,
    audio_source_run: tuple[LiveFlow, UUID, UUID],
    held: bool,
) -> None:
    """Kills G5-A08: prune an audio-family proof while its source run is held."""
    flow, run_id, file_id = audio_source_run
    async with db_container() as container:
        session = container.session()
        task = FlowHousekeepingTask(session)
        release = next(step for step in task.steps() if step.name == "audio_after_use")
        await release.run(
            RetentionBatch(job_run_id=uuid4(), batch_seq=0, rows=5000, files=5000)
        )
        proof_id = await session.scalar(
            sa.select(RetentionReceipts.id).where(
                RetentionReceipts.entity_id == file_id
            )
        )
        assert proof_id is not None
        await session.execute(
            sa.update(RetentionReceipts)
            .where(RetentionReceipts.id == proof_id)
            .values(completed_at=datetime(1900, 1, 1, tzinfo=timezone.utc))
        )
        if held:
            await FlowRetentionHoldRepository(session).insert(
                tenant_id=admin_user.tenant_id,
                flow_id=UUID(flow.flow_id),
                run_ids=[run_id],
                reason="Pending disclosure request",
                review_by=datetime.now(timezone.utc) + timedelta(days=30),
                ends_at=None,
                actor={"type": "user", "id": str(admin_user.id)},
                user_id=admin_user.id,
            )
        prune = next(step for step in task.steps() if step.name == "prune_receipts")
        for batch_seq in range(3):
            await prune.run(
                RetentionBatch(
                    job_run_id=uuid4(), batch_seq=batch_seq, rows=5000, files=0
                )
            )
        assert (await session.get(RetentionReceipts, proof_id) is not None) == held


@pytest.mark.parametrize(
    ("organization", "space", "flow", "expected"),
    [
        (None, None, None, False),
        (True, None, None, True),
        (True, False, None, False),
        (True, False, True, True),
        (False, True, None, True),
        (False, True, False, False),
    ],
)
async def test_audio_policy_sql_matches_the_settings_projection(
    db_container,
    organization: bool | None,
    space: bool | None,
    flow: bool | None,
    expected: bool,
) -> None:
    """Kills G5-A09: SQL truthiness differs from the nullable settings resolver."""
    assert (
        resolve_transcription_audio_after_use(
            organization=organization, space=space, flow=flow
        )
        is expected
    )
    async with db_container() as container:
        actual = await container.session().scalar(
            sa.select(
                effective_transcription_audio_after_use_sql(
                    organization=sa.literal(organization, type_=sa.Boolean()),
                    space=sa.literal(space, type_=sa.Boolean()),
                    flow=sa.literal(flow, type_=sa.Boolean()),
                )
            )
        )
    assert actual is expected


async def test_released_input_evidence_is_atomic_content_free_visible_and_run_owned(
    client,
    admin_token,  # noqa: F811
    admin_user,
    db_container,
) -> None:
    """Kills G5-R01/R02: file cascade, detached evidence commit, missing projection or run cleanup."""
    space = await _create_space(client, token=admin_token)
    flow = await _create_published_flow(client, token=admin_token, space_id=space)
    step_id = UUID(flow["steps"][0]["id"])
    released_at = datetime.now(timezone.utc)
    async with db_container() as container:
        session = container.session()
        run = FlowRuns(
            flow_id=UUID(flow["id"]),
            flow_version=flow["published_version"],
            tenant_id=admin_user.tenant_id,
            principal_user_id=admin_user.id,
            status="cancelled",
            finished_at=released_at,
        )
        file = Files(
            name="private source.wav",
            tenant_id=admin_user.tenant_id,
            owner_type="user",
            owner_user_id=admin_user.id,
        )
        session.add_all([run, file])
        await session.flush()
        run_id, file_id = run.id, file.id
        repo = FlowRunReleasedInputRepository(session)
        bindings = [(step_id, file_id)]
        assert await repo.record(run_id=run_id, bindings=bindings, at=released_at) == 1
        assert await repo.record(run_id=run_id, bindings=bindings, at=released_at) == 0
        await session.execute(sa.delete(Files).where(Files.id == file_id))
    detail = await client.get(
        f"/api/v1/flows/{flow['id']}/runs/{run_id}/",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["released_inputs"] == [
        {
            "step_id": str(step_id),
            "file_id": str(file_id),
            "released_at": released_at.isoformat().replace("+00:00", "Z"),
            "reason": "transcription_audio_after_use",
        }
    ]
    with pytest.raises(RuntimeError, match="release aborted"):
        async with db_container() as container:
            await FlowRunReleasedInputRepository(container.session()).record(
                run_id=run_id, bindings=[(step_id, uuid4())], at=released_at
            )
            raise RuntimeError("release aborted")
    async with db_container() as container:
        session = container.session()
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(FlowRunReleasedInputs)
            )
            == 1
        )
        await session.execute(sa.delete(FlowRuns).where(FlowRuns.id == run_id))
        assert (
            await session.scalar(
                sa.select(sa.func.count()).select_from(FlowRunReleasedInputs)
            )
            == 0
        )
