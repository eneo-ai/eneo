from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from eneo.authentication.principal_types import PrincipalType
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
from eneo.flows.principal import FlowPrincipal
from tests.integration.flows.test_flow_run_listing_and_evidence_measurement import (
    _capture_queries,
)
from tests.integration.flows.test_flow_run_review_checkpoint_repository import (
    _create_service_principal_id,
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
    runtime_assistant: object | None = None


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
    runtime_definition: bool = False,
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
    runtime_assistant = None
    assistant_snapshot = None
    if runtime_definition:
        from types import SimpleNamespace

        from eneo.ai_models.completion_models.completion_model import ModelKwargs
        from eneo.completion_models.domain.model_kwargs_capabilities import (
            SupportedModelKwargs,
        )
        from eneo.flows.assistant_execution_snapshot import (
            build_assistant_execution_snapshot,
        )

        runtime_assistant = SimpleNamespace(
            id=assistant.id,
            origin="flow_managed",
            get_prompt_text=lambda: "Summarize the reviewed text.",
            has_knowledge=lambda: False,
            completion_model=SimpleNamespace(
                id=model.id,
                name="gpt-4o-mini",
                nickname="gpt-4o-mini",
                litellm_model_name="gpt-4o-mini",
                provider_type="openai",
                supported_model_kwargs=SupportedModelKwargs(),
            ),
            completion_model_kwargs=ModelKwargs(temperature=0.2),
            collections=[],
            websites=[],
            integration_knowledge_list=[],
            mcp_servers=[],
        )
        assistant_snapshot = build_assistant_execution_snapshot(
            assistant=runtime_assistant
        )
    version_repo = FlowVersionRepository(session=session)
    await version_repo.create(
        flow_id=_require_uuid(flow.id),
        version=1,
        definition_json={
            **(
                {
                    "schema_version": 1,
                    "flow_id": str(flow.id),
                    "name": flow.name,
                    "description": flow.description,
                    "metadata_json": flow.metadata_json,
                }
                if runtime_definition
                else {}
            ),
            "steps": [
                {
                    "step_id": str(_require_uuid(first_step.id)),
                    "assistant_id": str(first_step.assistant_id),
                    "step_order": 1,
                    **(
                        {"assistant_snapshot": assistant_snapshot}
                        if runtime_definition
                        else {}
                    ),
                    **(
                        {
                            "input_source": "flow_input",
                            "input_type": "text",
                            "output_mode": "pass_through",
                            "output_type": "text",
                            "input_bindings": {"question": "{{flow_input.question}}"},
                        }
                        if runtime_definition
                        else {}
                    ),
                },
                {
                    "step_id": str(_require_uuid(second_step.id)),
                    "assistant_id": str(second_step.assistant_id),
                    "step_order": 2,
                    **(
                        {"assistant_snapshot": assistant_snapshot}
                        if runtime_definition
                        else {}
                    ),
                    **(
                        {
                            "input_source": "previous_step",
                            "input_type": "text",
                            "output_mode": "pass_through",
                            "output_type": "text",
                        }
                        if runtime_definition
                        else {}
                    ),
                },
            ],
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
        runtime_assistant=runtime_assistant,
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
    from eneo.audit.application.audit_service import AuditService
    from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

    flow_run_repo = FlowRunRepository(session=session)
    return FlowTranscriptCorrectionsService(
        audit_service=AuditService(AuditLogRepositoryImpl(session)),
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
                _occurrence(segment_index=1, char_start=0, char_end=6),
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


async def test_saves_and_revert_preserve_correction_revisions(
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
        repo = FlowTranscriptCorrectionsRepository(session=session)
        principal = FlowPrincipal.from_user(admin_user)
        service_id = await _create_service_principal_id(
            session=session,
            tenant_id=scenario.tenant_id,
            created_by_user_id=admin_user.id,
        )
        service_principal = FlowPrincipal(
            principal_type=PrincipalType.SERVICE_KEY, principal_service_id=service_id
        )
        saved = None
        contents = [
            [_occurrence(corrected="Çagri").as_json()],
            [_occurrence(corrected="Cagri").as_json()],
            [],
        ]
        for index, occurrences in enumerate(contents):
            saved = await repo.save(
                tenant_id=scenario.tenant_id,
                flow_id=scenario.flow_id,
                run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                occurrences_json=occurrences,
                speaker_edits_json=[],
                segments_hash="a" * 64,
                expected_revision=saved.revision if saved else None,
                principal=service_principal if index == 1 else principal,
            )
        revisions = await repo.list_revisions_for_run(
            run_id=scenario.flow_run_id, tenant_id=scenario.tenant_id
        )
        assert [item.revision for item in revisions] == [1, 2, 3]
        assert [item.occurrences_json for item in revisions] == contents
        assert [item.edited_by_user_id for item in revisions] == [
            admin_user.id,
            None,
            admin_user.id,
        ]
        assert [item.edited_by_service_id for item in revisions] == [
            None,
            service_id,
            None,
        ]
        assert saved is not None
        assert {item.correction_set_id for item in revisions} == {saved.id}
        assert (
            len(
                await repo.list_revisions_for_run(
                    run_id=scenario.flow_run_id, tenant_id=scenario.tenant_id, limit=1
                )
            )
            == 1
        )
        assert (
            await repo.list_revisions_for_run(
                run_id=scenario.flow_run_id,
                tenant_id=scenario.tenant_id,
                limit=3,
                logical_byte_budget=0,
            )
            == []
        )
        measurement = await repo.measure_revision_evidence(
            run_id=scenario.flow_run_id, tenant_id=scenario.tenant_id, candidate_limit=2
        )
        assert measurement.row_count == 2
        assert measurement.logical_json_bytes > 0


@pytest.mark.parametrize("baseline", [False, True])
async def test_correction_revision_page_limits_loaded_payload_bytes(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
    baseline,
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
        repo = FlowTranscriptCorrectionsRepository(session=session)
        saved = None
        for occurrences, speakers in (
            ([{"corrected": "small"}], []),
            ([], [{"speaker": "é" * 256}]),
            ([], []),
        ):
            saved = await repo.save(
                tenant_id=scenario.tenant_id,
                flow_id=scenario.flow_id,
                run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                occurrences_json=occurrences,
                speaker_edits_json=speakers,
                segments_hash="a" * 64,
                expected_revision=saved.revision if saved else None,
                principal=FlowPrincipal.from_user(admin_user),
            )
        bind = session.sync_session.bind
        assert bind is not None
        if baseline:
            with _capture_queries(bind) as queries:
                value, obstructing = await repo.get_revision_for_step(
                    run_id=scenario.flow_run_id,
                    step_id=scenario.transcription_step_id,
                    tenant_id=scenario.tenant_id,
                    revision=2,
                    logical_byte_budget=32,
                )
            assert value is None
            assert obstructing == (2, 531)
            assert len(queries) == 1
            assert "octet_length" in queries[0].sql
            with _capture_queries(bind) as queries:
                value, obstructing = await repo.get_revision_for_step(
                    run_id=scenario.flow_run_id,
                    step_id=scenario.transcription_step_id,
                    tenant_id=scenario.tenant_id,
                    revision=2,
                    logical_byte_budget=10_000,
                )
            assert value is not None
            assert value.speaker_edits_json == [{"speaker": "é" * 256}]
            assert obstructing is None
            assert len(queries) == 2
            return
        sizes = {1: 26, 2: 531, 3: 4}
        for after, limit, budget, expected, more, obstruction_revision in (
            (None, 200, 32, [1], True, 2),
            (None, 200, 540, [1], True, 2),
            (None, 200, -1, [], True, 1),
            (None, 1, 10_000, [1], True, None),
            (None, 200, 10_000, [1, 2, 3], False, None),
            (1, 200, 32, [], True, 2),
            (2, 200, 32, [3], False, None),
            (3, 200, 32, [], False, None),
        ):
            with _capture_queries(bind) as queries:
                rows, has_more, obstructing = await repo.list_revisions(
                    run_id=scenario.flow_run_id,
                    step_id=scenario.transcription_step_id,
                    tenant_id=scenario.tenant_id,
                    after_revision=after,
                    limit=limit,
                    logical_byte_budget=budget,
                )
            assert [row.revision for row in rows] == expected
            assert has_more is more
            assert obstructing == (
                (obstruction_revision, sizes[obstruction_revision])
                if obstruction_revision is not None
                else None
            )
            assert len(queries) == (2 if rows else 1)
            assert "octet_length" in queries[0].sql


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


@pytest.mark.migration_isolation
async def test_history_migration_preserves_current_correction_revision(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        repo = FlowTranscriptCorrectionsRepository(session=session)
        saved = None
        for _ in range(2):
            saved = await repo.save(
                tenant_id=scenario.tenant_id,
                flow_id=scenario.flow_id,
                run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                occurrences_json=[_occurrence().as_json()],
                speaker_edits_json=[],
                segments_hash="a" * 64,
                expected_revision=saved.revision if saved else None,
                principal=FlowPrincipal.from_user(admin_user),
            )
        path = (
            Path(__file__).parents[3]
            / "alembic/versions/202609151000_add_review_change_history.py"
        )
        spec = importlib.util.spec_from_file_location("history_migration", path)
        assert spec is not None and spec.loader is not None
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        def cycle(connection):
            with Operations.context(MigrationContext.configure(connection)):
                migration.downgrade()
                assert not sa.inspect(connection).has_table(
                    "flow_transcript_correction_revisions"
                )
                assert not sa.inspect(connection).has_table(
                    "flow_run_review_checkpoint_edits"
                )
                assert "payload_sha256_before" not in {
                    column["name"]
                    for column in sa.inspect(connection).get_columns(
                        "flow_run_audit_outbox"
                    )
                }
                migration.upgrade()

        await (await session.connection()).run_sync(cycle)
        revisions = await repo.list_revisions_for_run(
            run_id=scenario.flow_run_id, tenant_id=scenario.tenant_id
        )
        assert saved is not None
        assert [(item.correction_set_id, item.revision) for item in revisions] == [
            (saved.id, 2)
        ]
        assert revisions[0].occurrences_json == saved.occurrences_json
        assert revisions[0].created_at == saved.updated_at


async def test_v3_decisions_reload_guard_old_writes_and_stale_base(
    db_container,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    from eneo.flows.domain.transcript_corrections import segments_content_hash

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
        base_hash = segments_content_hash(SEGMENTS)
        args = dict(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            occurrences=[],
        )
        saved = await service.save(
            **args,
            expected_revision=None,
            schema_version=3,
            expected_segments_hash=base_hash,
            speaker_edits=[
                TranscriptSpeakerEdit(
                    0, None, None, None, "SPEAKER_00", "SPEAKER_00", "confirmed"
                ),
                TranscriptSpeakerEdit(
                    1, None, None, None, "SPEAKER_01", None, "unresolved"
                ),
            ],
        )
        assert saved.corrections.schema_version == 3
        session.expire_all()
        reloaded = await service.list_for_run(
            flow_id=scenario.flow_id, run_id=scenario.flow_run_id
        )
        assert [edit.decision for edit in reloaded[0].corrections.speaker_edits()] == [
            "confirmed",
            "unresolved",
        ]
        assert reloaded[0].corrections.edited_by_user_id == admin_user.id
        with pytest.raises(FlowBadRequestException):
            await service.save(**args, expected_revision=1, schema_version=2)
        with pytest.raises(FlowBadRequestException):
            await service.save(
                **args,
                expected_revision=1,
                schema_version=3,
                expected_segments_hash="0" * 64,
            )
        with pytest.raises(FlowBadRequestException):
            await service.save(
                **args,
                expected_revision=2,
                schema_version=3,
                expected_segments_hash=base_hash,
            )
        cleared = await service.save(
            **args,
            expected_revision=1,
            schema_version=3,
            expected_segments_hash=base_hash,
            speaker_edits=[],
        )
        assert cleared.corrections.revision == 2
        assert cleared.corrections.speaker_edits_json == []


@pytest.mark.parametrize("audit_failure", [False, True])
async def test_v3_patch_commits_decision_and_audit_before_response(
    client,
    monkeypatch,
    audit_failure,
    db_container,
    patch_auth_service_jwt,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    from eneo.audit.domain.action_types import ActionType
    from eneo.database.tables.audit_log_table import AuditLog
    from eneo.flows.domain.transcript_corrections import segments_content_hash

    async with db_container() as container:
        scenario = await _create_scenario(
            session=container.session(),
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
        )
        from eneo.database.tables.spaces_table import SpacesUsers
        from eneo.spaces.api.space_models import SpaceRoleValue

        flow = await FlowRepository(session=container.session()).get(
            scenario.flow_id, admin_user.tenant_id
        )
        container.session().add(
            SpacesUsers(
                space_id=flow.space_id,
                user_id=admin_user.id,
                role=SpaceRoleValue.EDITOR,
            )
        )
        await container.session().flush()
        token = container.auth_service().create_access_token_for_user(admin_user)
    if audit_failure:
        from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl

        async def unavailable(self, audit_log):
            raise RuntimeError("audit storage unavailable")

        monkeypatch.setattr(AuditLogRepositoryImpl, "create", unavailable)
    response = await client.patch(
        f"/api/v1/flows/{scenario.flow_id}/runs/{scenario.flow_run_id}/steps/{scenario.transcription_step_id}/transcript-corrections/",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "schema_version": 3,
            "segments_hash": segments_content_hash(SEGMENTS),
            "expected_revision": None,
            "occurrences": [],
            "speaker_edits": [
                {
                    "segment_index": 0,
                    "original_speaker": "SPEAKER_00",
                    "speaker": None,
                    "decision": "unresolved",
                }
            ],
        },
    )
    if audit_failure:
        assert response.status_code == 503, response.text
        async with db_container() as container:
            stored = await FlowTranscriptCorrectionsRepository(
                session=container.session()
            ).get_for_step(
                run_id=scenario.flow_run_id,
                step_id=scenario.transcription_step_id,
                tenant_id=admin_user.tenant_id,
            )
            assert stored is None
        return
    assert response.status_code == 200, response.text
    assert response.json()["speaker_edits"][0]["decision"] == "unresolved"
    async with db_container() as container:
        audits = (
            (
                await container.session().execute(
                    sa.select(AuditLog).where(
                        AuditLog.tenant_id == admin_user.tenant_id,
                        AuditLog.entity_id == scenario.flow_run_id,
                        AuditLog.action
                        == ActionType.FLOW_RUN_TRANSCRIPT_CORRECTIONS_EDITED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(audits) == 1
        stored = await FlowTranscriptCorrectionsRepository(
            session=container.session()
        ).get_for_step(
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            tenant_id=admin_user.tenant_id,
        )
        assert stored.schema_version == 3
        assert stored.speaker_edits()[0].decision == "unresolved"


@pytest.mark.parametrize("audit_failure", [False, True])
async def test_regeneration_snapshots_saved_review_and_keeps_original_output(
    client,
    monkeypatch,
    audit_failure,
    db_container,
    patch_auth_service_jwt,
    test_tenant,
    completion_model_factory,
    space_factory,
    assistant_factory,
    admin_user,
):
    from datetime import datetime, timezone
    from unittest.mock import AsyncMock

    from eneo.audit.domain.action_types import ActionType
    from eneo.audit.infrastructure.audit_log_repo_impl import AuditLogRepositoryImpl
    from eneo.database.tables.audit_log_table import AuditLog
    from eneo.database.tables.flow_tables import FlowRuns, FlowStepAttempts
    from eneo.database.tables.spaces_table import SpacesUsers
    from eneo.flows.api import flow_transcript_regeneration_router as router
    from eneo.flows.application.flow_transcript_regeneration_service import (
        render_original_segments,
    )
    from eneo.flows.domain.transcript_corrections import segments_content_hash
    from eneo.spaces.api.space_models import SpaceRoleValue

    dispatch = AsyncMock()
    monkeypatch.setattr(router, "dispatch_flow_run_recoverably_after_commit", dispatch)
    segments = [
        {
            **SEGMENTS[0],
            "text": "🙂 Ett. Två.",
            "speaker_attribution": "provisional",
            "overlap_ids": ["file:overlap_0000"],
        },
        {
            **SEGMENTS[1],
            "text": "Klart.",
            "speaker_attribution": "assigned",
            "overlap_ids": [],
        },
    ]
    async with db_container() as container:
        session = container.session()
        scenario = await _create_scenario(
            session=session,
            completion_model_factory=completion_model_factory,
            space_factory=space_factory,
            assistant_factory=assistant_factory,
            admin_user=admin_user,
            runtime_definition=True,
        )
        flow = await FlowRepository(session=session).get(
            scenario.flow_id, admin_user.tenant_id
        )
        session.add(
            SpacesUsers(
                space_id=flow.space_id,
                user_id=admin_user.id,
                role=SpaceRoleValue.EDITOR,
            )
        )
        await _store_segments(
            session=session,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            segments=segments,
        )
        await session.execute(
            sa.update(FlowRuns)
            .where(FlowRuns.id == scenario.flow_run_id)
            .values(
                status="completed",
                finished_at=datetime.now(timezone.utc),
                output_payload_json={"text": "Original summary"},
            )
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == scenario.flow_run_id,
            )
            .values(
                status="completed", output_payload_json={"text": "Original summary"}
            )
        )
        await session.execute(
            sa.update(FlowStepResults)
            .where(
                FlowStepResults.flow_run_id == scenario.flow_run_id,
                FlowStepResults.step_id == scenario.transcription_step_id,
            )
            .values(output_payload_json={"text": render_original_segments(segments)})
        )
        await _service(session=session, admin_user=admin_user).save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            schema_version=3,
            expected_segments_hash=segments_content_hash(segments),
            expected_revision=None,
            occurrences=[TranscriptCorrectionOccurrence(0, 4, 5, "t", "t!")],
            speaker_edits=[
                TranscriptSpeakerEdit(
                    0, 2, 6, "Ett.", "SPEAKER_00", None, "unresolved"
                ),
                TranscriptSpeakerEdit(
                    1, None, None, None, "SPEAKER_01", "SPEAKER_01", "confirmed"
                ),
            ],
        )
        token = container.auth_service().create_access_token_for_user(admin_user)
    if audit_failure:

        async def unavailable(self, audit_log):
            raise RuntimeError("audit storage unavailable")

        monkeypatch.setattr(AuditLogRepositoryImpl, "create", unavailable)
    path = f"/api/v1/flows/{scenario.flow_id}/runs/{scenario.flow_run_id}/steps/{scenario.transcription_step_id}/transcript-regenerations/"
    headers = {
        "Authorization": f"Bearer {token}",
        "Idempotency-Key": "reviewed-output-1",
    }
    body = {
        "expected_run_revision": 1,
        "expected_correction_revision": 1,
        "segments_hash": segments_content_hash(segments),
    }
    response = await client.post(path, headers=headers, json=body)
    if audit_failure:
        assert response.status_code == 503, response.text
        async with db_container() as container:
            runs = (
                await container.session().scalars(
                    sa.select(FlowRuns).where(FlowRuns.flow_id == scenario.flow_id)
                )
            ).all()
            assert len(runs) == 1
        dispatch.assert_not_awaited()
        return
    assert response.status_code == 201, response.text
    child_id = UUID(response.json()["run"]["id"])
    assert response.json()["first_regenerated_step_id"] == str(scenario.plain_step_id)
    dispatch.assert_awaited_once()
    async with db_container() as container:
        session = container.session()
        repo = FlowRunRepository(session=session)
        source = await repo.get(
            run_id=scenario.flow_run_id, tenant_id=admin_user.tenant_id
        )
        child = await repo.get(run_id=child_id, tenant_id=admin_user.tenant_id)
        assert source.output_payload_json == {"text": "Original summary"}
        assert (
            child.input_payload_json["transcript_regeneration"]["correction_revision"]
            == 1
        )
        assert (
            "[Talare går inte att avgöra]: Ett!."
            in child.input_payload_json["transkribering"]
        )
        results = await repo.list_step_results(
            run_id=child_id, tenant_id=admin_user.tenant_id
        )
        assert [step.status.value for step in results] == ["completed", "pending"]
        assert results[0].input_payload_json["transcription"]["segments"] == segments
        assert (
            results[0].output_payload_json["text"]
            == child.input_payload_json["transkribering"]
        )
        correction_repo = FlowTranscriptCorrectionsRepository(session=session)
        copied = await correction_repo.get_for_step(
            run_id=child_id,
            step_id=scenario.transcription_step_id,
            tenant_id=admin_user.tenant_id,
        )
        assert copied.speaker_edits()[0].decision == "unresolved"
        assert copied.edited_by_user_id == admin_user.id
        attempts = (
            await session.scalars(
                sa.select(FlowStepAttempts).where(
                    FlowStepAttempts.flow_run_id == child_id,
                )
            )
        ).all()
        assert len(attempts) == 1
        assert attempts[0].provenance_json["source_run_id"] == str(source.id)
        audits = (
            await session.scalars(
                sa.select(AuditLog).where(
                    AuditLog.entity_id == child_id,
                    AuditLog.action == ActionType.FLOW_RUN_CREATED.value,
                )
            )
        ).all()
        assert len(audits) == 1
        # A new source revision must not alter an accepted child's snapshot.
        await _service(session=session, admin_user=admin_user).save(
            flow_id=scenario.flow_id,
            run_id=scenario.flow_run_id,
            step_id=scenario.transcription_step_id,
            schema_version=3,
            expected_segments_hash=segments_content_hash(segments),
            expected_revision=1,
            occurrences=[],
            speaker_edits=[],
        )
    replay = await client.post(path, headers=headers, json=body)
    assert replay.status_code == 200, replay.text
    assert replay.json()["run"]["id"] == str(child_id)
    assert replay.json()["created"] is False
    dispatch.assert_awaited_once()
    stale = await client.post(
        path, headers={**headers, "Idempotency-Key": "new-action"}, json=body
    )
    assert stale.status_code == 400
    assert stale.json()["context"]["reason"] == "correction_revision_changed"
    conflict = await client.post(
        path, headers=headers, json={**body, "expected_correction_revision": 2}
    )
    assert conflict.status_code == 400
    assert conflict.json()["code"] == FlowApiErrorCode.RUN_IDEMPOTENCY_CONFLICT.value

    # Execute the real worker: only the downstream step runs, using the saved
    # snapshot even though the source correction set has since changed.
    from types import SimpleNamespace

    from dependency_injector import providers

    from eneo.database.database import sessionmanager
    from eneo.flows.runtime.executor import FlowRunExecutor
    from eneo.flows.runtime.flow_run_actor import FlowRunActor
    from eneo.flows.runtime.tasks import enable_autobegin_for_flow_task_session
    from eneo.main.container.container import Container

    async with sessionmanager.session() as session:
        enable_autobegin_for_flow_task_session(session)
        worker = Container(
            session=providers.Object(session), tenant=providers.Object(test_tenant)
        )
        file_service = worker.file_service(user=admin_user)
        transcriber = AsyncMock()
        completion = AsyncMock()
        completion.get_response.return_value = SimpleNamespace(
            completion="Updated summary",
            total_token_count=13,
        )

        async def get_response(*, completion_service, **kwargs):
            return await completion_service.get_response(**kwargs)

        scenario.runtime_assistant.get_response = get_response
        executor = FlowRunExecutor(
            runtime_actor=FlowRunActor.from_user(user=admin_user),
            session=session,
            flow_repo=worker.flow_repo(),
            flow_run_repo=worker.flow_run_repo(),
            flow_run_review_checkpoint_repo=worker.flow_run_review_checkpoint_repo(),
            flow_run_terminalizer=worker.flow_run_terminalizer(),
            flow_version_repo=worker.flow_version_repo(),
            space_repo=worker.tenant_scoped_space_repo(),
            completion_service=completion,
            file_repo=worker.file_repo(),
            file_content_loader=worker.file_content_loader(),
            file_service=file_service,
            template_asset_repo=worker.flow_template_asset_repo(),
            encryption_service=worker.encryption_service(),
            audit_service=SimpleNamespace(log_async=AsyncMock(return_value=uuid4())),
            transcriber=transcriber,
            max_inline_text_bytes=1024 * 1024,
        )
        executor._load_assistant = AsyncMock(return_value=scenario.runtime_assistant)
        outcome = await executor.execute(
            run_id=child_id,
            flow_id=scenario.flow_id,
            tenant_id=admin_user.tenant_id,
            run_revision=1,
            dispatch_task_id="regeneration-test",
            retry_count=0,
        )
        assert outcome["status"] == "completed", outcome
        transcriber.transcribe.assert_not_called()
        completion.get_response.assert_awaited_once()
        child = await worker.flow_run_repo().get(
            run_id=child_id, tenant_id=admin_user.tenant_id
        )
        assert child.output_payload_json["text"] == "Updated summary"
        assert (
            child.input_payload_json["transkribering"]
            in completion.get_response.await_args.kwargs["question"]
        )
        attempts = (
            await session.scalars(
                sa.select(FlowStepAttempts).where(
                    FlowStepAttempts.flow_run_id == child_id,
                )
            )
        ).all()
        assert len(attempts) == 2
        assert (
            sum(
                a.provenance_json.get("kind") == "reviewed_transcript_snapshot"
                for a in attempts
                if a.provenance_json
            )
            == 1
        )
