from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.flows.domain.runtime import StepExecutionOutput, StepInputValue
from eneo.flows.domain.speaker_labels import SPEAKER_MAPPING_OUTPUT_CONTRACT
from eneo.flows.domain.step_output import inline_transcript
from eneo.flows.output_processing import validate_against_contract
from eneo.flows.runtime.step_execution_runtime import (
    PreparedCompletionCall,
    PreparedStepExecution,
    StepExecutionRuntimeDeps,
)
from eneo.flows.runtime.step_handlers import speaker_mapping as handler_module
from eneo.flows.runtime.step_handlers.base import PreparedAssistantStep
from eneo.flows.runtime.step_handlers.speaker_mapping import SpeakerMappingStepHandler
from eneo.main.exceptions import TypedIOValidationException

SOURCE = "\n".join(
    [
        "[00:00:00 - 00:00:04] SPEAKER_00: Hej, jag heter Anna.",
        "[00:00:05 - 00:00:09] SPEAKER_01: Hej Anna, Bo här.",
    ]
)
PROPOSAL = {
    "speakers": [
        {
            "label": "SPEAKER_00",
            "name": "Anna",
            "confidence": "high",
            "evidence": "intro",
        },
        {"label": "SPEAKER_01", "name": None, "confidence": "low", "evidence": ""},
    ]
}


def _step(**overrides):
    base = dict(
        step_id=uuid4(),
        step_order=2,
        input_source="previous_step",
        input_type="text",
        output_type="json",
        output_mode="speaker_mapping",
        output_config={"speaker_mapping": {"participants_field": "deltagare"}},
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _prepared(text: str) -> PreparedStepExecution:
    return PreparedStepExecution(
        assistant=SimpleNamespace(),
        step_input=StepInputValue(text=text, input_source="previous_step"),
        effective_prompt="Du är en assistent.",
        input_payload_for_result={},
        contract_validation=None,
        diagnostics=[],
        llm_files=[],
    )


def _deps(max_inline_text_bytes: int | None = 10_000) -> StepExecutionRuntimeDeps:
    return StepExecutionRuntimeDeps(
        variable_resolver=SimpleNamespace(),  # type: ignore[arg-type]
        completion_service=SimpleNamespace(),  # type: ignore[arg-type]
        load_assistant=AsyncMock(),
        resolve_step_input=AsyncMock(),
        retrieve_rag_chunks=AsyncMock(),
        process_typed_output=AsyncMock(),
        apply_output_cap=AsyncMock(side_effect=lambda *, text, run, step: (text, [])),
        max_inline_text_bytes=max_inline_text_bytes,
    )


def _output(structured) -> StepExecutionOutput:
    return StepExecutionOutput(
        input_text="q",
        source_text="",
        input_source="previous_step",
        used_question_binding=False,
        full_text="{}",
        persisted_text="{}",
        generated_file_ids=[],
        tool_calls_metadata=None,
        num_tokens_input=1,
        num_tokens_output=1,
        effective_prompt="",
        model_parameters_json={},
        structured_output=structured,
    )


@pytest.fixture
def harness(monkeypatch):
    calls: dict[str, object] = {}

    def fake_call(*, step, state, prepared):
        calls["question"] = prepared.step_input.text
        calls["prompt"] = prepared.effective_prompt
        return PreparedCompletionCall(
            question=prepared.step_input.text,
            effective_prompt=prepared.effective_prompt,
            preferred_model_kwargs=SimpleNamespace(),  # type: ignore[arg-type]
            preferred_model_parameters={},
            capability_fallback_model_kwargs=None,
            capability_fallback_model_parameters=None,
            assistant_context_version=1,
            preferred_native_json_format=False,
        )

    monkeypatch.setattr(handler_module, "build_prepared_completion_call", fake_call)

    async def fake_complete(*, step, run, state, prepared, deps):
        calls["deps"] = deps
        structured = calls.get("structured", PROPOSAL)
        validate_against_contract(
            structured, SPEAKER_MAPPING_OUTPUT_CONTRACT, label="Step 2 output"
        )
        return _output(structured)

    monkeypatch.setattr(handler_module, "complete_step_execution", fake_complete)

    async def activate(run, step, state, attempt_no, prepared_steps):
        calls["activated"] = prepared_steps
        return tuple(prepared_steps)

    return calls, activate


def _handler(activate, prepared_text: str = SOURCE, deps=None):
    from eneo.flows.domain.transcript_source import transcript_source_reference

    preview = AsyncMock(
        return_value=PreparedAssistantStep(
            prepared=_prepared(prepared_text), deps=deps or _deps()
        )
    )
    persist = AsyncMock()
    return (
        SpeakerMappingStepHandler(
            preview_assistant_step=preview,
            activate_prepared_assistant_steps=activate,
            activate_resolved_input_edges=AsyncMock(),
            persist_transcript=persist,
            transcript_source_for_step=AsyncMock(
                side_effect=lambda run, previous: transcript_source_reference(
                    previous.input_payload_json
                )
            ),
        ),
        persist,
    )


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
