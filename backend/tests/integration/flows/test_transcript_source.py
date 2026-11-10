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
from tests.integration.flows import transcript_source_support
from tests.integration.flows.statement_capture_support import capture_queries
from tests.integration.flows.test_transcript_corrections import SEGMENTS
from tests.unittests.flows import audio_spool_test_support

spool_contract = audio_spool_test_support.spool_contract
source_scenario = transcript_source_support.source_scenario


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


@pytest.mark.parametrize("step_count", [1, 50])
async def test_step_listing_batches_reference_only_attempt_reads(
    source_scenario, client, db_container, patch_auth_service_jwt, step_count
):
    import re

    from eneo.database.tables.flow_tables import FlowStepResults
    from eneo.database.tables.spaces_table import SpacesUsers
    from eneo.spaces.api.space_models import SpaceRoleValue

    session, scenario, user = source_scenario
    await session.execute(
        sa.update(FlowStepResults)
        .where(FlowStepResults.flow_run_id == scenario.flow_run_id)
        .values(current_attempt_no=None, input_payload_json={})
    )
    for index in range(step_count):
        identity = dict(
            flow_run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=user.tenant_id,
            step_id=uuid4(),
            step_order=index + 3,
        )
        session.add(FlowStepResults(**identity, status="running", current_attempt_no=1))
        session.add(
            FlowStepAttempts(
                **identity,
                attempt_no=1,
                status="started",
                started_at=sa.func.now(),
                input_payload_json={
                    "schema_version": "flow-step-attempt-input.v1",
                    "resolved_input": {"text": "input" * 1000},
                },
                output_payload_json={"text": "output" * 1000},
                provenance_json={"payload": "provenance" * 1000},
            )
        )
    flow = await FlowRepository(session=session).get(scenario.flow_id, user.tenant_id)
    session.add(
        SpacesUsers(space_id=flow.space_id, user_id=user.id, role=SpaceRoleValue.EDITOR)
    )
    await session.commit()
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(user)
    bind = session.sync_session.bind
    assert bind is not None
    with capture_queries(bind) as queries:
        response = await client.get(
            f"/api/v1/flows/{scenario.flow_id}/runs/{scenario.flow_run_id}/steps/",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    assert len(response.json()) == step_count + 2
    attempts = [query.sql for query in queries if "flow_step_attempts" in query.sql]
    assert len(attempts) == 1
    assert "output_payload_json" not in attempts[0]
    assert "provenance_json" not in attempts[0]
    assert not re.search(
        r"flow_step_attempts\.input_payload_json(?:\s+AS\s+\w+)?(?:,|\s+FROM)",
        attempts[0],
    )
    assert "segments_json" not in attempts[0]
    assert "detail_json" not in attempts[0]


@pytest.mark.parametrize("envelope", [False, True])
@pytest.mark.parametrize(
    "state", ["present", "omitted", "missing_row", "hash", "bounds", "identity", "null"]
)
async def test_batched_references_validate_canonical_current_attempt(
    source_scenario, envelope, state
):
    from eneo.database.tables.flow_tables import FlowStepResults

    session, scenario, user = source_scenario
    source = transcription.capture_transcript_source(
        segments=[] if state == "omitted" else SEGMENTS,
        speaker_review={"files": []},
        words=[],
        words_omitted_reason=None,
    )
    reference = _reference(scenario, source, attempt_no=2)
    await _attempt(session, scenario, _reference(scenario, source))
    await _attempt(session, scenario, reference)
    if state != "missing_row":
        await FlowTranscriptSourceRepository(session=session).insert(
            tenant_id=user.tenant_id,
            flow_id=scenario.flow_id,
            reference=reference,
            source=source,
        )
    marker = reference.model_dump(mode="json")
    if state == "hash":
        marker["source_hash"] = "b" * 64
    elif state == "bounds":
        marker["bounds"]["detail_bytes"] += 1
    elif state == "identity":
        marker["attempt_no"] = 1
    elif state == "null":
        marker = None
    payload = {"transcription": {"source": marker}}
    if envelope:
        payload = {
            "schema_version": "flow-step-attempt-input.v1",
            "resolved_input": payload,
            "transcription": {"source": "ignored outside the envelope"},
        }
    await session.execute(
        sa.update(FlowStepAttempts)
        .where(
            FlowStepAttempts.flow_run_id == scenario.flow_run_id,
            FlowStepAttempts.attempt_no == 2,
        )
        .values(input_payload_json=payload)
    )
    await session.execute(
        sa.update(FlowStepResults)
        .where(
            FlowStepResults.flow_run_id == scenario.flow_run_id,
            FlowStepResults.step_id == scenario.transcription_step_id,
        )
        .values(current_attempt_no=2, input_payload_json={})
    )
    result = await FlowRunRepository(session=session).get_step_result(
        run_id=scenario.flow_run_id,
        tenant_id=user.tenant_id,
        step_id=scenario.transcription_step_id,
    )
    bind = session.sync_session.bind
    assert bind is not None
    with capture_queries(bind) as queries:
        call = _service(session, user).get_references_for_step_results(
            flow_id=scenario.flow_id, run_id=scenario.flow_run_id, step_results=[result]
        )
        if state in ("present", "omitted"):
            assert await call == {scenario.transcription_step_id: reference}
        else:
            with pytest.raises(
                MissingTranscriptSourceError if state == "missing_row" else ValueError
            ):
                await call
    assert (
        len(
            [
                query
                for query in queries
                if "flow_step_attempts" in query.sql
                or "flow_step_transcript_sources" in query.sql
            ]
        )
        == 1
    )


async def test_detail_route_pages_absolute_indexes_and_whole_source_hash(
    source_scenario, client, db_container, patch_auth_service_jwt, monkeypatch
):
    from eneo.database.tables.flow_tables import FlowStepResults
    from eneo.database.tables.spaces_table import SpacesUsers
    from eneo.spaces.api.space_models import SpaceRoleValue

    session, scenario, user = source_scenario
    segments = [
        {**SEGMENTS[0], "text": f"{index}: " + "å" * 800} for index in range(201)
    ]
    review = {"files": [{"file_index": 0, "overlaps": [{"text": "å" * 150_000}]}]}
    source = transcription.capture_transcript_source(
        segments=segments, speaker_review=review, words=[], words_omitted_reason=None
    )
    reference = _reference(scenario, source)
    await _attempt(session, scenario, reference)
    await FlowTranscriptSourceRepository(session=session).insert(
        tenant_id=user.tenant_id,
        flow_id=scenario.flow_id,
        reference=reference,
        source=source,
    )
    await session.execute(
        sa.update(FlowStepResults)
        .where(
            FlowStepResults.flow_run_id == scenario.flow_run_id,
            FlowStepResults.step_id == scenario.transcription_step_id,
        )
        .values(current_attempt_no=1, input_payload_json={"transcription": {}})
    )
    flow = await FlowRepository(session=session).get(scenario.flow_id, user.tenant_id)
    session.add(
        SpacesUsers(space_id=flow.space_id, user_id=user.id, role=SpaceRoleValue.EDITOR)
    )
    await session.commit()
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(user)
    path = (
        f"/api/v1/flows/{scenario.flow_id}/runs/{scenario.flow_run_id}"
        f"/steps/{scenario.transcription_step_id}/attempts/1/transcript-source/"
    )
    headers = {"Authorization": f"Bearer {token}"}
    first = await client.get(path, headers=headers)
    assert first.status_code == 200, first.text
    page = first.json()
    assert page["status"] == "present"
    assert page["run_id"] == str(scenario.flow_run_id)
    assert page["step_id"] == str(scenario.transcription_step_id)
    assert page["attempt_no"] == 1
    assert page["source_hash"] == source.source_hash
    assert page["bounds"] == source.bounds.model_dump(mode="json")
    assert page["component_omissions"] == {"detail": None, "words": None}
    assert page["speaker_review"] == review
    assert page["page_size"] == 200
    assert page["max_response_bytes"] == 16 * 1024 * 1024
    assert len(first.content) <= page["max_response_bytes"]
    assert page["start_segment_index"] == 0
    assert page["next_segment_index"] == 200
    assert page["segments"] == [
        {**segment, "segment_index": index}
        for index, segment in enumerate(segments[:200])
    ]
    second = await client.get(
        path,
        headers=headers,
        params={"start_segment_index": page["next_segment_index"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["segments"] == [{**segments[200], "segment_index": 200}]
    assert second.json()["next_segment_index"] is None
    assert second.json()["source_hash"] == page["source_hash"]
    assert "speaker_review" not in second.json()
    listing = await client.get(
        f"/api/v1/flows/{scenario.flow_id}/runs/{scenario.flow_run_id}/steps/",
        headers=headers,
    )
    assert listing.status_code == 200, listing.text
    assert len(listing.content) < 10_000
    metadata = listing.json()[0]["input_payload_json"]["transcription"]
    assert "segments" not in metadata
    assert "speaker_review" not in metadata
    assert metadata["segments_hash"] == page["source_hash"]
    corrections_path = (
        f"/api/v1/flows/{scenario.flow_id}/runs/{scenario.flow_run_id}"
        f"/steps/{scenario.transcription_step_id}/transcript-corrections/"
    )
    missing_hash = await client.patch(
        corrections_path, headers=headers, json={"schema_version": 2, "occurrences": []}
    )
    assert missing_hash.status_code == 422, missing_hash.text

    from eneo.flows.api import flow_transcript_source_router

    monkeypatch.setattr(
        flow_transcript_source_router, "RUN_VIEW_MAX_LOADED_SECTION_LOGICAL_BYTES", 1000
    )
    oversized = await client.get(path, headers=headers)
    assert oversized.status_code == 413, oversized.text
    assert "segments" not in oversized.json()


@pytest.mark.parametrize(
    "state", ["pre_row", "omitted", "missing_attempt", "audit_failure"]
)
async def test_detail_route_preserves_unavailability_and_audit_contract(
    source_scenario, client, db_container, patch_auth_service_jwt, monkeypatch, state
):
    from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
    from eneo.database.tables.spaces_table import SpacesUsers
    from eneo.spaces.api.space_models import SpaceRoleValue

    session, scenario, user = source_scenario
    if state == "omitted":
        source = transcription.capture_transcript_source(
            segments=[], speaker_review=None, words=[], words_omitted_reason=None
        )
        reference = _reference(scenario, source)
        await _attempt(session, scenario, reference)
        await FlowTranscriptSourceRepository(session=session).insert(
            tenant_id=user.tenant_id,
            flow_id=scenario.flow_id,
            reference=reference,
            source=source,
        )
    elif state != "missing_attempt":
        await _attempt(session, scenario, None)
    flow = await FlowRepository(session=session).get(scenario.flow_id, user.tenant_id)
    session.add(
        SpacesUsers(space_id=flow.space_id, user_id=user.id, role=SpaceRoleValue.EDITOR)
    )
    await session.commit()
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(user)
    if state == "audit_failure":

        async def unavailable(self, audit_log):
            raise RuntimeError("audit storage unavailable")

        monkeypatch.setattr(AuditLogRepositoryImpl, "create", unavailable)
    response = await client.get(
        f"/api/v1/flows/{scenario.flow_id}/runs/{scenario.flow_run_id}"
        f"/steps/{scenario.transcription_step_id}/attempts/1/transcript-source/",
        headers={"Authorization": f"Bearer {token}"},
    )
    if state == "missing_attempt":
        assert response.status_code == 404, response.text
    elif state == "audit_failure":
        assert response.status_code == 503, response.text
    else:
        assert response.status_code == 200, response.text
        expected = {
            "status": "omitted" if state == "omitted" else "unavailable_pre_row",
            "run_id": str(scenario.flow_run_id),
            "step_id": str(scenario.transcription_step_id),
            "attempt_no": 1,
        }
        if state == "omitted":
            expected.update(reason=2, bounds=source.bounds.model_dump(mode="json"))
        assert response.json() == expected


async def test_source_is_immutable_and_retry_has_its_own_row(source_scenario):
    session, scenario, user = source_scenario
    repo = FlowTranscriptSourceRepository(session=session)
    source = transcription.capture_transcript_source(
        segments=SEGMENTS, speaker_review=None, words=[], words_omitted_reason=None
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


async def test_corrections_use_canonical_attempt_and_require_its_hash(source_scenario):
    from eneo.database.tables.flow_tables import FlowStepResults
    from eneo.flows.flow_api_error_code import FlowApiErrorCode
    from eneo.flows.flow_api_exceptions import FlowBadRequestException
    from tests.integration.flows.test_transcript_corrections import (
        _service as corrections_service,
    )

    session, scenario, user = source_scenario
    source = transcription.capture_transcript_source(
        segments=SEGMENTS, speaker_review=None, words=[], words_omitted_reason=None
    )
    reference = _reference(scenario, source)
    await _attempt(session, scenario, reference)
    await FlowTranscriptSourceRepository(session=session).insert(
        tenant_id=user.tenant_id,
        flow_id=scenario.flow_id,
        reference=reference,
        source=source,
    )
    await session.execute(
        sa.update(FlowStepResults)
        .where(
            FlowStepResults.flow_run_id == scenario.flow_run_id,
            FlowStepResults.step_id == scenario.transcription_step_id,
        )
        .values(current_attempt_no=1, input_payload_json={})
    )
    service = corrections_service(session=session, admin_user=user)
    args = dict(
        flow_id=scenario.flow_id,
        run_id=scenario.flow_run_id,
        step_id=scenario.transcription_step_id,
        occurrences=[],
    )
    saved = await service.save(
        **args, expected_revision=None, expected_segments_hash=source.source_hash
    )
    assert saved.corrections.segments_hash == source.source_hash
    assert saved.stale is False
    for invalid_hash in (None, "0" * 64):
        with pytest.raises(FlowBadRequestException) as exc:
            await service.save(
                **args, expected_revision=1, expected_segments_hash=invalid_hash
            )
        assert exc.value.code == FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_STALE_REVISION
        assert exc.value.context["reason"] == "stale_segments"


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
        words_omitted_reason="too_large" if component == "words" else None,
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
        segments=SEGMENTS, speaker_review=None, words=[], words_omitted_reason=None
    )
    await _attempt(session, scenario, _reference(scenario, source))
    with pytest.raises(MissingTranscriptSourceError):
        await _read(session, scenario, user)


async def test_export_rejects_missing_referenced_source(source_scenario):
    session, scenario, user = source_scenario
    source = transcription.capture_transcript_source(
        segments=SEGMENTS, speaker_review=None, words=[], words_omitted_reason=None
    )
    await _attempt(session, scenario, _reference(scenario, source))
    attempts = await FlowRunRepository(session=session).list_step_attempts(
        run_id=scenario.flow_run_id, tenant_id=user.tenant_id
    )
    with pytest.raises(MissingTranscriptSourceError):
        await _service(session, user).get_for_export(
            run_id=scenario.flow_run_id, limit=10_000, attempts=attempts.attempts
        )


@pytest.mark.parametrize("reference_on_result", [False, True])
async def test_regenerated_child_resolves_after_parent_is_deleted(
    source_scenario, reference_on_result
):
    from eneo.database.tables.flow_tables import FlowRuns
    from eneo.flows.domain.flow import FlowStepResultStatus
    from eneo.flows.domain.transcript_regeneration import FlowRunPrefixSeed
    from eneo.flows.domain.transcript_source import (
        transcript_source_reference,
        with_transcript_source_reference,
    )

    session, scenario, user = source_scenario
    source = transcription.capture_transcript_source(
        segments=SEGMENTS,
        speaker_review={"files": []},
        words=[],
        words_omitted_reason=None,
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
            )
            if reference_on_result
            else {"runtime_input": {"execution_mode": "per_source"}},
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


async def _publication_case(session, scenario, user, preparation=None):
    from dataclasses import replace

    from eneo.database.tables.flow_tables import FlowRuns, FlowStepResults
    from eneo.flows.infrastructure.flow_transcript_words_repo import (
        FlowTranscriptWordsRepository,
    )
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
    words_repo = FlowTranscriptWordsRepository(session=session)
    await words_repo.upsert(
        tenant_id=run.tenant_id,
        flow_id=run.flow_id,
        run_id=run.id,
        step_id=step.step_id,
        segments_hash="a" * 64,
        alignment="forced",
        words_json=[
            {"segment_index": 0, "words": [{"word": "Prior", "start": 0, "end": 1}]}
        ],
    )
    await session.commit()
    result = await runs.get_step_result(
        run_id=run.id, step_id=step.step_id, tenant_id=run.tenant_id
    )
    await session.commit()
    executor, _, _, _ = _build_executor(user, max_inline_text_bytes=2048)
    executor.session = session
    executor.flow_run_repo = runs
    executor.transcript_words_repo = words_repo
    preparation = preparation or transcription.TranscriptSourcePreparation(
        files_count=1,
        segments=SEGMENTS,
        speaker_review=None,
        words=[],
        words_omitted_reason=None,
    )
    source = preparation.source
    executor._stage_transcript_source(_reference(scenario, source), preparation)
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
    from eneo.flows.infrastructure.flow_transcript_words_repo import (
        FlowTranscriptWordsRepository,
    )

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
        words = await FlowTranscriptWordsRepository(session=fresh).get_for_step(
            run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id
        )
        assert words.segments_hash == "a" * 64
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
    from eneo.flows.infrastructure.flow_transcript_words_repo import (
        FlowTranscriptWordsRepository,
    )

    session, scenario, user = source_scenario
    executor, run, step, result, source = await _publication_case(
        session, scenario, user
    )
    await _publish(executor, run, step, result, boundary)
    async with sessionmanager.session() as fresh, fresh.begin():
        state = await _read(fresh, scenario, user)
        assert state.status == "present"
        assert state.source == source
        assert (
            await FlowTranscriptWordsRepository(session=fresh).get_for_step(
                run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id
            )
            is None
        )


@pytest.mark.parametrize("limited_component", [None, "segments", "detail", "words"])
async def test_multiple_preparations_publish_one_bounded_source(
    source_scenario, monkeypatch, limited_component
):
    import json

    from eneo.database.database import sessionmanager
    from eneo.flows.domain.transcript_corrections import segments_content_hash
    from eneo.flows.infrastructure.flow_transcript_words_repo import (
        FlowTranscriptWordsRepository,
    )

    parts = [
        dict(
            files_count=1,
            segments=[{**SEGMENTS[0], "file_index": 0, "text": text}],
            speaker_review={
                "files": [{"file_index": 0, "file_id": str(uuid4()), "overlaps": []}]
            },
            words=[
                {"segment_index": 0, "words": [{"word": text, "start": 0, "end": 1}]}
            ],
            words_omitted_reason=None,
        )
        for text in ("First transcript.", "Second transcript.")
    ]
    expected_segments = [
        {**part["segments"][0], "file_index": index} for index, part in enumerate(parts)
    ]
    expected_detail = {
        "files": [
            {**part["speaker_review"]["files"][0], "file_index": index}
            for index, part in enumerate(parts)
        ]
    }
    if limited_component:
        bound = (
            max(
                len(
                    json.dumps(
                        {
                            "segments": part["segments"],
                            "detail": part["speaker_review"],
                            "words": part["words"],
                        }[limited_component],
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                for part in parts
            )
            + 1
        )
        monkeypatch.setattr(
            transcription, f"MAX_{limited_component.upper()}_BYTES", bound
        )
    preparation = transcription.TranscriptSourcePreparation(**parts[0])
    session, scenario, user = source_scenario
    executor, run, step, result, _ = await _publication_case(
        session, scenario, user, preparation
    )
    executor.transcript_words_repo = FlowTranscriptWordsRepository(session=session)
    preparation.append(**parts[1])
    executor._stage_transcript_source(
        _reference(scenario, preparation.source), preparation
    )
    await _publish(executor, run, step, result, "activation")
    async with sessionmanager.session() as fresh, fresh.begin():
        source = await FlowTranscriptSourceRepository(session=fresh).get_for_attempt(
            tenant_id=run.tenant_id, run_id=run.id, step_id=step.step_id, attempt_no=1
        )
        assert source.source_hash == segments_content_hash(expected_segments)
        assert source.bounds.segments_count == 2
        assert source.bounds.words_count == 2
        assert source.bounds.segments_bytes == len(
            json.dumps(expected_segments, ensure_ascii=False).encode("utf-8")
        )
        assert source.bounds.detail_bytes == len(
            json.dumps(expected_detail, ensure_ascii=False).encode("utf-8")
        )
        assert source.segments == (
            None if limited_component == "segments" else expected_segments
        )
        assert source.speaker_review == (
            None if limited_component == "detail" else expected_detail
        )
        state = await _read(fresh, scenario, user)
        if limited_component == "segments":
            assert state.status == "omitted"
            assert state.reason == TranscriptSourceOmissionReason.TOO_LARGE
        else:
            assert state.status == "present"
            assert state.component_omissions.detail == (
                TranscriptSourceOmissionReason.TOO_LARGE
                if limited_component == "detail"
                else None
            )
            assert state.component_omissions.words == (
                TranscriptSourceOmissionReason.TOO_LARGE
                if limited_component == "words"
                else None
            )
        words = await FlowTranscriptWordsRepository(session=fresh).get_for_step(
            run_id=run.id, step_id=step.step_id, tenant_id=run.tenant_id
        )
        if limited_component in ("segments", "words"):
            assert words is None
        else:
            assert words is not None
            assert words.segments_hash == source.source_hash
            assert words.words_json == [
                {**part["words"][0], "segment_index": index}
                for index, part in enumerate(parts)
            ]


async def test_fenced_out_publication_writes_neither_row_nor_reference(source_scenario):
    from eneo.database.database import sessionmanager
    from eneo.database.tables.flow_tables import FlowRuns
    from eneo.flows.domain.transcript_source import transcript_source_reference
    from eneo.flows.infrastructure.flow_run_repo import (
        FlowRunExecutionOwner,
        flow_run_execution_owner,
    )
    from eneo.flows.infrastructure.flow_transcript_words_repo import (
        FlowTranscriptWordsRepository,
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
        words = await FlowTranscriptWordsRepository(session=fresh).get_for_step(
            run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id
        )
        assert words.segments_hash == "a" * 64
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
    from eneo.files.transcript import (
        TranscriptSegment,
        TranscriptWord,
    )
    from eneo.flows.infrastructure.flow_transcript_words_repo import (
        FlowTranscriptWordsRepository,
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
                transcript_segments=(
                    TranscriptSegment(
                        text,
                        0.0,
                        18_000.0,
                        words=(TranscriptWord("Hej", 0.0, 1.0),),
                    ),
                ),
                speaker_review=detail,
            )
        ),
    )
    assert "segments" not in transcribed.to_metadata()
    assert "speaker_review" not in transcribed.to_metadata()
    session, scenario, user = source_scenario
    executor, run, step, result, source = await _publication_case(
        session, scenario, user, transcribed.source_preparation
    )
    executor.transcript_words_repo = FlowTranscriptWordsRepository(session=session)
    result = result.model_copy(
        update={"input_payload_json": {"transcription": transcribed.to_metadata()}}
    )
    await _publish(executor, run, step, result, "activation")
    async with sessionmanager.session() as fresh, fresh.begin():
        state = await _read(fresh, scenario, user)
        assert state.source == transcribed.source
        assert state.source.segments[0]["text"] == text
        assert state.source.bounds.words_count == 1
        assert state.component_omissions.words is None
        words = await FlowTranscriptWordsRepository(session=fresh).get_for_step(
            run_id=run.id, step_id=step.step_id, tenant_id=run.tenant_id
        )
        assert words is not None
        assert words.segments_hash == state.source.source_hash
        assert words.words_json[0]["segment_index"] == 0
        attempt = await FlowRunRepository(session=fresh).get_step_attempt(
            run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id, attempt_no=1
        )
        payload = attempt.input_payload_json["resolved_input"]["transcription"]
        assert {
            key: value for key, value in payload.items() if key != "source"
        } == transcribed.to_metadata()


@pytest.mark.parametrize("published", [False, True])
async def test_worker_cancellation_preserves_committed_transcript_source(
    source_scenario, published
):
    from eneo.database.database import sessionmanager

    session, scenario, user = source_scenario
    executor, run, step, result, source = await _publication_case(
        session, scenario, user
    )
    if published:
        await _publish(executor, run, step, result, "activation")
    await executor._handle_cancelled_step(
        run_id=run.id, tenant_id=run.tenant_id, step=step, attempt_no=1, state=None
    )
    async with sessionmanager.session() as fresh, fresh.begin():
        state = await _read(fresh, scenario, user)
        if published:
            assert state.status == "present"
            assert state.source == source
        else:
            assert state.status == "unavailable_pre_row"


async def test_word_write_rollback_preserves_prior_words_and_source(
    source_scenario, monkeypatch
):
    from eneo.database.database import sessionmanager
    from eneo.flows.infrastructure.flow_transcript_words_repo import (
        FlowTranscriptWordsRepository,
    )

    preparation = transcription.TranscriptSourcePreparation(
        files_count=1,
        segments=SEGMENTS,
        words=[{"segment_index": 0, "words": [{"word": "Vi", "start": 0, "end": 1}]}],
    )
    session, scenario, user = source_scenario
    executor, run, step, result, _ = await _publication_case(
        session, scenario, user, preparation
    )
    original = FlowTranscriptWordsRepository.upsert

    async def interrupted(self, **kwargs):
        await original(self, **kwargs)
        raise RuntimeError("word publication interrupted")

    monkeypatch.setattr(FlowTranscriptWordsRepository, "upsert", interrupted)
    with pytest.raises(RuntimeError, match="word publication interrupted"):
        await _publish(executor, run, step, result, "activation")
    await session.rollback()
    async with sessionmanager.session() as fresh, fresh.begin():
        assert (await _read(fresh, scenario, user)).status == "unavailable_pre_row"
        words = await FlowTranscriptWordsRepository(session=fresh).get_for_step(
            run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id
        )
        assert words.segments_hash == "a" * 64
        assert words.words_json[0]["words"][0]["word"] == "Prior"


@pytest.mark.parametrize("mode", ["summarize", "process_each_section"])
async def test_inline_transcript_sections_persist_identity_after_reload(
    source_scenario, mode
):
    from dataclasses import replace

    from eneo.flows.domain.flow import FlowStepResultStatus
    from eneo.flows.domain.step_output import InlineTranscript, inline_transcript
    from eneo.flows.domain.text_processing import SectionManifest
    from eneo.flows.flow_run_input_envelope import FlowRunInputEnvelopePatch
    from eneo.flows.flow_run_provenance import parse_attempt_provenance
    from eneo.flows.runtime.step_execution_runtime import build_output_payload
    from eneo.flows.runtime.step_result_builder import build_completed_step_result
    from tests.unittests.flows.test_text_sections import _case

    session, scenario, user = source_scenario
    repo = FlowRunRepository(session)
    text = "A short inline meeting transcript."
    transcript = inline_transcript(
        text=text,
        source_step_id=scenario.transcription_step_id,
        source_attempt_no=1,
    )
    for order, step_id in enumerate(
        (scenario.transcription_step_id, scenario.plain_step_id), 1
    ):
        await repo.create_or_get_attempt_started(
            run_id=scenario.flow_run_id,
            flow_id=scenario.flow_id,
            tenant_id=scenario.tenant_id,
            step_id=step_id,
            step_order=order,
            attempt_no=1,
            dispatch_task_id="inline-material-test",
        )
    producer = await repo.get_step_result(
        run_id=scenario.flow_run_id,
        tenant_id=scenario.tenant_id,
        step_id=scenario.transcription_step_id,
    )
    producer = producer.model_copy(
        update={
            "status": FlowStepResultStatus.COMPLETED,
            "current_attempt_no": 1,
            "output_payload_json": {
                "text": text,
                "text_source_selector": transcript.reference.selector.model_dump(
                    mode="json"
                ),
            },
        }
    )
    await repo.save_step_result(
        scenario.flow_run_id, producer, scenario.tenant_id, attempt_no=1
    )
    await repo.update_input_payload(
        run_id=scenario.flow_run_id,
        tenant_id=scenario.tenant_id,
        input_payload_patch=FlowRunInputEnvelopePatch.transcription(
            transcript=transcript
        ),
    )
    await session.commit()
    run = await repo.get(run_id=scenario.flow_run_id, tenant_id=scenario.tenant_id)
    assert (
        InlineTranscript.model_validate(run.input_payload_json["transkribering"])
        == transcript
    )
    executor, _, assistant, _, state, step, _, _, questions, _ = _case(
        user,
        text=text,
        inline=True,
        prompt="Read {{transkribering}}",
    )
    state.prior_results = [producer]
    state.completed_by_order = {1: producer}
    step = replace(
        step,
        step_id=scenario.plain_step_id,
        input_config={"text_processing": {"mode": mode}},
    )
    executor.flow_run_repo = repo
    executor.session = session
    await session.commit()
    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    assert questions == [text]
    assert assistant.get_response.await_count == 1
    claimed = await repo.get_step_result(
        run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id
    )
    step = replace(step, assistant_id=claimed.assistant_id)
    completed = build_completed_step_result(
        claimed=claimed,
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step=step,
        output=result.output,
        output_payload_json=build_output_payload(result.output),
        execution_hash="inline-material-test",
    )
    await repo.save_step_result(run.id, completed, run.tenant_id, attempt_no=1)
    await session.commit()
    stored = await repo.get_step_result(
        run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id
    )
    manifest = SectionManifest.model_validate(
        stored.output_payload_json["section_manifest"]
    )
    assert manifest.sources == (transcript.reference,)
    attempt = await repo.get_step_attempt(
        run_id=run.id, tenant_id=run.tenant_id, step_id=step.step_id, attempt_no=1
    )
    aliases = attempt.input_payload_json["execution_inputs"][0]["material_aliases"]
    assert aliases == [transcript.reference.model_dump(mode="json")]
    if mode == "summarize":
        provenance = parse_attempt_provenance(attempt.provenance_json).provenance
        assert provenance.summarization.sources == (transcript.reference,)
        assert provenance.summarization.rounds == 0
        assert len(provenance.summarization.records) == 1


async def _authorized_run(session, scenario, user):
    runs = FlowRunRepository(session=session)
    return await FlowRunAccessPolicy(
        user=user, flow_repo=FlowRepository(session=session), flow_run_repo=runs
    ).load_run_status(
        run_id=scenario.flow_run_id, flow_id=scenario.flow_id, access_kind="content"
    )


async def _page(session, scenario, user, start, attempt_no=1):
    return await _service(session, user).get_page_for_attempt(
        run=await _authorized_run(session, scenario, user),
        step_id=scenario.transcription_step_id,
        attempt_no=attempt_no,
        start=start,
        limit=200,
    )


async def _store(session, scenario, user, segments, speaker_review=None):
    source = transcription.capture_transcript_source(
        segments=segments,
        speaker_review=speaker_review,
        words=[],
        words_omitted_reason=None,
    )
    reference = _reference(scenario, source)
    await _attempt(session, scenario, reference)
    await FlowTranscriptSourceRepository(session=session).insert(
        tenant_id=user.tenant_id,
        flow_id=scenario.flow_id,
        reference=reference,
        source=source,
    )
    return source


def _lines(count):
    return [{**SEGMENTS[index % 2], "text": f"{index}: rad"} for index in range(count)]


@pytest.mark.parametrize("total", [1, 400, 401])
async def test_page_reads_return_absolute_slices_of_the_whole_source(
    source_scenario, total
):
    session, scenario, user = source_scenario
    review = {"files": [{"file_index": 0, "overlaps": [{"id": "x:overlap_0000"}]}]}
    source = await _store(session, scenario, user, _lines(total), review)
    assert source.segments is not None

    for start in (0, 1, 199, 200, 399, 400, 401, 2**31 - 1, 2**31, 10**18):
        state = await _page(session, scenario, user, start)
        assert state.status == "present"
        assert state.component_omissions.detail is None
        assert state.component_omissions.words is None
        page = state.page
        assert page.start == start
        assert page.total == total
        assert page.segments == source.segments[start : start + 200]
        assert page.source_hash == source.source_hash
        assert page.bounds == source.bounds
        assert page.speaker_review == (review if start == 0 else None)


async def test_page_reads_match_python_slices_of_the_stored_source(source_scenario):
    import random

    session, scenario, user = source_scenario
    rng = random.Random(4)
    segments = [
        {
            "file_index": rng.randint(0, 2),
            "start": index * 1.5,
            "end": index * 1.5 + rng.random(),
            "speaker": rng.choice(["SPEAKER_00", "SPEAKER_01", None]),
            "text": "å" * rng.randint(0, 40),
            **({"overlap_ids": [f"x:overlap_{index}"]} if rng.random() < 0.1 else {}),
            **({"speaker_attribution": None} if rng.random() < 0.1 else {}),
        }
        for index in range(1_000)
    ]
    await _store(session, scenario, user, segments, {"files": []})
    whole = await _read(session, scenario, user)
    assert whole.status == "present"
    stored = whole.source.segments
    assert stored is not None

    starts = [0, 1, 199, 200, 800, 999, 1_000, 1_001, 5_000]
    starts += [rng.randint(0, 1_100) for _ in range(20)]
    for start in starts:
        state = await _page(session, scenario, user, start)
        assert state.status == "present"
        assert state.page.segments == stored[start : start + 200], start
        assert state.page.total == len(stored)
        assert state.page.speaker_review == (
            whole.source.speaker_review if start == 0 else None
        )


@pytest.mark.parametrize(
    "state",
    [
        "pre_row",
        "omitted",
        "missing_attempt",
        "missing_row",
        "hash",
        "bounds",
        "foreign",
        "null",
        "malformed",
        "omitted_nonempty",
        "present_without_segments",
        "not_a_list",
        "json_null_omitted",
        "json_null_present",
        "non_object_past_page",
    ],
)
async def test_page_reads_refuse_and_degrade_like_whole_source_reads(
    source_scenario, state
):
    from pydantic import ValidationError

    from eneo.database.tables.flow_tables import FlowStepTranscriptSources
    from eneo.flows.domain.transcript_source import TranscriptSourceBounds
    from eneo.main.exceptions import NotFoundException

    def refusal(exc):
        """A refusal's type and what it says, whichever model raised it."""
        if isinstance(exc, ValidationError):
            return type(exc), [(e["type"], e["loc"], e["msg"]) for e in exc.errors()]
        return type(exc), str(exc)

    session, scenario, user = source_scenario
    source = transcription.capture_transcript_source(
        segments=[] if state == "omitted" else SEGMENTS,
        speaker_review=None,
        words=[],
        words_omitted_reason=None,
    )
    reference = _reference(scenario, source)
    stored_segments = {
        "omitted_nonempty": SEGMENTS,
        "present_without_segments": [],
        "not_a_list": SEGMENTS[0],
        "json_null_omitted": sa.JSON.NULL,
        "json_null_present": sa.JSON.NULL,
        "non_object_past_page": [*_lines(230), "not a line", *_lines(20)],
    }
    if state in stored_segments:
        # Rows the ORM cannot write. Each read refuses them as the whole read
        # does; only JSON null marked omitted reads as an omitted source.
        bounds = TranscriptSourceBounds.model_validate(
            {
                **source.bounds.model_dump(),
                "segments_omitted_reason": (
                    TranscriptSourceOmissionReason.TOO_LARGE
                    if state in ("omitted_nonempty", "json_null_omitted")
                    else None
                ),
            }
        )
        reference = reference.model_copy(update={"bounds": bounds})
        await session.execute(
            sa.insert(FlowStepTranscriptSources).values(
                tenant_id=user.tenant_id,
                flow_id=scenario.flow_id,
                flow_run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                attempt_no=1,
                source_hash=source.source_hash,
                segments_json=stored_segments[state],
                detail_json=None,
                **bounds.model_dump(mode="json"),
            )
        )
    elif state not in ("pre_row", "missing_attempt", "missing_row"):
        await FlowTranscriptSourceRepository(session=session).insert(
            tenant_id=user.tenant_id,
            flow_id=scenario.flow_id,
            reference=reference,
            source=source,
        )
    if state != "missing_attempt":
        await _attempt(session, scenario, None if state == "pre_row" else reference)
    marker = reference.model_dump(mode="json")
    if state == "hash":
        marker["source_hash"] = "b" * 64
    elif state == "bounds":
        marker["bounds"]["segments_count"] += 1
    elif state == "foreign":
        marker["attempt_no"] = 2
    elif state == "null":
        marker = None
    elif state == "malformed":
        marker = {"version": 1, "run_id": "not-a-run"}
    if state in ("hash", "bounds", "foreign", "null", "malformed"):
        await session.execute(
            sa.update(FlowStepAttempts)
            .where(FlowStepAttempts.flow_run_id == scenario.flow_run_id)
            .values(
                input_payload_json={
                    "schema_version": "flow-step-attempt-input.v1",
                    "resolved_input": {"transcription": {"source": marker}},
                }
            )
        )

    outcomes = []
    for read in (_read(session, scenario, user), _page(session, scenario, user, 0)):
        try:
            outcomes.append(await read)
        except Exception as exc:
            outcomes.append(exc)
    whole, page = outcomes
    if state == "pre_row":
        assert whole.status == page.status == "unavailable_pre_row"
    elif state in ("omitted", "json_null_omitted"):
        assert whole.status == page.status == "omitted"
        assert (
            page.reason
            == whole.reason
            == (
                TranscriptSourceOmissionReason.NO_SEGMENTS
                if state == "omitted"
                else TranscriptSourceOmissionReason.TOO_LARGE
            )
        )
        assert page.bounds == whole.bounds == reference.bounds
    else:
        expected = {
            "missing_attempt": NotFoundException,
            "missing_row": MissingTranscriptSourceError,
            "hash": ValueError,
            "bounds": ValueError,
            "foreign": ValueError,
        }.get(state, ValidationError)
        assert type(whole) is expected, whole
        assert refusal(page) == refusal(whole), (page, whole)


async def test_detail_route_reads_one_page_after_one_status_authorization(
    source_scenario, client, db_container, patch_auth_service_jwt
):
    import re

    from eneo.audit.domain.action_types import ActionType
    from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
    from eneo.database.tables.flow_tables import FlowRuns, FlowStepResults
    from eneo.database.tables.spaces_table import SpacesUsers
    from eneo.spaces.api.space_models import SpaceRoleValue

    session, scenario, user = source_scenario
    await _store(session, scenario, user, _lines(450), {"files": []})
    await session.execute(
        sa.update(FlowStepAttempts)
        .where(FlowStepAttempts.flow_run_id == scenario.flow_run_id)
        .values(output_payload_json={"text": "Protected transcript " * 500})
    )
    await session.execute(
        sa.update(FlowRuns)
        .where(FlowRuns.id == scenario.flow_run_id)
        .values(output_payload_json={"text": "Protected transcript " * 500})
    )
    await session.execute(
        sa.update(FlowStepResults)
        .where(FlowStepResults.flow_run_id == scenario.flow_run_id)
        .values(input_payload_json={})
    )
    flow = await FlowRepository(session=session).get(scenario.flow_id, user.tenant_id)
    session.add(
        SpacesUsers(space_id=flow.space_id, user_id=user.id, role=SpaceRoleValue.EDITOR)
    )
    await session.commit()
    async with db_container() as container:
        token = container.auth_service().create_access_token_for_user(user)
    path = (
        f"/api/v1/flows/{scenario.flow_id}/runs/{scenario.flow_run_id}"
        f"/steps/{scenario.transcription_step_id}/attempts/1/transcript-source/"
    )
    bind = session.sync_session.bind
    assert bind is not None
    pages = []
    start = 0
    while start is not None:
        with capture_queries(bind) as queries:
            response = await client.get(
                path,
                headers={"Authorization": f"Bearer {token}"},
                params={"start_segment_index": start},
            )
        assert response.status_code == 200, response.text
        runs = [q.sql for q in queries if re.search(r"\bFROM flow_runs\b", q.sql)]
        assert len(runs) == 1, runs
        assert "input_payload_json" not in runs[0]
        assert "output_payload_json" not in runs[0]
        reads = [
            q.sql
            for q in queries
            if "flow_step_attempts" in q.sql or "flow_step_transcript_sources" in q.sql
        ]
        assert len(reads) == 1, reads
        assert "output_payload_json" not in reads[0]
        assert "jsonb_path_query_array" in reads[0]
        assert ("detail_json" in reads[0]) == (start == 0)
        pages.append(response.json())
        start = response.json()["next_segment_index"]

    assert [page["start_segment_index"] for page in pages] == [0, 200, 400]
    assert [len(page["segments"]) for page in pages] == [200, 200, 50]
    assert [segment["segment_index"] for segment in pages[2]["segments"]] == list(
        range(400, 450)
    )
    async with db_container() as container:
        audits = (
            await container.session().execute(
                sa.select(AuditLogTable.description, AuditLogTable.log_metadata)
                .where(
                    AuditLogTable.action == ActionType.FLOW_EVIDENCE_VIEWED.value,
                    AuditLogTable.entity_id == scenario.flow_run_id,
                )
                .order_by(AuditLogTable.timestamp)
            )
        ).all()
    assert len(audits) == len(pages)
    for audit in audits:
        assert audit.description == (
            f"Viewed transcript source for flow run {scenario.flow_run_id}"
        )
        assert audit.log_metadata["target"] == {
            "id": str(scenario.flow_run_id),
            "name": None,
        }
        assert audit.log_metadata["extra"] == {
            "evidence_detail": "transcript_source",
            "step_id": str(scenario.transcription_step_id),
            "attempt_no": 1,
            "flow_id": str(scenario.flow_id),
            "run_id": str(scenario.flow_run_id),
        }


@pytest.mark.parametrize("route", ["transcript-source", "transcript-words"])
@pytest.mark.parametrize("caller", ["not_the_owner", "missing_run"])
async def test_transcript_routes_refuse_before_reading_content(
    source_scenario, client, db_container, patch_auth_service_jwt, route, caller
):
    import re

    from eneo.audit.domain.action_types import ActionType
    from eneo.database.tables.audit_log_table import AuditLog as AuditLogTable
    from eneo.database.tables.spaces_table import SpacesUsers
    from eneo.flows.domain.transcript_corrections import segments_content_hash
    from eneo.flows.infrastructure.flow_transcript_words_repo import (
        FlowTranscriptWordsRepository,
    )
    from eneo.roles.permissions import Permission
    from eneo.spaces.api.space_models import SpaceRoleValue
    from tests.integration.flows.test_flow_evidence_api_contracts import (
        _create_user_with_flow_permissions_and_token,
    )

    session, scenario, user = source_scenario
    await _store(session, scenario, user, _lines(3))
    await FlowTranscriptWordsRepository(session=session).upsert(
        tenant_id=user.tenant_id,
        flow_id=scenario.flow_id,
        run_id=scenario.flow_run_id,
        step_id=scenario.transcription_step_id,
        segments_hash=segments_content_hash(_lines(3)),
        alignment="forced",
        words_json=[{"segment_index": 0, "words": []}],
    )
    await session.commit()
    if caller == "not_the_owner":
        caller_user, token = await _create_user_with_flow_permissions_and_token(
            db_container=db_container,
            tenant_id=user.tenant_id,
            role_name_prefix="Transcript reader",
            permissions=[Permission.FLOWS_VIEW, Permission.FLOWS_TRACE],
        )
        flow = await FlowRepository(session=session).get(
            scenario.flow_id, user.tenant_id
        )
        session.add(
            SpacesUsers(
                space_id=flow.space_id,
                user_id=caller_user.id,
                role=SpaceRoleValue.EDITOR,
            )
        )
        await session.commit()
        run_id = scenario.flow_run_id
    else:
        flow = await FlowRepository(session=session).get(
            scenario.flow_id, user.tenant_id
        )
        session.add(
            SpacesUsers(
                space_id=flow.space_id, user_id=user.id, role=SpaceRoleValue.EDITOR
            )
        )
        await session.commit()
        async with db_container() as container:
            token = container.auth_service().create_access_token_for_user(user)
        run_id = uuid4()
    suffix = (
        "attempts/1/transcript-source/"
        if route == "transcript-source"
        else "transcript-words/"
    )
    bind = session.sync_session.bind
    assert bind is not None
    with capture_queries(bind) as queries:
        response = await client.get(
            f"/api/v1/flows/{scenario.flow_id}/runs/{run_id}"
            f"/steps/{scenario.transcription_step_id}/{suffix}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == (403 if caller == "not_the_owner" else 404)
    assert not [
        q.sql
        for q in queries
        if re.search(
            r"flow_step_attempts|flow_step_transcript_sources|"
            r"flow_step_transcript_words|flow_step_results",
            q.sql,
        )
    ]
    async with db_container() as container:
        assert not (
            await container.session().scalars(
                sa.select(AuditLogTable.id).where(
                    AuditLogTable.action == ActionType.FLOW_EVIDENCE_VIEWED.value
                )
            )
        ).all()
