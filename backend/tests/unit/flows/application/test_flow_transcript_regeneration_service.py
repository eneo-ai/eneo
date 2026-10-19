import copy
import hashlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.authentication.principal_types import PrincipalType
from eneo.flows.application.flow_transcript_regeneration_service import (
    FlowTranscriptRegenerationService,
    _render_reviewed_transcript,
)
from eneo.flows.domain.flow import FlowStepResult, FlowStepResultStatus
from eneo.flows.domain.speaker_labels import (
    apply_speaker_names,
    effective_speaker_names,
)
from eneo.flows.domain.step_output import build_text_overflow_metadata
from eneo.flows.domain.transcript_corrections import (
    TranscriptCorrectionOccurrence,
    TranscriptSpeakerEdit,
    segments_content_hash,
)
from eneo.flows.flow_api_error_code import FlowApiErrorCode
from eneo.flows.flow_api_exceptions import FlowBadRequestException
from eneo.flows.runtime.speaker_mapping_runtime import (
    mapping_to_names,
    validate_speaker_mapping,
)


def _source_state(segments, *, source=None):
    """The step's transcript source: captured from ``segments``, or ``source``
    as a run stores it."""
    from eneo.flows.domain.transcript_source import (
        PresentTranscriptSource,
        TranscriptComponentOmissions,
    )
    from eneo.flows.runtime.transcription import capture_transcript_source

    return PresentTranscriptSource(
        source=source
        or capture_transcript_source(
            segments=segments, speaker_review=None, words=[], words_omitted_reason=None
        ),
        component_omissions=TranscriptComponentOmissions(detail=None, words=None),
    )


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
            review_policy=None,
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
            input_payload_json={},
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
        speaker_names={},
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
        transcript_source_service=AsyncMock(
            get_for_attempt=AsyncMock(return_value=_source_state(segments))
        ),
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
    assert "Anna: Confirmed." in seed.transcript.text
    assert "[Talare går inte att avgöra]: Unresolved." in seed.transcript.text
    assert "[Överlappande tal – osäker talare]: Pending." in seed.transcript.text
    assert "Anna: Pending." not in seed.transcript.text
    assert "Stale summary" not in seed.transcript.text
    assert seed.transcript.reference.source_step_id == seed.results[-1].step_id
    assert seed.transcript.reference.source_attempt_no == 1
    assert seed.transcript.reference.selector.path == ("output", "text")
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
    assert seed.transcript_sources[context.request["step_id"]] is (
        context.service.transcript_source_service.get_for_attempt.return_value.source
    )
    context.service.corrections_repo.copy_snapshot.assert_awaited_once()
    assert context.service.audit_service.log.await_args.kwargs["required"] is True


async def test_a_transcript_without_speakers_regenerates_without_line_times(
    context,
):
    # Its step kept the model's own text, and timing its words added nothing
    # to it; a regeneration adds no timestamps either.
    segments = [
        {
            "file_index": 0,
            "start": 0.0,
            "end": 2.0,
            "speaker": None,
            "text": "Vi frågade sugary om planen.",
        },
        {
            "file_index": 0,
            "start": 2.4,
            "end": 5.2,
            "speaker": None,
            "text": "Hon svarade direkt.",
        },
    ]
    digest = segments_content_hash(segments)
    context.service.transcript_source_service.get_for_attempt.return_value = (
        _source_state(segments)
    )
    context.request["segments_hash"] = digest
    context.corrections.segments_hash = digest
    context.corrections.occurrences = lambda: [
        TranscriptCorrectionOccurrence(0, 11, 17, "sugary", "Çagri")
    ]
    context.corrections.speaker_edits = lambda: []
    context.steps[1].output_mode = "pass_through"

    await context.service.regenerate(**context.request)

    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert seed.transcript.text == "Vi frågade Çagri om planen.\nHon svarade direkt."


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


@pytest.mark.parametrize("source_index", [0, 1])
async def test_file_backed_prefix_cannot_be_regenerated(context, source_index):
    payload = context.results[source_index].output_payload_json
    payload["text_overflow"] = build_text_overflow_metadata(
        file_ids=[uuid4()], preview=payload["text"], full_text=payload["text"] * 100
    )
    with pytest.raises(FlowBadRequestException) as exc:
        await context.service.regenerate(**context.request)
    assert exc.value.context == {"reason": "file_backed_prefix_unsupported"}
    assert (
        str(exc.value)
        == "The reviewed transcript cannot be regenerated with this request."
    )
    context.service.run_service.create_run.assert_not_awaited()
    context.service.corrections_repo.copy_snapshot.assert_not_awaited()


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
    assert seed.transcript.text.count("[Överlappande tal – osäker talare]") == 3
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


@pytest.mark.parametrize("review_required", [False, True])
async def test_regeneration_records_approval_from_reviewed_snapshot(
    context, review_required
):
    context.steps[1].review_policy = object() if review_required else None
    await context.service.regenerate(**context.request)
    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert seed.review_established_step_ids == (
        frozenset({context.steps[1].step_id}) if review_required else frozenset()
    )


# Five lines over two recordings: a correction, a split, a line nobody named, an
# unresolved decision and an overlap.
NAMED_SEGMENTS = [
    {
        "file_index": 0,
        "start": 0,
        "end": 1,
        "speaker": "SPEAKER_00",
        "text": "Vi frågade sugary.",
    },
    {
        "file_index": 0,
        "start": 1,
        "end": 2,
        "speaker": "SPEAKER_01",
        "text": "Hej där alla.",
    },
    {"file_index": 0, "start": 2, "end": 3, "speaker": "SPEAKER_02", "text": "Tredje."},
    {"file_index": 1, "start": 3, "end": 4, "speaker": "SPEAKER_00", "text": "Okänd."},
    {
        "file_index": 1,
        "start": 4,
        "end": 5,
        "speaker": "SPEAKER_00",
        "speaker_attribution": "provisional",
        "text": "Överlapp.",
    },
]
NAMED_OCCURRENCES = [TranscriptCorrectionOccurrence(0, 11, 17, "sugary", "Çagri")]
NAMED_EDITS = [
    TranscriptSpeakerEdit(1, 4, 13, "där alla.", "SPEAKER_01", "SPEAKER_03"),
    TranscriptSpeakerEdit(3, None, None, None, "SPEAKER_00", None, "unresolved"),
]


def _name_the_transcript(context, names, *, speaker_step: bool = False):
    digest = segments_content_hash(NAMED_SEGMENTS)
    context.service.transcript_source_service.get_for_attempt.return_value = (
        _source_state(NAMED_SEGMENTS)
    )
    context.request["segments_hash"] = digest
    context.corrections.segments_hash = digest
    context.corrections.occurrences = lambda: list(NAMED_OCCURRENCES)
    context.corrections.speaker_edits = lambda: list(NAMED_EDITS)
    context.corrections.speaker_names = names
    if not speaker_step:
        # The owner's shape: transcription, then steps that only pass text on.
        context.steps[1].output_mode = "pass_through"


async def test_names_reach_the_next_step_through_the_transcription_prefix(context):
    _name_the_transcript(
        context, {"SPEAKER_00": "Anna", "SPEAKER_01": None, "SPEAKER_03": "Cecilia"}
    )

    await context.service.regenerate(**context.request)

    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    # Corrections and the split come first; names replace labels last. A label
    # nobody named, null included, stays; bracket lines and headings stay.
    expected = "\n".join(
        [
            "## Del 1",
            "",
            "[00:00:00 - 00:00:01] Anna: Vi frågade Çagri.",
            "[00:00:01 - 00:00:02] SPEAKER_01: Hej",
            "[00:00:01 - 00:00:02] Cecilia: där alla.",
            "[00:00:02 - 00:00:03] SPEAKER_02: Tredje.",
            "",
            "## Del 2",
            "",
            "[00:00:03 - 00:00:04] [Talare går inte att avgöra]: Okänd.",
            "[00:00:04 - 00:00:05] [Överlappande tal – osäker talare]: Överlapp.",
        ]
    )
    assert seed.transcript.text == expected
    assert len(seed.results) == 1
    assert seed.results[0].output_payload_json["text"] == expected
    assert (
        seed.provenance["reviewed_text_hash"]
        == hashlib.sha256(expected.encode()).hexdigest()
    )


async def test_without_names_the_regenerated_transcript_is_unchanged(context):
    _name_the_transcript(context, {})

    await context.service.regenerate(**context.request)

    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    labelled = _render_reviewed_transcript(
        NAMED_SEGMENTS, NAMED_OCCURRENCES, NAMED_EDITS, None
    )
    assert seed.transcript.text == labelled
    assert seed.results[0].output_payload_json["text"] == labelled
    assert (
        seed.provenance["reviewed_text_hash"]
        == hashlib.sha256(labelled.encode()).hexdigest()
    )


async def test_a_persons_names_override_the_speaker_naming_step(context):
    _name_the_transcript(
        context,
        {"SPEAKER_00": "Anna Berg", "SPEAKER_01": None},
        speaker_step=True,
    )
    context.results[1].output_payload_json["structured"] = {
        "speakers": [
            {"label": "SPEAKER_00", "name": "Anna"},
            {"label": "SPEAKER_01", "name": "Bo"},
            {"label": "SPEAKER_02", "name": "Cecilia"},
        ]
    }

    await context.service.regenerate(**context.request)

    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    transcription, naming = (result.output_payload_json for result in seed.results)
    labelled = _render_reviewed_transcript(
        NAMED_SEGMENTS, NAMED_OCCURRENCES, NAMED_EDITS, None
    )
    # The transcription keeps its labels; the naming step's text has the names.
    assert transcription["text"] == labelled
    named = naming["text"].splitlines()
    assert named[2] == "[00:00:00 - 00:00:01] Anna Berg: Vi frågade Çagri."
    assert named[3] == "[00:00:01 - 00:00:02] SPEAKER_01: Hej"
    assert named[5] == "[00:00:02 - 00:00:03] Cecilia: Tredje."
    assert seed.transcript.text == naming["text"]
    assert (
        seed.provenance["reviewed_text_hash"]
        == hashlib.sha256(naming["text"].encode()).hexdigest()
    )


# The naming step's proposal, each identity with the model's support for it.
PROPOSAL = {
    "speakers": [
        {
            "label": "SPEAKER_00",
            "name": "Anna",
            "confidence": "high",
            "evidence": "Anna presenterar sig.",
        },
        {
            "label": "SPEAKER_01",
            "name": "Bo",
            "confidence": "medium",
            "evidence": "Bo tilltalas vid namn.",
        },
        {
            "label": "SPEAKER_02",
            "name": "Cecilia",
            "confidence": "high",
            "evidence": "Cecilia hälsar.",
        },
    ]
}


def _correct_the_steps_names(context):
    """A person names the step's Anna Bertil, clears its Bo, and names Doris
    the speaker they split off from Bo's line, whom the step never saw."""
    names = {"SPEAKER_00": "Bertil", "SPEAKER_01": None, "SPEAKER_03": "Doris"}
    _name_the_transcript(context, names, speaker_step=True)
    context.results[1].output_payload_json["structured"] = copy.deepcopy(PROPOSAL)
    return names


async def test_the_naming_steps_mapping_names_the_speakers_its_text_names(context):
    _correct_the_steps_names(context)

    await context.service.regenerate(**context.request)

    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    naming = seed.results[1].output_payload_json
    # A later step that reads the mapping finds the person's names. A name a
    # person gives is certain and one they clear is unknown; the model's
    # evidence argued for Anna and Bo, so neither keeps it. Cecilia keeps hers.
    # Doris, a person's name too, follows the step's speakers.
    assert naming["structured"] == {
        "speakers": [
            {
                "label": "SPEAKER_00",
                "name": "Bertil",
                "confidence": "high",
                "evidence": "",
            },
            {"label": "SPEAKER_01", "name": None, "confidence": "low", "evidence": ""},
            PROPOSAL["speakers"][2],
            {
                "label": "SPEAKER_03",
                "name": "Doris",
                "confidence": "high",
                "evidence": "",
            },
        ]
    }
    # A review of the new run's mapping takes it as it is.
    assert (
        validate_speaker_mapping(
            naming["structured"],
            inventory=PROPOSAL["speakers"],
            participants=[],
            allow_free_text=True,
            split_labels=["SPEAKER_03"],
        )
        == naming["structured"]
    )
    # The text is the labelled transcript named by that mapping.
    labelled = _render_reviewed_transcript(
        NAMED_SEGMENTS, NAMED_OCCURRENCES, NAMED_EDITS, None
    )
    assert naming["text"] == apply_speaker_names(
        labelled, mapping_to_names(naming["structured"])
    )
    named = naming["text"].splitlines()
    assert named[2] == "[00:00:00 - 00:00:01] Bertil: Vi frågade Çagri."
    assert named[3] == "[00:00:01 - 00:00:02] SPEAKER_01: Hej"
    assert named[4] == "[00:00:01 - 00:00:02] Doris: där alla."
    assert named[5] == "[00:00:02 - 00:00:03] Cecilia: Tredje."
    # The source run keeps the step's own proposal.
    assert context.results[1].output_payload_json["structured"] == PROPOSAL


async def test_a_split_whose_words_were_deleted_is_not_named_in_the_mapping(context):
    _correct_the_steps_names(context)
    context.corrections.occurrences = lambda: [
        *NAMED_OCCURRENCES,
        TranscriptCorrectionOccurrence(1, 4, 13, "där alla.", ""),
    ]

    await context.service.regenerate(**context.request)

    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    naming = seed.results[1].output_payload_json
    # Neither the text nor the mapping has Doris left to name.
    assert "Doris" not in naming["text"]
    assert [entry["label"] for entry in naming["structured"]["speakers"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
        "SPEAKER_02",
    ]


async def test_the_new_runs_mapping_and_regeneration_keep_the_persons_names(context):
    names = _correct_the_steps_names(context)
    await context.service.regenerate(**context.request)
    first = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    copied = context.service.corrections_repo.copy_snapshot.await_args.kwargs[
        "corrections"
    ]

    # The new run as it is stored: the imported prefix as attempt 1, the
    # copied transcript source and corrections, and the step that reads them.
    child = context.service.run_service.create_run.return_value.run
    seeded = [
        result.model_copy(update={"flow_run_id": child.id, "current_attempt_no": 1})
        for result in first.results
    ]
    consumer = context.results[2].model_copy(update={"flow_run_id": child.id})
    context.service.run_repo.get_step_result.return_value = seeded[0]
    context.service.run_repo.list_step_results.return_value = [*seeded, consumer]
    step_id = context.request["step_id"]
    context.service.transcript_source_service.get_for_attempt.return_value = (
        _source_state(None, source=first.transcript_sources[step_id])
    )
    context.service.corrections_repo.get_for_step.return_value = copied
    context.service.access_policy.load_run.return_value = SimpleNamespace(
        **{**vars(context.source), "id": child.id}
    )

    # What the person saw: the step's names under theirs. An app shows the
    # new run the same way, and the new run's mapping already names them so.
    seen = effective_speaker_names(mapping_to_names(PROPOSAL), names)
    stored = mapping_to_names(seeded[1].output_payload_json["structured"])
    assert stored == seen
    assert seen == {
        "SPEAKER_00": "Bertil",
        "SPEAKER_02": "Cecilia",
        "SPEAKER_03": "Doris",
    }
    assert effective_speaker_names(stored, copied.speaker_names) == seen

    await context.service.regenerate(
        **{**context.request, "run_id": child.id, "idempotency_key": "again"}
    )

    second = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert second.transcript.text == first.transcript.text
    assert (
        second.results[1].output_payload_json["structured"]
        == seeded[1].output_payload_json["structured"]
    )


async def test_the_new_run_keeps_the_names_for_its_own_regeneration(context):
    names = {"SPEAKER_00": "Anna"}
    _name_the_transcript(context, names)

    await context.service.regenerate(**context.request)

    first = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    snapshot = context.service.corrections_repo.copy_snapshot.await_args.kwargs
    assert snapshot["corrections"].speaker_names == names
    # The copied set is all the new run's regeneration reads.
    child = context.service.run_service.create_run.return_value.run
    context.service.access_policy.load_run.return_value = SimpleNamespace(
        **{**vars(context.source), "id": child.id}
    )
    context.service.corrections_repo.get_for_step.return_value = snapshot["corrections"]
    await context.service.regenerate(
        **{**context.request, "run_id": child.id, "idempotency_key": "again"}
    )
    second = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert second.transcript.text == first.transcript.text
    assert "] Anna: Vi frågade Çagri." in second.transcript.text


async def test_a_name_change_is_a_new_regeneration_request(context):
    _name_the_transcript(context, {"SPEAKER_00": "Anna"})
    await context.service.regenerate(**context.request)
    args = context.service.run_service.create_run.await_args.kwargs
    child = context.service.run_service.create_run.return_value.run
    child.input_payload_json = {
        "transcript_regeneration": args["prefix_seed"].provenance
    }
    context.service.run_repo.get_idempotent_run.return_value = (child, "fingerprint")
    context.service.run_service.create_run.reset_mock()

    # The same request replays the run it created.
    replay = await context.service.regenerate(**context.request)
    assert replay.run is child
    assert replay.created is False
    context.service.run_service.create_run.assert_not_awaited()

    # Saving a name bumps the correction revision the request names, so the
    # same key no longer fits and a new key creates a new run.
    context.corrections.speaker_names = {"SPEAKER_00": "Anna Berg"}
    context.corrections.revision = 5
    renamed = {**context.request, "expected_correction_revision": 5}
    with pytest.raises(FlowBadRequestException) as exc:
        await context.service.regenerate(**renamed)
    assert exc.value.code == FlowApiErrorCode.RUN_IDEMPOTENCY_CONFLICT
    context.service.run_repo.get_idempotent_run.return_value = None
    await context.service.regenerate(**{**renamed, "idempotency_key": "renamed"})
    seed = context.service.run_service.create_run.await_args.kwargs["prefix_seed"]
    assert "] Anna Berg: Vi frågade Çagri." in seed.transcript.text
    assert (
        seed.provenance["request_hash"]
        != args["prefix_seed"].provenance["request_hash"]
    )
