from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_transcript_regeneration_service import (
    FlowTranscriptRegenerationService,
)
from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.transcript_corrections import (
    TranscriptSpeakerEdit,
    segments_content_hash,
)
from eneo.flows.flow_api_exceptions import FlowBadRequestException


@pytest.fixture
def context():
    tenant_id, user_id, flow_id, run_id = uuid4(), uuid4(), uuid4(), uuid4()
    ids = [uuid4() for _ in range(3)]
    segments = [
        {
            "file_index": 0,
            "start": i,
            "end": i + 1,
            "speaker": "SPEAKER_00",
            "speaker_attribution": "provisional",
            "text": text,
        }
        for i, text in enumerate(["Confirmed.", "Unresolved.", "Pending."])
    ]
    source = SimpleNamespace(
        id=run_id,
        flow_id=flow_id,
        tenant_id=tenant_id,
        status="completed",
        revision=1,
        flow_version=1,
        input_payload_json={"question": "Meeting"},
        run_label=None,
    )
    user = SimpleNamespace(
        id=user_id,
        tenant_id=tenant_id,
        principal_type=PrincipalType.USER,
        principal_id=user_id,
        service_id=None,
    )
    steps = [
        SimpleNamespace(
            step_id=step_id,
            step_order=i + 1,
            input_type="text",
            output_mode="speaker_mapping" if i == 1 else "pass_through",
        )
        for i, step_id in enumerate(ids)
    ]
    results = [
        FlowStepResult(
            id=uuid4(),
            flow_run_id=run_id,
            flow_id=flow_id,
            tenant_id=tenant_id,
            step_id=step_id,
            step_order=i + 1,
            current_attempt_no=3,
            status=FlowStepResultStatus.COMPLETED,
            input_payload_json={"transcription": {"segments": segments}}
            if i == 0
            else {},
            output_payload_json={"text": "Stale summary"},
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        for i, step_id in enumerate(ids)
    ]
    results[1].output_payload_json.update(
        {
            "structured": {"speakers": [{"label": "SPEAKER_00", "name": "Anna"}]},
            "speaker_mapping": {"source_step_id": str(ids[0]), "source_attempt_no": 3},
        }
    )
    corrections = SimpleNamespace(
        revision=4,
        schema_version=3,
        segments_hash=segments_content_hash(segments),
        occurrences=lambda: [],
        speaker_edits=lambda: [
            TranscriptSpeakerEdit(0, None, None, None, "SPEAKER_00", "SPEAKER_00"),
            TranscriptSpeakerEdit(
                1, None, None, None, "SPEAKER_00", None, "unresolved"
            ),
        ],
    )
    run_repo = AsyncMock()
    run_repo.get_idempotent_run.return_value = None
    run_repo.get_step_result.return_value = results[0]
    run_repo.list_current_step_input_file_ids_by_step_result_id.return_value = {}
    run_repo.list_step_results.return_value = results
    run_service = AsyncMock()
    # The versioned view exposes step annotations only (no payloads); the
    # service must read complete rows from the repository instead.
    run_service.get_run_versioned_view.return_value = SimpleNamespace(
        published_definition=SimpleNamespace(runtime_steps=lambda: steps),
        step_results=[
            SimpleNamespace(step_id=result.step_id, status=result.status)
            for result in results
        ],
    )
    child = SimpleNamespace(id=uuid4(), revision=1)
    run_service.create_run.return_value = SimpleNamespace(run=child, created=True)
    access = AsyncMock()
    access.load_run.return_value = source
    corrections_repo = AsyncMock()
    corrections_repo.get_for_step.return_value = corrections
    words_repo = AsyncMock()
    words_repo.get_for_step.return_value = None
    service = FlowTranscriptRegenerationService(
        user=user,
        run_service=run_service,
        access_policy=access,
        run_repo=run_repo,
        corrections_repo=corrections_repo,
        words_repo=words_repo,
        audit_service=AsyncMock(),
    )
    request = dict(
        flow_id=flow_id,
        run_id=run_id,
        step_id=ids[0],
        expected_run_revision=1,
        expected_correction_revision=4,
        segments_hash=segments_content_hash(segments),
        idempotency_key="regenerate",
    )
    return SimpleNamespace(
        service=service,
        request=request,
        source=source,
        steps=steps,
        results=results,
        corrections=corrections,
        segments=segments,
    )


async def test_naming_snapshot_preserves_confirmed_unresolved_and_provisional(context):
    await context.service.regenerate(**context.request)
    args = context.service.run_service.create_run.await_args.kwargs
    seed = args["prefix_seed"]
    assert "Anna: Confirmed." in seed.transcript
    assert "[Talare går inte att avgöra]: Unresolved." in seed.transcript
    assert "[Överlappande tal – osäker talare]: Pending." in seed.transcript
    assert "Anna: Pending." not in seed.transcript
    assert "Stale summary" not in seed.transcript
    assert len(seed.results) == 2
    assert (
        seed.results[1].output_payload_json["speaker_mapping"]["source_attempt_no"] == 1
    )
    assert (
        context.results[1].output_payload_json["speaker_mapping"]["source_attempt_no"]
        == 3
    )
    assert args["expected_flow_version"] == 1
    assert seed.provenance["correction_revision"] == 4
    context.service.corrections_repo.copy_snapshot.assert_awaited_once()
    assert context.service.audit_service.log.await_args.kwargs["required"] is True


@pytest.mark.parametrize(
    "failure,reason",
    [
        ("running", "source_run_not_completed"),
        ("run_revision", "source_run_changed"),
        ("hash", "stale_segments"),
        ("correction_revision", "correction_revision_changed"),
        ("correction_hash", "stale_or_unsupported_corrections"),
        ("mapping_attempt", "speaker_mapping_source_changed"),
        ("prefix_pending", "source_prefix_incomplete"),
        ("no_downstream", "unsupported_downstream_transcription"),
        ("later_audio", "unsupported_downstream_transcription"),
        ("wrong_first", "transcription_must_be_first_step"),
    ],
)
async def test_rejects_unsafe_sources_before_creating_a_run(context, failure, reason):
    if failure == "running":
        context.source.status = "running"
    elif failure == "run_revision":
        context.source.revision = 2
    elif failure == "hash":
        context.request["segments_hash"] = "b" * 64
    elif failure == "correction_revision":
        context.corrections.revision = 5
    elif failure == "correction_hash":
        context.corrections.segments_hash = "b" * 64
    elif failure == "mapping_attempt":
        context.results[1].output_payload_json["speaker_mapping"][
            "source_attempt_no"
        ] = 2
    elif failure == "prefix_pending":
        context.results[1].status = FlowStepResultStatus.PENDING
    elif failure == "no_downstream":
        context.steps.pop()
    elif failure == "later_audio":
        context.steps[2].input_type = "audio"
    elif failure == "wrong_first":
        context.steps[0].step_id = uuid4()
    with pytest.raises(FlowBadRequestException) as exc:
        await context.service.regenerate(**context.request)
    assert exc.value.context["reason"] == reason
    context.service.run_service.create_run.assert_not_awaited()
    context.service.audit_service.log.assert_not_awaited()


async def test_source_content_access_is_required_before_any_mutation(context):
    from eneo.main.exceptions import NotFoundException

    context.service.access_policy.load_run.side_effect = NotFoundException()
    with pytest.raises(NotFoundException):
        await context.service.regenerate(**context.request)
    context.service.run_repo.acquire_tenant_run_creation_lock.assert_not_awaited()
    context.service.run_service.create_run.assert_not_awaited()


@pytest.mark.parametrize("matching", [True, False])
async def test_word_evidence_is_copied_only_when_anchored_to_original_segments(
    context, matching
):
    words = SimpleNamespace(
        segments_hash=context.request["segments_hash"] if matching else "b" * 64,
        alignment="forced",
        words_json=[
            {
                "segment_index": 0,
                "words": [
                    {
                        "word": "Confirmed.",
                        "start": 0.1,
                        "end": 0.8,
                        "probability": 0.9,
                    },
                ],
            }
        ],
    )
    context.service.words_repo.get_for_step.return_value = words
    await context.service.regenerate(**context.request)
    if matching:
        saved = context.service.words_repo.upsert.await_args.kwargs
        assert saved["segments_hash"] == context.request["segments_hash"]
        assert saved["words_json"] == words.words_json
        assert saved["alignment"] == "forced"
    else:
        context.service.words_repo.upsert.assert_not_awaited()


async def test_null_revision_can_regenerate_an_unedited_transcript(context):
    context.service.corrections_repo.get_for_step.return_value = None
    context.request["expected_correction_revision"] = None
    await context.service.regenerate(**context.request)
    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert seed.provenance["correction_revision"] is None
    assert seed.transcript.count("[Överlappande tal – osäker talare]") == 3
    context.service.corrections_repo.copy_snapshot.assert_not_awaited()


@pytest.mark.parametrize("label", [None, "Ärende 42"])
async def test_regeneration_copies_source_run_label(context, label):
    context.source.run_label = label
    await context.service.regenerate(**context.request)
    args = context.service.run_service.create_run.await_args.kwargs
    assert "run_label" in args
    assert args["run_label"] == label


async def test_regeneration_replays_accepted_prefix_after_source_changes(context):
    await context.service.regenerate(**context.request)
    args = context.service.run_service.create_run.await_args.kwargs
    child = context.service.run_service.create_run.return_value.run
    child.input_payload_json = {
        "transcript_regeneration": args["prefix_seed"].provenance
    }
    context.service.run_repo.get_idempotent_run.return_value = (child, "fingerprint")
    context.source.revision = 2
    context.service.run_service.create_run.reset_mock()
    context.service.audit_service.log.reset_mock()

    replay = await context.service.regenerate(**context.request)

    assert replay.run is child
    assert replay.created is False
    context.service.run_service.create_run.assert_not_awaited()
    context.service.audit_service.log.assert_not_awaited()
