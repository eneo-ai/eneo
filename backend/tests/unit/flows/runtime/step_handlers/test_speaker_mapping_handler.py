from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from eneo.flows.domain.step_output import inline_transcript
from eneo.flows.runtime.step_handlers import speaker_mapping as handler_module
from eneo.main.exceptions import TypedIOValidationException
from tests.unit.flows.runtime.step_handlers import speaker_mapping_test_support
from tests.unit.flows.runtime.step_handlers.speaker_mapping_test_support import (
    PROPOSAL,
    SOURCE,
)
from tests.unit.flows.runtime.step_handlers.speaker_mapping_test_support import (
    runtime_deps as _deps,
)
from tests.unit.flows.runtime.step_handlers.speaker_mapping_test_support import (
    speaker_handler as _handler,
)
from tests.unit.flows.runtime.step_handlers.speaker_mapping_test_support import (
    speaker_step as _step,
)

harness = speaker_mapping_test_support.harness


def _state():
    previous = SimpleNamespace(
        step_id=uuid4(),
        current_attempt_no=3,
        input_payload_json={"transcription": {"diarization": "external"}},
        output_payload_json={"text": SOURCE},
    )
    return SimpleNamespace(completed_by_order={1: previous}), previous


async def test_proposal_renames_transcript_and_records_provenance(harness) -> None:
    calls, activate = harness
    handler, persist = _handler(activate)
    state, previous = _state()
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={
            "deltagare": "Anna, Bo",
            "transkribering": inline_transcript(
                text=SOURCE,
                source_step_id=previous.step_id,
                source_attempt_no=previous.current_attempt_no,
                selector_path=("output", "text"),
            ).model_dump(mode="json"),
        },
    )

    step = _step()
    result = await handler.execute(
        step=step, run=run, state=state, version_metadata=None, attempt_no=1
    )

    output = result.output
    assert (
        output.full_text.splitlines()[0]
        == "[00:00:00 - 00:00:04] Anna: Hej, jag heter Anna."
    )
    assert "SPEAKER_01: Hej Anna, Bo här." in output.full_text
    assert output.structured_output == PROPOSAL
    extension = output.output_payload_extensions["speaker_mapping"]
    assert extension["participants"] == ["Anna", "Bo"]
    assert extension["source_step_id"] == str(previous.step_id)
    assert extension["source_attempt_no"] == 3
    assert [entry["label"] for entry in extension["inventory"]] == [
        "SPEAKER_00",
        "SPEAKER_01",
    ]
    # The model sees the inventory and participants, plus the fixed instructions.
    assert '"Anna"' in calls["question"] and "SPEAKER_01" in calls["question"]
    assert calls["prompt"].startswith("Du är en assistent.")
    assert "Respond with JSON only" in calls["prompt"]
    assert calls["activated"][0].prepared.completion_call is not None
    # Knowledge retrieval is skipped for this step.
    assert calls["deps"].retrieve_rag_chunks is handler_module._no_rag
    assert await calls["deps"].retrieve_rag_chunks() == (
        [],
        {"attempted": False, "status": "skipped_speaker_mapping"},
        [],
    )
    assert any(d.code == "speaker_mapping_unmapped_labels" for d in output.diagnostics)
    persist.assert_awaited_once()
    stored = persist.await_args.args[1]
    assert stored.text == output.full_text
    assert stored.reference.source_step_id == step.step_id
    assert stored.reference.source_attempt_no == 1
    assert stored.reference.selector.path == ("output", "text")


async def test_a_stray_character_in_a_proposed_name_does_not_fail_the_step(
    harness,
) -> None:
    calls, activate = harness
    calls["structured"] = {
        "speakers": [
            {"label": "SPEAKER_00", "name": "An\u200bna\n", "confidence": "high"},
            {"label": "SPEAKER_01", "name": "B" * 121, "confidence": "low"},
        ]
    }
    handler, _ = _handler(activate)
    state, _ = _state()
    run = SimpleNamespace(id=uuid4(), input_payload_json={"deltagare": "Anna, Bo"})

    result = await handler.execute(
        step=_step(), run=run, state=state, version_metadata=None, attempt_no=1
    )

    output = result.output
    assert output.full_text.splitlines()[0].startswith("[00:00:00 - 00:00:04] Anna:")
    assert "SPEAKER_01: Hej Anna, Bo här." in output.full_text
    assert [entry["name"] for entry in output.structured_output["speakers"]] == [
        "Anna",
        None,
    ]


async def test_a_listed_name_matches_whatever_its_whitespace(harness) -> None:
    calls, activate = harness
    calls["structured"] = {
        "speakers": [
            {"label": "SPEAKER_00", "name": "Eva\u00a0Ek", "confidence": "high"},
            {"label": "SPEAKER_01", "name": "Bo  Berg", "confidence": "high"},
        ]
    }
    handler, _ = _handler(activate)
    state, _ = _state()
    run = SimpleNamespace(
        id=uuid4(), input_payload_json={"deltagare": "Eva\u00a0Ek, Bo  Berg"}
    )

    result = await handler.execute(
        step=_step(), run=run, state=state, version_metadata=None, attempt_no=1
    )

    output = result.output
    assert [entry["name"] for entry in output.structured_output["speakers"]] == [
        "Eva Ek",
        "Bo Berg",
    ]
    assert output.full_text.splitlines()[0].startswith("[00:00:00 - 00:00:04] Eva Ek:")
    extension = output.output_payload_extensions["speaker_mapping"]
    assert extension["participants"] == ["Eva Ek", "Bo Berg"]


async def test_a_roster_that_cleans_to_nothing_still_restricts_names(
    harness,
) -> None:
    calls, activate = harness
    calls["structured"] = {
        "speakers": [
            {"label": "SPEAKER_00", "name": "Anna", "confidence": "high"},
            {"label": "SPEAKER_01", "name": "Bo", "confidence": "high"},
        ]
    }
    handler, _ = _handler(activate)
    state, _ = _state()
    run = SimpleNamespace(id=uuid4(), input_payload_json={"deltagare": ["x" * 121]})

    result = await handler.execute(
        step=_step(), run=run, state=state, version_metadata=None, attempt_no=1
    )

    output = result.output
    assert [entry["name"] for entry in output.structured_output["speakers"]] == [
        None,
        None,
    ]
    assert output.full_text.splitlines()[0].startswith(
        "[00:00:00 - 00:00:04] SPEAKER_00:"
    )
    assert any(d.code == "speaker_mapping_unmapped_labels" for d in output.diagnostics)


async def test_run_transcript_keeps_distinct_source_with_identical_text(
    harness,
) -> None:
    _, activate = harness
    handler, persist = _handler(activate)
    state, _ = _state()
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={
            "transkribering": inline_transcript(
                text=SOURCE,
                source_step_id=uuid4(),
                source_attempt_no=3,
                selector_path=("output", "text"),
            ).model_dump(mode="json")
        },
    )

    await handler.execute(
        step=_step(), run=run, state=state, version_metadata=None, attempt_no=1
    )

    persist.assert_not_awaited()


@pytest.mark.parametrize("evidence_fields", [{}, {"evidence": None}, {"evidence": ""}])
async def test_absent_evidence_preserves_known_and_unknown_speakers(
    harness, evidence_fields
) -> None:
    calls, activate = harness
    calls["structured"] = {
        "speakers": [
            {**speaker, **evidence_fields}
            for speaker in (
                {"label": "SPEAKER_00", "name": "Anna", "confidence": "high"},
                {"label": "SPEAKER_01", "name": None, "confidence": "low"},
            )
        ]
    }
    handler, persist = _handler(activate)
    state, _ = _state()
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={
            "deltagare": "Anna",
            "transkribering": inline_transcript(
                text=SOURCE,
                source_step_id=state.completed_by_order[1].step_id,
                source_attempt_no=3,
                selector_path=("output", "text"),
            ).model_dump(mode="json"),
        },
    )

    result = await handler.execute(
        step=_step(output_config={"speaker_mapping": {"infer_names": True}}),
        run=run,
        state=state,
        version_metadata=None,
        attempt_no=1,
    )

    expected = SOURCE.replace("SPEAKER_00:", "Anna:")
    assert result.output.full_text == expected
    assert result.output.structured_output == {
        "speakers": [{**speaker, "evidence": ""} for speaker in PROPOSAL["speakers"]]
    }
    assert any(
        diagnostic.code == "speaker_mapping_unmapped_labels"
        for diagnostic in result.output.diagnostics
    )
    persist.assert_awaited_once()
    assert persist.await_args.args[1].text == expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("label", None),
        ("name", 42),
        ("confidence", None),
        ("evidence", {"text": "intro"}),
    ],
)
async def test_invalid_speaker_fields_fail_before_transcript_is_persisted(
    harness, field, value
) -> None:
    calls, activate = harness
    calls["structured"] = {
        "speakers": [{**PROPOSAL["speakers"][0], field: value}, PROPOSAL["speakers"][1]]
    }
    handler, persist = _handler(activate)
    state, _ = _state()

    with pytest.raises(TypedIOValidationException) as excinfo:
        await handler.execute(
            step=_step(),
            run=SimpleNamespace(
                id=uuid4(),
                input_payload_json={
                    "transkribering": inline_transcript(
                        text=SOURCE,
                        source_step_id=state.completed_by_order[1].step_id,
                        source_attempt_no=3,
                        selector_path=("output", "text"),
                    ).model_dump(mode="json")
                },
            ),
            state=state,
            version_metadata=None,
            attempt_no=1,
        )

    assert excinfo.value.code == "typed_io_contract_violation"
    persist.assert_not_awaited()


async def test_skipped_upstream_diarization_passes_transcript_through(harness) -> None:
    _, activate = harness
    handler, persist = _handler(activate, prepared_text="Bara text utan talare.")
    previous = SimpleNamespace(
        step_id=uuid4(),
        current_attempt_no=1,
        input_payload_json={
            "transcription": {"diarization": "skipped:empty_transcript"}
        },
    )
    state = SimpleNamespace(completed_by_order={1: previous})

    result = await handler.execute(
        step=_step(),
        run=SimpleNamespace(id=uuid4(), input_payload_json={}),
        state=state,
        version_metadata=None,
        attempt_no=1,
    )

    assert result.output.full_text == "Bara text utan talare."
    assert result.output.structured_output == {"speakers": []}
    assert result.output.output_payload_extensions["speaker_mapping"]["skipped"] is True
    assert any(d.code == "speaker_mapping_skipped" for d in result.output.diagnostics)
    persist.assert_not_awaited()


async def test_input_without_speaker_labels_fails_typed(harness) -> None:
    _, activate = harness
    handler, _ = _handler(activate, prepared_text="Bara text utan talare.")
    state, _ = _state()

    with pytest.raises(TypedIOValidationException):
        await handler.execute(
            step=_step(),
            run=SimpleNamespace(id=uuid4(), input_payload_json={}),
            state=state,
            version_metadata=None,
            attempt_no=1,
        )


@pytest.mark.parametrize(
    "labels",
    [
        ["SPEAKER_00"],
        ["SPEAKER_00", "SPEAKER_00"],
        ["SPEAKER_00", "SPEAKER_01", "SPEAKER_09"],
    ],
)
async def test_mapping_must_cover_exactly_the_transcript_inventory(
    harness, labels
) -> None:
    calls, activate = harness
    calls["structured"] = {
        "speakers": [
            {"label": label, "name": None, "confidence": "low", "evidence": None}
            for label in labels
        ]
    }
    handler, persist = _handler(activate)
    state, _ = _state()

    with pytest.raises(TypedIOValidationException) as excinfo:
        await handler.execute(
            step=_step(),
            run=SimpleNamespace(id=uuid4(), input_payload_json={"deltagare": "Anna"}),
            state=state,
            version_metadata=None,
            attempt_no=1,
        )

    assert excinfo.value.code == "typed_io_validation_failed"
    persist.assert_not_awaited()


async def test_oversized_renamed_transcript_fails_instead_of_overflowing(
    harness,
) -> None:
    _, activate = harness
    handler, _ = _handler(activate, deps=_deps(max_inline_text_bytes=10))
    state, _ = _state()

    with pytest.raises(TypedIOValidationException) as excinfo:
        await handler.execute(
            step=_step(),
            run=SimpleNamespace(id=uuid4(), input_payload_json={"deltagare": "Anna"}),
            state=state,
            version_metadata=None,
            attempt_no=1,
        )
    assert excinfo.value.code == "typed_io_transcript_too_large"
    assert (
        str(excinfo.value)
        == "Step 2: transcript with speaker names exceeds the inline output limit (10 bytes)."
    )


async def test_wrong_io_tuple_fails_before_any_model_call(harness) -> None:
    _, activate = harness
    handler, _ = _handler(activate)
    state, _ = _state()

    with pytest.raises(TypedIOValidationException):
        await handler.execute(
            step=_step(input_source="flow_input"),
            run=SimpleNamespace(id=uuid4(), input_payload_json={}),
            state=state,
            version_metadata=None,
            attempt_no=1,
        )


async def test_name_inference_accepts_names_outside_the_list(harness) -> None:
    calls, activate = harness
    calls["structured"] = {
        "speakers": [
            {
                "label": "SPEAKER_00",
                "name": "Maria",
                "confidence": "high",
                "evidence": "Presenterar sig som Maria.",
            },
            {
                "label": "SPEAKER_01",
                "name": "Gunnar",
                "confidence": "medium",
                "evidence": "Tilltalas som Gunnar.",
            },
        ]
    }
    handler, _ = _handler(
        activate,
        prepared_text=SOURCE.replace("Anna", "Maria").replace("Bo här", "Gunnar här"),
    )
    state, _ = _state()
    run = SimpleNamespace(id=uuid4(), input_payload_json={"deltagare": "Bo"})
    step = _step(
        output_config={
            "speaker_mapping": {"participants_field": "deltagare", "infer_names": True}
        }
    )

    result = await handler.execute(
        step=step, run=run, state=state, version_metadata=None, attempt_no=1
    )

    output = result.output
    assert output.full_text.splitlines()[0].startswith("[00:00:00 - 00:00:04] Maria:")
    assert output.full_text.splitlines()[1].startswith("[00:00:05 - 00:00:09] Gunnar:")
    extension = output.output_payload_extensions["speaker_mapping"]
    assert extension["participants"] == ["Bo"]
    assert extension["infer_names"] is True
    # The frozen call carries the conversation's opening and the inferring rules.
    question = json.loads(calls["question"])
    assert question["opening"] == [
        "SPEAKER_00: Hej, jag heter Maria.",
        "SPEAKER_01: Hej Maria, Gunnar här.",
    ]
    assert "Never invent a name" in calls["prompt"]
    assert "participant list never" in calls["prompt"]


async def test_without_inference_the_call_is_unchanged(harness) -> None:
    calls, activate = harness
    handler, _ = _handler(activate)
    state, _ = _state()
    run = SimpleNamespace(id=uuid4(), input_payload_json={"deltagare": "Anna, Bo"})

    result = await handler.execute(
        step=_step(), run=run, state=state, version_metadata=None, attempt_no=1
    )

    assert "opening" not in json.loads(calls["question"])
    assert "Never invent a name" in calls["prompt"]
    extension = result.output.output_payload_extensions["speaker_mapping"]
    assert extension["infer_names"] is False


async def test_provisional_only_speaker_has_no_naming_evidence(harness):
    calls, activate = harness
    source = "[00:00:00 - 00:00:01] [Överlappande tal – osäker talare]: Jag heter Anna."
    handler, _ = _handler(activate, prepared_text=source)
    state, previous = _state()
    previous.input_payload_json["transcription"].update(
        {
            "speaker_review": {"files": [{"overlap_detection": "available"}]},
            "speakers": [
                {
                    "label": "SPEAKER_00",
                    "file_index": 0,
                    "file_id": str(uuid4()),
                    "line_count": 1,
                    "samples": [],
                    "clean_example_available": False,
                }
            ],
        }
    )
    calls["structured"] = {"speakers": [PROPOSAL["speakers"][0]]}
    result = await handler.execute(
        step=_step(),
        run=SimpleNamespace(id=uuid4(), input_payload_json={}),
        state=state,
        version_metadata=None,
        attempt_no=1,
    )
    inventory = result.output.output_payload_extensions["speaker_mapping"]["inventory"]
    assert inventory[0]["label"] == "SPEAKER_00"
    assert inventory[0]["samples"] == []
    assert inventory[0]["clean_example_available"] is False
    assert "Jag heter Anna" not in calls["question"]
    assert result.output.full_text == source


async def test_unknown_review_speaker_passes_readable_words_without_naming(harness):
    calls, activate = harness
    source = "[00:00:00 - 00:00:01] [Överlappande tal – osäker talare]: Hej."
    handler, _ = _handler(activate, prepared_text=source)
    state, previous = _state()
    from eneo.flows.domain.transcript_source import (
        TranscriptSourceBounds,
        TranscriptSourceOmissionReason,
        TranscriptSourceReference,
    )

    previous.input_payload_json["transcription"]["source"] = TranscriptSourceReference(
        run_id=uuid4(),
        step_id=previous.step_id,
        attempt_no=1,
        source_hash="a" * 64,
        bounds=TranscriptSourceBounds(
            segments_bytes=100,
            detail_bytes=3_000_000,
            words_bytes=0,
            segments_count=1,
            words_count=0,
            detail_omitted_reason=TranscriptSourceOmissionReason.TOO_LARGE,
        ),
    ).model_dump(mode="json")
    result = await handler.execute(
        step=_step(),
        run=SimpleNamespace(id=uuid4(), input_payload_json={}),
        state=state,
        version_metadata=None,
        attempt_no=1,
    )
    assert result.output.full_text == source
    assert result.output.structured_output == {"speakers": []}
    assert "question" not in calls
    assert result.output.output_payload_extensions["speaker_mapping"][
        "source_step_id"
    ] == str(previous.step_id)


@pytest.mark.parametrize("first_name", ["Agne", "Agne Hansson"])
async def test_inferred_names_are_grounded_before_renaming_or_persisting(
    harness, first_name
):
    calls, activate = harness
    source = "\n".join(
        [
            "[00:00:00 - 00:00:04] SPEAKER_00: Nu har Stefan Löfven stått här och inte gett besked.",
            "[00:00:05 - 00:00:09] SPEAKER_01: Behåll den där, Agne. Vi behöver en politisk överenskommelse.",
        ]
    )
    calls["structured"] = {
        "speakers": [
            {
                "label": "SPEAKER_00",
                "name": first_name,
                "confidence": "high",
                "evidence": "Tilltalas som Agne.",
            },
            {
                "label": "SPEAKER_01",
                "name": "Ibrahim Baylan",
                "confidence": "medium",
                "evidence": "Talar som ansvarig politiker om energi.",
            },
        ]
    }
    handler, persist = _handler(activate, prepared_text=source)
    state, _ = _state()
    run = SimpleNamespace(
        id=uuid4(),
        input_payload_json={
            "transkribering": inline_transcript(
                text=source,
                source_step_id=state.completed_by_order[1].step_id,
                source_attempt_no=3,
                selector_path=("output", "text"),
            ).model_dump(mode="json")
        },
    )
    result = await handler.execute(
        step=_step(output_config={"speaker_mapping": {"infer_names": True}}),
        run=run,
        state=state,
        version_metadata=None,
        attempt_no=1,
    )
    output = result.output
    assert [entry["name"] for entry in output.structured_output["speakers"]] == [
        "Agne" if first_name == "Agne" else None,
        None,
    ]
    assert "Ibrahim Baylan" not in output.full_text
    assert "Agne Hansson" not in output.full_text
    assert "SPEAKER_01: Behåll den där, Agne." in output.full_text
    assert output.structured_output["speakers"][1]["confidence"] == "low"
    assert output.structured_output["speakers"][1]["evidence"] == ""
    persist.assert_awaited_once()
    assert persist.await_args.args[1].text == output.full_text
