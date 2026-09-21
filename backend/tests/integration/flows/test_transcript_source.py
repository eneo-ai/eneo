from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from eneo.database.tables.flow_tables import FlowStepAttempts
from eneo.flows import FlowRepository
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_transcript_source_service import (
    FlowTranscriptSourceService,
)
from eneo.flows.domain.transcript_source import (
    MissingTranscriptSourceError,
    TranscriptSourceOmissionReason,
    TranscriptSourceReference,
)
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_transcript_source_repo import (
    FlowTranscriptSourceRepository,
)
from eneo.flows.runtime import transcription
from tests.integration.flows.test_transcript_corrections import (
    SEGMENTS,
    _create_scenario,
)
from tests.unittests.flows import audio_spool_test_support

spool_contract = audio_spool_test_support.spool_contract


@pytest.fixture
async def source_scenario(
    completion_model_factory, space_factory, assistant_factory, admin_user
):
    from eneo.database.database import sessionmanager
    from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session

    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        yield session, scenario, admin_user


def _reference(scenario, source, attempt_no=1):
    return TranscriptSourceReference(
        run_id=scenario.flow_run_id,
        step_id=scenario.transcription_step_id,
        attempt_no=attempt_no,
        source_hash=source.source_hash,
        bounds=source.bounds,
    )


async def _attempt(session, scenario, reference):
    await session.execute(
        sa.insert(FlowStepAttempts).values(
            flow_run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=scenario.transcription_step_id,
            step_order=1,
            attempt_no=reference.attempt_no if reference else 1,
            status="completed",
            started_at=sa.func.now(),
            finished_at=sa.func.now(),
            input_payload_json={
                "schema_version": "flow-step-attempt-input.v1",
                "resolved_input": {
                    "transcription": {"source": reference.model_dump(mode="json")}
                }
                if reference
                else {},
            },
        )
    )


def _service(session, user):
    runs = FlowRunRepository(session=session)
    return FlowTranscriptSourceService(
        user=user,
        access_policy=FlowRunAccessPolicy(
            user=user, flow_repo=FlowRepository(session=session), flow_run_repo=runs
        ),
        flow_run_repo=runs,
        transcript_source_repo=FlowTranscriptSourceRepository(session=session),
    )


async def _read(session, scenario, user, attempt_no=1):
    return await _service(session, user).get_for_attempt(
        flow_id=scenario.flow_id,
        run_id=scenario.flow_run_id,
        step_id=scenario.transcription_step_id,
        attempt_no=attempt_no,
    )


async def test_source_is_immutable_and_retry_has_its_own_row(source_scenario):
    session, scenario, user = source_scenario
    repo = FlowTranscriptSourceRepository(session=session)
    source = transcription.capture_transcript_source(
        segments=SEGMENTS, speaker_review=None, words=[]
    )
    first = _reference(scenario, source)
    await _attempt(session, scenario, first)
    await repo.insert(
        tenant_id=scenario.tenant_id,
        flow_id=scenario.flow_id,
        reference=first,
        source=source,
    )
    with pytest.raises(IntegrityError):
        async with session.begin_nested():
            await repo.insert(
                tenant_id=scenario.tenant_id,
                flow_id=scenario.flow_id,
                reference=first,
                source=source,
            )
    retry = _reference(scenario, source, attempt_no=2)
    await _attempt(session, scenario, retry)
    await repo.insert(
        tenant_id=scenario.tenant_id,
        flow_id=scenario.flow_id,
        reference=retry,
        source=source,
    )
    assert (await _read(session, scenario, user)).source == source
    assert (await _read(session, scenario, user, attempt_no=2)).source == source
    assert (
        await repo.get_for_attempt(
            tenant_id=uuid4(), run_id=first.run_id, step_id=first.step_id, attempt_no=1
        )
        is None
    )


@pytest.mark.parametrize("component", ["segments", "detail", "words", "no_segments"])
async def test_independent_bounds_survive_storage_and_reader(
    source_scenario, monkeypatch, component
):
    session, scenario, user = source_scenario
    if component != "no_segments":
        monkeypatch.setattr(transcription, f"MAX_{component.upper()}_BYTES", 1)
    source = transcription.capture_transcript_source(
        segments=[] if component == "no_segments" else SEGMENTS,
        speaker_review={"files": [{"overlaps": [{"id": "one"}]}]},
        words=[{"segment_index": 0, "words": [{"word": "Vi", "start": 0, "end": 1}]}],
    )
    reference = _reference(scenario, source)
    await _attempt(session, scenario, reference)
    await FlowTranscriptSourceRepository(session=session).insert(
        tenant_id=scenario.tenant_id,
        flow_id=scenario.flow_id,
        reference=reference,
        source=source,
    )
    state = await _read(session, scenario, user)
    if component in {"segments", "no_segments"}:
        assert state.status == "omitted"
        assert state.reason == (
            TranscriptSourceOmissionReason.NO_SEGMENTS
            if component == "no_segments"
            else TranscriptSourceOmissionReason.TOO_LARGE
        )
        assert state.bounds == source.bounds
    else:
        assert state.status == "present"
        assert state.source.segments == SEGMENTS
        assert (
            getattr(state.component_omissions, component)
            == TranscriptSourceOmissionReason.TOO_LARGE
        )


async def test_pre_row_attempt_is_explicitly_unavailable(source_scenario):
    session, scenario, user = source_scenario
    await _attempt(session, scenario, None)
    assert (await _read(session, scenario, user)).status == "unavailable_pre_row"


async def test_marker_without_row_raises_typed_integrity_failure(source_scenario):
    session, scenario, user = source_scenario
    source = transcription.capture_transcript_source(
        segments=SEGMENTS, speaker_review=None, words=[]
    )
    await _attempt(session, scenario, _reference(scenario, source))
    with pytest.raises(MissingTranscriptSourceError):
        await _read(session, scenario, user)


async def test_regenerated_child_resolves_after_parent_is_deleted(source_scenario):
    from eneo.database.tables.flow_tables import FlowRuns
    from eneo.flows.domain.flow import FlowStepResultStatus
    from eneo.flows.domain.transcript_regeneration import FlowRunPrefixSeed
    from eneo.flows.domain.transcript_source import (
        transcript_source_reference,
        with_transcript_source_reference,
    )

    session, scenario, user = source_scenario
    source = transcription.capture_transcript_source(
        segments=SEGMENTS, speaker_review={"files": []}, words=[]
    )
    reference = _reference(scenario, source, attempt_no=3)
    await _attempt(session, scenario, reference)
    await FlowTranscriptSourceRepository(session=session).insert(
        tenant_id=scenario.tenant_id,
        flow_id=scenario.flow_id,
        reference=reference,
        source=source,
    )
    runs = FlowRunRepository(session=session)
    parent_result = await runs.get_step_result(
        run_id=scenario.flow_run_id,
        step_id=scenario.transcription_step_id,
        tenant_id=scenario.tenant_id,
    )
    parent_result = parent_result.model_copy(
        update={
            "current_attempt_no": 3,
            "status": FlowStepResultStatus.COMPLETED,
            "input_payload_json": with_transcript_source_reference(
                parent_result.input_payload_json, reference
            ),
        }
    )
    child = await runs.create(
        flow_id=scenario.flow_id,
        flow_version=1,
        principal_user_id=user.id,
        tenant_id=scenario.tenant_id,
        input_payload_json={},
        preseed_steps=[
            {
                "step_id": scenario.transcription_step_id,
                "assistant_id": parent_result.assistant_id,
                "step_order": 1,
            }
        ],
    )
    await runs.seed_validated_prefix(
        run=child,
        seed=FlowRunPrefixSeed(
            source_run_id=scenario.flow_run_id,
            results=(parent_result,),
            kind="reviewed_transcript_snapshot",
            provenance={"request_hash": "r"},
        ),
    )
    child_result = await runs.get_step_result(
        run_id=child.id,
        step_id=scenario.transcription_step_id,
        tenant_id=scenario.tenant_id,
    )
    child_reference = transcript_source_reference(child_result.input_payload_json)
    assert child_reference.run_id == child.id
    assert child_reference.attempt_no == 1
    await session.execute(
        sa.delete(FlowRuns).where(FlowRuns.id == scenario.flow_run_id)
    )
    state = await _service(session, user).get_for_attempt(
        flow_id=scenario.flow_id,
        run_id=child.id,
        step_id=scenario.transcription_step_id,
        attempt_no=1,
    )
    assert state.status == "present"
    assert state.source == source


async def _publication_case(session, scenario, user, source=None):
    from dataclasses import replace

    from eneo.database.tables.flow_tables import FlowRuns, FlowStepResults
    from tests.unittests.flows.test_typed_io_executor import (
        _build_executor,
        _runtime_step,
    )

    runs = FlowRunRepository(session=session)
    result = await runs.get_step_result(
        run_id=scenario.flow_run_id,
        step_id=scenario.transcription_step_id,
        tenant_id=scenario.tenant_id,
    )
    step = replace(
        _runtime_step(),
        step_id=scenario.transcription_step_id,
        assistant_id=result.assistant_id,
    )
    await session.execute(
        sa.update(FlowRuns)
        .where(FlowRuns.id == scenario.flow_run_id)
        .values(
            status="running",
            started_at=sa.func.now(),
            execution_heartbeat_at=sa.func.now(),
        )
    )
    run = await runs.get(run_id=scenario.flow_run_id, tenant_id=scenario.tenant_id)
    await session.execute(
        sa.insert(FlowStepAttempts).values(
            flow_run_id=run.id,
            flow_id=run.flow_id,
            tenant_id=run.tenant_id,
            step_id=step.step_id,
            step_order=1,
            attempt_no=1,
            status="started",
            started_at=sa.func.now(),
        )
    )
    await session.execute(
        sa.update(FlowStepResults)
        .where(FlowStepResults.id == result.id)
        .values(status="running", current_attempt_no=1)
    )
    await session.commit()
    result = await runs.get_step_result(
        run_id=run.id, step_id=step.step_id, tenant_id=run.tenant_id
    )
    await session.commit()
    executor, _, _, _ = _build_executor(user, max_inline_text_bytes=2048)
    executor.session = session
    executor.flow_run_repo = runs
    source = source or transcription.capture_transcript_source(
        segments=SEGMENTS, speaker_review=None, words=[]
    )
    executor._stage_transcript_source(_reference(scenario, source), source)
    return executor, run, step, result, source


async def _publish(executor, run, step, result, boundary):
    from eneo.flows.flow_run_provenance import FlowResolvedInputEdges
    from eneo.main.exceptions import TypedIOValidationException
    from tests.integration.flows.test_flow_terminalization_contract import (
        _flow_run_terminalizer,
    )
    from tests.unittests.flows.test_flow_transcription import _state

    if boundary == "activation":
        await executor._activate_step_attempt(
            run=run,
            step=step,
            state=_state(),
            attempt_no=1,
            resolved_input_edges=FlowResolvedInputEdges(schema_version=1, edges=()),
            attempt_start=None,
            resolved_input=result.input_payload_json,
        )
    elif boundary == "generic_failure":
        executor.flow_run_terminalizer = _flow_run_terminalizer(executor.flow_run_repo)
        await executor._handle_generic_step_failure(
            run_id=run.id,
            tenant_id=run.tenant_id,
            step=step,
            attempt_no=1,
            claimed=result,
            exc=RuntimeError("input resolution interrupted"),
        )
    else:
        executor.flow_run_terminalizer = _flow_run_terminalizer(executor.flow_run_repo)
        await executor._handle_typed_step_failure(
            run_id=run.id,
            tenant_id=run.tenant_id,
            step=step,
            attempt_no=1,
            claimed=result,
            typed_exc=TypedIOValidationException(
                "Invalid input", code="TYPED_IO_VALIDATION_ERROR"
            ),
            failed_input_payload=result.input_payload_json,
        )


@pytest.mark.parametrize(
    "boundary", ["activation", "failure_before_activation", "generic_failure"]
)
@pytest.mark.parametrize("after_insert", [False, True])
async def test_publication_rolls_back_to_prior_committed_state(
    source_scenario, monkeypatch, boundary, after_insert
):
    from eneo.database.database import sessionmanager
    from eneo.flows.domain.transcript_source import transcript_source_reference

    session, scenario, user = source_scenario
    executor, run, step, result, source = await _publication_case(
        session, scenario, user
    )

    original_insert = FlowTranscriptSourceRepository.insert

    async def fail_insert(self, **kwargs):
        attempt = await executor.flow_run_repo.get_step_attempt(
            run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id, attempt_no=1
        )
        assert transcript_source_reference(attempt.input_payload_json) is not None
        if boundary != "activation":
            written = await executor.flow_run_repo.get_step_result(
                run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id
            )
            assert transcript_source_reference(written.input_payload_json) is not None
        if after_insert:
            await original_insert(self, **kwargs)
        raise RuntimeError("source insert interrupted")

    monkeypatch.setattr(FlowTranscriptSourceRepository, "insert", fail_insert)
    with pytest.raises(RuntimeError, match="source insert interrupted"):
        await _publish(executor, run, step, result, boundary)
    await session.rollback()
    async with sessionmanager.session() as fresh, fresh.begin():
        runs = FlowRunRepository(session=fresh)
        prior = await runs.get_step_result(
            run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id
        )
        attempt = await runs.get_step_attempt(
            run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id, attempt_no=1
        )
        assert prior.input_payload_json == result.input_payload_json
        assert prior.status.value == "running"
        assert attempt.status.value == "started"
        assert transcript_source_reference(attempt.input_payload_json) is None
        assert (
            await FlowTranscriptSourceRepository(session=fresh).get_for_attempt(
                tenant_id=run.tenant_id,
                run_id=run.id,
                step_id=step.step_id,
                attempt_no=1,
            )
            is None
        )


@pytest.mark.parametrize(
    "boundary", ["activation", "failure_before_activation", "generic_failure"]
)
async def test_publication_commits_reference_and_row_together(
    source_scenario, boundary
):
    from eneo.database.database import sessionmanager

    session, scenario, user = source_scenario
    executor, run, step, result, source = await _publication_case(
        session, scenario, user
    )
    await _publish(executor, run, step, result, boundary)
    async with sessionmanager.session() as fresh, fresh.begin():
        state = await _read(fresh, scenario, user)
        assert state.status == "present"
        assert state.source == source


async def test_fenced_out_publication_writes_neither_row_nor_reference(source_scenario):
    from eneo.database.database import sessionmanager
    from eneo.database.tables.flow_tables import FlowRuns
    from eneo.flows.domain.transcript_source import transcript_source_reference
    from eneo.flows.infrastructure.flow_run_repo import (
        FlowRunExecutionOwner,
        flow_run_execution_owner,
    )
    from eneo.flows.runtime.execution_heartbeat import FlowExecutionOwnershipLost

    session, scenario, user = source_scenario
    executor, run, step, result, source = await _publication_case(
        session, scenario, user
    )
    owner = FlowRunExecutionOwner(run.id, run.tenant_id, run.revision)
    assert await executor.flow_run_repo.has_execution_ownership(owner=owner)
    await session.execute(
        sa.update(FlowRuns)
        .where(FlowRuns.id == run.id)
        .values(revision=run.revision + 1)
    )
    await session.commit()
    token = flow_run_execution_owner.set(owner)
    try:
        with pytest.raises(FlowExecutionOwnershipLost):
            await _publish(executor, run, step, result, "activation")
    finally:
        flow_run_execution_owner.reset(token)
    async with sessionmanager.session() as fresh, fresh.begin():
        attempt = await FlowRunRepository(session=fresh).get_step_attempt(
            run_id=run.id, step_id=step.step_id, tenant_id=run.tenant_id, attempt_no=1
        )
        assert transcript_source_reference(attempt.input_payload_json) is None
        assert (
            await FlowTranscriptSourceRepository(session=fresh).get_for_attempt(
                tenant_id=run.tenant_id,
                run_id=run.id,
                step_id=step.step_id,
                attempt_no=1,
            )
            is None
        )


@pytest.mark.parametrize("large_component", ["segments", "detail"])
async def test_large_producer_source_survives_publication(
    source_scenario, spool_contract, large_component
):
    from eneo.database.database import sessionmanager
    from eneo.files.transcriber import TranscribedAudio
    from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
        TranscriptSegment,
    )
    from tests.unit.flows.runtime.test_transcription_speaker_inventory import (
        _file,
        _run,
        _transcriber,
    )

    text = "å" * 150_000 if large_component == "segments" else "Hej."
    detail = (
        {"overlaps": [{"id": "overlap", "text": "å" * 150_000}]}
        if large_component == "detail"
        else None
    )
    transcribed = await _run(
        spool_contract,
        [_file("a.mp3")],
        _transcriber(
            TranscribedAudio(
                "Transcript.",
                18_000.0,
                transcript_segments=(TranscriptSegment(text, 0.0, 18_000.0),),
                speaker_review=detail,
            )
        ),
    )
    assert transcribed.segments is None
    assert transcribed.segments_omitted_reason == "too_large"
    session, scenario, user = source_scenario
    executor, run, step, result, source = await _publication_case(
        session, scenario, user, transcribed.source
    )
    result = result.model_copy(
        update={"input_payload_json": {"transcription": transcribed.to_metadata()}}
    )
    await _publish(executor, run, step, result, "activation")
    async with sessionmanager.session() as fresh, fresh.begin():
        state = await _read(fresh, scenario, user)
        assert state.source == transcribed.source
        assert state.source.segments[0]["text"] == text
        attempt = await FlowRunRepository(session=fresh).get_step_attempt(
            run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id, attempt_no=1
        )
        payload = attempt.input_payload_json["resolved_input"]["transcription"]
        assert {
            key: value for key, value in payload.items() if key != "source"
        } == transcribed.to_metadata()
