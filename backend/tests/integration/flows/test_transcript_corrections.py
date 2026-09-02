from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.database.tables.flow_tables import FlowStepResults
from eneo.flows import FlowRepository, FlowVersionRepository
from eneo.flows.application.flow_run_access_policy import FlowRunAccessPolicy
from eneo.flows.application.flow_transcript_corrections_service import (
    FlowTranscriptCorrectionsService,
)
from eneo.flows.domain.flow import Flow, FlowStep
from eneo.flows.domain.transcript_corrections import (
    TranscriptCorrectionOccurrence,
    TranscriptSpeakerEdit,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.infrastructure.flow_run_repo import FlowRunRepository
from eneo.flows.infrastructure.flow_transcript_corrections_repo import (
    FlowTranscriptCorrectionsRepository,
)

SEGMENTS = [
    {
        "file_index": 1,
        "start": 0.0,
        "end": 4.0,
        "speaker": "SPEAKER_00",
        "text": "Vi frågade sugary om planen.",
    },
    {
        "file_index": 1,
        "start": 4.0,
        "end": 8.0,
        "speaker": "SPEAKER_01",
        "text": "sugary svarade direkt.",
    },
]


@dataclass(frozen=True, slots=True)
class TranscriptCorrectionsScenario:
    tenant_id: UUID
    flow_id: UUID
    flow_run_id: UUID
    transcription_step_id: UUID
    plain_step_id: UUID


def _build_flow(
    *,
    tenant_id: UUID,
    space_id: UUID,
    user_id: UUID,
    assistant_id: UUID,
) -> Flow:
    return Flow(
        id=None,
        tenant_id=tenant_id,
        space_id=space_id,
        name=f"Transcript corrections flow {uuid4()}",
        description="Flow used for transcript corrections tests.",
        created_by_user_id=user_id,
        owner_user_id=user_id,
        published_version=None,
        metadata_json=None,
        data_retention_days=30,
        created_at=None,
        updated_at=None,
        steps=[
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=1,
                user_description="Transcribe the meeting",
                input_source="flow_input",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings={"question": "{{flow.input.question}}"},
                output_classification_override=None,
                input_config=None,
                output_config=None,
            ),
            FlowStep(
                id=None,
                flow_id=uuid4(),
                tenant_id=tenant_id,
                assistant_id=assistant_id,
                step_order=2,
                user_description="Summarize the transcript",
                input_source="previous_step",
                input_type="text",
                input_contract=None,
                output_mode="pass_through",
                output_type="text",
                output_contract=None,
                input_bindings=None,
                output_classification_override=None,
                input_config=None,
                output_config=None,
            ),
        ],
    )


def _require_uuid(value: UUID | None) -> UUID:
    assert value is not None
    return value


async def _create_scenario(
    *,
    session,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
) -> TranscriptCorrectionsScenario:
    model = await completion_model_factory(session, "gpt-4o-mini")
    space = await space_factory(
        session,
        f"Transcript corrections space {uuid4()}",
        [model.id],
    )
    assistant = await assistant_factory(
        session,
        f"Transcript corrections assistant {uuid4()}",
        model.id,
        space_id=space.id,
    )

    flow_repo = FlowRepository(session=session)
    flow = await flow_repo.create(
        flow=_build_flow(
            tenant_id=admin_user.tenant_id,
            space_id=space.id,
            user_id=admin_user.id,
            assistant_id=assistant.id,
        ),
        tenant_id=admin_user.tenant_id,
    )
    first_step, second_step = flow.steps
    version_repo = FlowVersionRepository(session=session)
    await version_repo.create(
        flow_id=_require_uuid(flow.id),
        version=1,
        definition_json={
            "steps": [
                {
                    "step_id": str(_require_uuid(first_step.id)),
                    "assistant_id": str(first_step.assistant_id),
                    "step_order": 1,
                },
                {
                    "step_id": str(_require_uuid(second_step.id)),
                    "assistant_id": str(second_step.assistant_id),
                    "step_order": 2,
                },
            ]
        },
        tenant_id=admin_user.tenant_id,
    )
    flow = await flow_repo.update(
        flow=flow.model_copy(update={"published_version": 1}),
        tenant_id=admin_user.tenant_id,
    )

    run_repo = FlowRunRepository(session=session)
    run = await run_repo.create(
        flow_id=_require_uuid(flow.id),
        flow_version=1,
        principal_user_id=admin_user.id,
        tenant_id=admin_user.tenant_id,
        input_payload_json={"question": "Transkribera mötet"},
        preseed_steps=[
            {
                "step_id": _require_uuid(first_step.id),
                "assistant_id": first_step.assistant_id,
                "step_order": 1,
            },
            {
                "step_id": _require_uuid(second_step.id),
                "assistant_id": second_step.assistant_id,
                "step_order": 2,
            },
        ],
    )
    await _store_segments(
        session=session,
        run_id=run.id,
        step_id=_require_uuid(first_step.id),
        segments=SEGMENTS,
    )
    return TranscriptCorrectionsScenario(
        tenant_id=admin_user.tenant_id,
        flow_id=_require_uuid(flow.id),
        flow_run_id=run.id,
        transcription_step_id=_require_uuid(first_step.id),
        plain_step_id=_require_uuid(second_step.id),
    )


async def _store_segments(
    *,
    session,
    run_id: UUID,
    step_id: UUID,
    segments: list[dict],
) -> None:
    await session.execute(
        sa.update(FlowStepResults)
        .where(FlowStepResults.flow_run_id == run_id)
        .where(FlowStepResults.step_id == step_id)
        .values(input_payload_json={"transcription": {"segments": segments}})
    )


def _service(*, session, admin_user) -> FlowTranscriptCorrectionsService:
    flow_run_repo = FlowRunRepository(session=session)
    return FlowTranscriptCorrectionsService(
        user=admin_user,
        transcript_corrections_repo=FlowTranscriptCorrectionsRepository(
            session=session
        ),
        access_policy=FlowRunAccessPolicy(
            user=admin_user,
            flow_repo=FlowRepository(session=session),
            flow_run_repo=flow_run_repo,
        ),
        flow_run_repo=flow_run_repo,
    )


def _occurrence(
    *,
    segment_index: int = 0,
    char_start: int = 11,
    char_end: int = 17,
    original: str = "sugary",
    corrected: str = "Çagri",
) -> TranscriptCorrectionOccurrence:
    return TranscriptCorrectionOccurrence(
        segment_index=segment_index,
        char_start=char_start,
        char_end=char_end,
        original=original,
        corrected=corrected,
    )


def _speaker_edit(
    *,
    segment_index: int = 1,
    char_start: int | None = None,
    char_end: int | None = None,
    original: str | None = None,
    original_speaker: str = "SPEAKER_01",
    speaker: str = "SPEAKER_00",
) -> TranscriptSpeakerEdit:
    return TranscriptSpeakerEdit(
        segment_index=segment_index,
        char_start=char_start,
        char_end=char_end,
        original=original,
        original_speaker=original_speaker,
        speaker=speaker,
    )


async def test_save_and_list_round_trip(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)

        saved = await service.save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            expected_revision=None,
            occurrences=[
                _occurrence(segment_index=1, char_start=0),
                _occurrence(),
            ],
        )

        assert saved.corrections.revision == 1
        assert saved.stale is False
        # Canonical order: (segment_index, char_start), regardless of input order.
        assert [
            item["segment_index"] for item in saved.corrections.occurrences_json
        ] == [0, 1]

        views = await service.list_for_run(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
        )
        assert len(views) == 1
        assert views[0].corrections.step_id == scenario.transcription_step_id
        assert views[0].stale is False


async def test_revision_compare_and_swap(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)
        saved = await service.save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            expected_revision=None,
            occurrences=[_occurrence()],
        )

        # Creating again without a revision conflicts with the existing row.
        with pytest.raises(FlowBadRequestException) as create_conflict:
            await service.save(
                flow_id=scenario.flow_id,
                run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                expected_revision=None,
                occurrences=[],
            )
        assert (
            create_conflict.value.code
            == FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_STALE_REVISION
        )

        # A wrong revision is rejected and reports the current one.
        with pytest.raises(FlowBadRequestException) as stale:
            await service.save(
                flow_id=scenario.flow_id,
                run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                expected_revision=99,
                occurrences=[],
            )
        assert stale.value.code == (
            FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_STALE_REVISION
        )

        # The correct revision replaces the list; an empty list clears it.
        cleared = await service.save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            expected_revision=saved.corrections.revision,
            occurrences=[],
        )
        assert cleared.corrections.revision == saved.corrections.revision + 1
        assert cleared.corrections.occurrences_json == []


async def test_save_rejects_mismatched_anchor(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)

        with pytest.raises(FlowBadRequestException) as excinfo:
            await service.save(
                flow_id=scenario.flow_id,
                run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                expected_revision=None,
                occurrences=[_occurrence(original="sockry")],
            )
        assert excinfo.value.code == (
            FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_OCCURRENCE
        )


async def test_save_rejects_step_without_segments(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)

        with pytest.raises(FlowBadRequestException) as excinfo:
            await service.save(
                flow_id=scenario.flow_id,
                run_id=scenario.flow_run_id,
                step_id=scenario.plain_step_id,
                expected_revision=None,
                occurrences=[_occurrence()],
            )
        assert excinfo.value.code == (
            FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_SEGMENTS_UNAVAILABLE
        )


async def test_list_flags_stale_after_segments_change(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)
        await service.save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            expected_revision=None,
            occurrences=[_occurrence()],
        )

        rewritten = [dict(SEGMENTS[0], text="Helt ny transkribering.")]
        await _store_segments(
            session=session,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            segments=rewritten,
        )

        views = await service.list_for_run(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
        )
        assert len(views) == 1
        assert views[0].stale is True


async def test_repo_filters_by_tenant(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)
        await service.save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            expected_revision=None,
            occurrences=[_occurrence()],
        )
        repo = FlowTranscriptCorrectionsRepository(session=session)

        same_tenant = await repo.get_for_step(
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            tenant_id=scenario.tenant_id,
        )
        assert same_tenant is not None

        other_tenant = await repo.get_for_step(
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            tenant_id=uuid4(),
        )
        assert other_tenant is None
        assert (
            await repo.list_for_run(
                run_id=scenario.flow_run_id,
                tenant_id=uuid4(),
            )
            == []
        )


async def test_save_and_list_round_trip_with_speaker_edits(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)

        saved = await service.save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            expected_revision=None,
            occurrences=[_occurrence()],
            speaker_edits=[
                _speaker_edit(
                    segment_index=1,
                    char_start=0,
                    char_end=6,
                    original="sugary",
                    original_speaker="SPEAKER_01",
                    speaker="SPEAKER_02",
                ),
                _speaker_edit(
                    segment_index=0,
                    original_speaker="SPEAKER_00",
                    speaker="SPEAKER_03",
                ),
            ],
        )

        assert saved.corrections.schema_version == 2
        # Canonical order: by segment, whole-segment edits before spans.
        assert [
            (item["segment_index"], item["char_start"])
            for item in saved.corrections.speaker_edits_json
        ] == [(0, None), (1, 0)]

        views = await service.list_for_run(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
        )
        assert len(views) == 1
        assert views[0].corrections.speaker_edits() == saved.corrections.speaker_edits()
        assert views[0].stale is False


async def test_save_rejects_invalid_speaker_edit(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)

        with pytest.raises(FlowBadRequestException) as excinfo:
            await service.save(
                flow_id=scenario.flow_id,
                run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                expected_revision=None,
                occurrences=[],
                # A no-op edit: the segment already belongs to this speaker.
                speaker_edits=[_speaker_edit(speaker="SPEAKER_01")],
            )
        assert excinfo.value.code == (
            FlowApiErrorCode.TRANSCRIPT_CORRECTIONS_INVALID_SPEAKER_EDIT
        )


async def test_speaker_change_in_segments_flags_stale(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)
        await service.save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            expected_revision=None,
            occurrences=[],
            speaker_edits=[_speaker_edit()],
        )

        # Same text, different diarization label: anchors are invalid.
        relabelled = [dict(SEGMENTS[0]), dict(SEGMENTS[1], speaker="SPEAKER_02")]
        await _store_segments(
            session=session,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            segments=relabelled,
        )

        views = await service.list_for_run(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
        )
        assert len(views) == 1
        assert views[0].stale is True


async def test_revision_cas_replaces_speaker_edits(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        service = _service(session=session, admin_user=admin_user)
        saved = await service.save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            expected_revision=None,
            occurrences=[],
            speaker_edits=[_speaker_edit()],
        )
        assert saved.corrections.speaker_edits_json != []

        cleared = await service.save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            expected_revision=saved.corrections.revision,
            occurrences=[],
            speaker_edits=[],
        )
        assert cleared.corrections.revision == saved.corrections.revision + 1
        assert cleared.corrections.speaker_edits_json == []
