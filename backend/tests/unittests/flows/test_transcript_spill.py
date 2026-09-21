from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from eneo.audit.domain.action_types import ActionType
from eneo.files.file_models import FileContentVariant, FileInfo, FileType
from eneo.files.transcriber import TranscribedAudio
from eneo.flows.domain.flow import FlowRunStatus
from eneo.flows.domain.step_output import FileBackedStepText, interpret_step_text
from eneo.flows.domain.text_processing import SectionManifest
from eneo.flows.runtime.step_execution_runtime import build_output_payload
from eneo.flows.runtime.step_result_builder import build_completed_step_input_payload
from eneo.main.exceptions import TypedIOValidationException
from tests.unittests.flows import audio_spool_test_support
from tests.unittests.flows.test_flow_transcription import (
    _audio_file,
    _patch_run_input_payload,
    _SpaceStub,
    _state,
)
from tests.unittests.flows.test_typed_io_executor import (
    _build_executor,
    _completed_step_result,
    _mock_assistant_for_execute_step,
    _run,
    _runtime_step,
)

spool_contract = audio_spool_test_support.spool_contract


async def test_transcription_stages_an_exact_attempt_reference(spool_contract, user):
    executor, repo, run, files, assistant = _case(user, "Transcript.", spool_contract)
    step = _runtime_step(input_type="audio", output_mode="transcribe_only")
    resolved = await executor._resolve_step_input(
        run=run,
        step=step,
        context={"flow_input": {}},
        prior_results=[],
        state=_state(),
        requested_file_ids=list(files),
        attempt_no=3,
        version_metadata=_metadata(executor),
    )
    reference = resolved.transcription_metadata["source"]
    assert reference["run_id"] == str(run.id)
    assert reference["step_id"] == str(step.step_id)
    assert reference["attempt_no"] == 3
    assert reference["bounds"]["segments_omitted_reason"] == 2


async def test_per_source_audio_publishes_one_combined_attempt_source(
    spool_contract, user, monkeypatch
):
    from eneo.files.text import TEXT_EXTRACTION_WARNINGS
    from eneo.flows.domain.transcript_corrections import segments_content_hash
    from eneo.flows.infrastructure.flow_transcript_source_repo import (
        FlowTranscriptSourceRepository,
    )
    from eneo.transcription_models.infrastructure.adapters.litellm_transcription import (
        TranscriptSegment,
    )

    executor, repo, run, files, assistant = _case(user, "Transcript.", spool_contract)
    second = _audio_file(name="second.wav")
    files[second.id] = second
    repo.list_step_input_file_ids.return_value = list(files)
    executor.file_service.get_audio_download = spool_contract.downloads(
        list(files.values())
    )
    executor.transcriber.transcribe.side_effect = [
        TranscribedAudio(
            text, 10.0, transcript_segments=(TranscriptSegment(text, 0, 10),)
        )
        for text in ("First transcript.", "Second transcript.")
    ]
    assistant.get_response.side_effect = [
        SimpleNamespace(
            completion='{"documents":[{"title":"First"}]}', total_token_count=11
        ),
        SimpleNamespace(
            completion='{"documents":[{"title":"Second"}]}', total_token_count=13
        ),
    ]
    insert = AsyncMock()
    monkeypatch.setattr(FlowTranscriptSourceRepository, "insert", insert)
    step = _runtime_step(
        input_type="file",
        output_type="json",
        input_config={
            "runtime_input": {
                "enabled": True,
                "input_format": "audio",
                "execution_mode": "per_source",
                "max_files": 2,
            }
        },
        output_contract={
            "type": "object",
            "required": ["documents"],
            "additionalProperties": False,
            "properties": {
                "documents": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": [
                            "source_label",
                            "source_file_id",
                            "extraction_warnings",
                            "title",
                        ],
                        "properties": {
                            "source_label": {"type": "string"},
                            "source_file_id": {"type": "string"},
                            "title": {"type": "string"},
                            "extraction_warnings": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": sorted(TEXT_EXTRACTION_WARNINGS),
                                },
                            },
                        },
                    },
                }
            },
        },
    )
    await executor._execute_step(
        step=step,
        run=run,
        state=_state(),
        attempt_no=3,
        version_metadata=_metadata(executor),
    )
    assert executor.transcriber.transcribe.await_count == 2
    assert assistant.get_response.await_count == 2
    insert.assert_awaited_once()
    source = insert.await_args.kwargs["source"]
    assert [segment["text"] for segment in source.segments] == [
        "First transcript.",
        "Second transcript.",
    ]
    assert [segment["file_index"] for segment in source.segments] == [0, 1]
    assert source.source_hash == segments_content_hash(source.segments)
    assert source.bounds.segments_bytes == len(
        json.dumps(source.segments, ensure_ascii=False).encode("utf-8")
    )
    activated = repo.activate_step_attempt.await_args.kwargs[
        "attempt_input"
    ].to_payload()
    reference = activated["resolved_input"]["transcription"]["source"]
    assert reference["source_hash"] == source.source_hash
    assert reference["bounds"] == source.bounds.model_dump(mode="json")


def _case(user, text, spool_contract):
    executor, _, repo, _ = _build_executor(user, max_inline_text_bytes=2048)
    run = _run(status=FlowRunStatus.RUNNING, user=user, input_payload={})
    _patch_run_input_payload(repo, run)
    audio = _audio_file(name="meeting.wav")
    files = {audio.id: audio}
    references = []

    async def describe(*, file_ids):
        return [FileInfo.model_validate(files[file_id]) for file_id in file_ids]

    async def load(file_id):
        assert files[file_id].file_type is not FileType.AUDIO, (
            "Audio must use its download stream"
        )
        return files[file_id]

    async def save(**kwargs):
        payload = kwargs["payload"]
        file = audio.model_copy(
            update={
                "id": uuid4(),
                "name": kwargs["name"],
                "file_type": kwargs["file_type"],
                "mimetype": kwargs["mimetype"],
                "size": len(payload),
                "checksum": sha256(payload).hexdigest(),
                "blob": payload,
                "text": payload.decode("utf-8"),
            }
        )
        files[file.id] = file
        references.append(
            SimpleNamespace(
                file_id=file.id,
                variant=FileContentVariant.GENERATED_ARTIFACT,
                ordinal=0,
                size_bytes=len(payload),
                sha256=sha256(payload).digest(),
            )
        )
        return FileInfo.model_validate(file)

    executor.file_service.get_owned_file_infos.side_effect = describe
    executor.file_service.get_file_content.side_effect = load
    executor.file_service.get_audio_download = spool_contract.downloads([audio])
    executor.file_service.save_generated_file.side_effect = save
    executor.file_service.repo.get_content_references.side_effect = lambda ids: [
        ref for ref in references if ref.file_id in ids
    ]
    repo.list_step_input_file_ids.return_value = [audio.id]
    model = SimpleNamespace(
        id=uuid4(), name="whisper-1", model_name="whisper-1", can_access=True
    )
    executor.space_repo.get_space_by_assistant.return_value = _SpaceStub([model], model)
    executor.transcriber = SimpleNamespace(
        transcribe=AsyncMock(
            return_value=TranscribedAudio(text=text, duration_seconds=15000)
        )
    )
    assistant = _mock_assistant_for_execute_step()
    assistant.get_prompt_text.return_value = ""
    executor._load_assistant = AsyncMock(return_value=assistant)
    return executor, repo, run, files, assistant


@pytest.mark.parametrize("oversized", [False, True])
async def test_transcript_spills_once_and_persisted_inputs_are_bounded(
    spool_contract, user, oversized
):
    text = ("Å long meeting transcript.\n" * (200 if oversized else 2)).strip()
    executor, repo, run, files, assistant = _case(user, text, spool_contract)
    step = _runtime_step(input_type="audio", output_mode="transcribe_only")
    output = (
        await executor._execute_step(
            step=step,
            run=run,
            state=_state(),
            attempt_no=3,
            version_metadata=_metadata(executor),
        )
    ).output
    payload = build_output_payload(output)
    stored_input = build_completed_step_input_payload(output)
    activated = repo.activate_step_attempt.await_args.kwargs[
        "attempt_input"
    ].to_payload()
    assert output.full_text == text
    assistant.get_response.assert_not_awaited()
    if not oversized:
        executor.file_service.save_generated_file.assert_not_awaited()
        assert run.input_payload_json["transkribering"] == text
        assert stored_input["runtime_input"]["text"] == text
        assert payload["text"] == text
        assert "text_overflow" not in payload
        return

    executor.file_service.save_generated_file.assert_awaited_once()
    saved = executor.file_service.save_generated_file.await_args.kwargs
    assert saved["payload"] == text.encode("utf-8")
    assert saved["file_type"] == FileType.TEXT
    assert saved["mimetype"] == "text/plain"
    reference = FileBackedStepText.model_validate(
        run.input_payload_json["transkribering"]
    )
    assert reference.source_step_id == step.step_id
    assert reference.source_attempt_no == 3
    assert reference.checksum == sha256(text.encode("utf-8")).hexdigest()
    assert files[reference.file_id].text == text
    assert stored_input["runtime_input"]["text"] == reference.model_dump(mode="json")
    assert isinstance(payload["text"], str)
    assert interpret_step_text(payload).file_id == reference.file_id
    assert output.generated_file_ids == [reference.file_id]
    for record in (run.input_payload_json, stored_input, activated, payload):
        assert text not in json.dumps(record, ensure_ascii=False)
        _assert_bounded_text(record, executor.max_inline_text_bytes)


def _metadata(executor):
    model = executor.space_repo.get_space_by_assistant.return_value.get_default_transcription_model()
    return {
        "wizard": {
            "transcription_enabled": True,
            "transcription_model": {"id": str(model.id)},
        }
    }


@pytest.mark.parametrize("oversized", [False, True])
async def test_transcript_audit_records_produced_character_count(
    spool_contract, user, oversized
):
    text = "Å long meeting transcript.\n" * (200 if oversized else 2)
    executor, _, run, _, _ = _case(user, text, spool_contract)
    executor.audit_service = AsyncMock()
    await executor._execute_step(
        step=_runtime_step(input_type="audio", output_mode="transcribe_only"),
        run=run,
        state=_state(),
        attempt_no=1,
        version_metadata=_metadata(executor),
    )
    audits = [
        call.kwargs
        for call in executor.audit_service.log_async.await_args_list
        if call.kwargs["action"] == ActionType.FLOW_RUN_AUDIO_TRANSCRIBED
    ]
    assert len(audits) == 1
    assert audits[0]["metadata"]["extra"]["text_length"] == len(text.strip())
    assert isinstance(run.input_payload_json["transkribering"], dict) == oversized


@pytest.mark.parametrize("oversized", [False, True])
@pytest.mark.parametrize("prefix", ["", "Meeting notes\n"])
async def test_transcribe_only_binding_preserves_output_and_artifact_identity(
    spool_contract, user, oversized, prefix
):
    text = ("Bound transcript.\n" * (200 if oversized else 2)).strip()
    executor, repo, run, files, assistant = _case(user, text, spool_contract)
    step = _runtime_step(
        input_type="audio",
        output_mode="transcribe_only",
        input_bindings={"question": prefix + "{{step_input.text}}"},
    )
    output = (
        await executor._execute_step(
            step=step,
            run=run,
            state=_state(),
            attempt_no=1,
            version_metadata=_metadata(executor),
        )
    ).output
    expected = prefix + text
    assert output.full_text == expected
    payload = build_output_payload(output)
    persisted = interpret_step_text(payload)
    if not oversized:
        assert persisted.text == expected
        assert run.input_payload_json["transkribering"] == text
        executor.file_service.save_generated_file.assert_not_awaited()
        return

    reference = FileBackedStepText.model_validate(
        run.input_payload_json["transkribering"]
    )
    assert files[reference.file_id].blob == text.encode("utf-8")
    assert reference.checksum == sha256(text.encode("utf-8")).hexdigest()
    assert files[persisted.file_id].text == expected
    assert persisted.full_text_bytes == len(files[persisted.file_id].blob)
    output_checksum = sha256(files[persisted.file_id].blob).hexdigest()
    assert output_checksum == sha256(expected.encode("utf-8")).hexdigest()
    if prefix:
        assert persisted.file_id != reference.file_id
        assert output_checksum != reference.checksum
    else:
        assert persisted.file_id == reference.file_id
        assert output_checksum == reference.checksum
    assert executor.file_service.save_generated_file.await_count == (2 if prefix else 1)

    previous = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text=payload["text"],
        text_overflow=payload["text_overflow"],
    ).model_copy(update={"step_id": step.step_id})
    repo.list_step_input_file_ids.return_value = []
    for binding, selected_text, file_id, checksum in (
        (None, expected, persisted.file_id, output_checksum),
        ("{{transkribering}}", text, reference.file_id, reference.checksum),
        (
            "{{step_1.output.text}}\n{{transkribering}}\n{{transkribering}}",
            expected + "\n" + text + "\n" + text,
            None,
            None,
        ),
    ):
        assistant.get_prompt_text.return_value = (
            "Raw: {{transkribering}}\nOutput: {{step_1.output.text}}"
            if file_id is None
            else ""
        )
        state = _state()
        state.prior_results = [previous]
        state.completed_by_order = {1: previous}
        next_step = _runtime_step(
            step_order=2,
            input_source="previous_step",
            input_bindings={"question": binding} if binding else None,
        )
        result = await executor._execute_step(
            step=next_step, run=run, state=state, attempt_no=1
        )
        assert result.output.input_text == selected_text
        assert assistant.get_response.await_args.kwargs["question"] == selected_text
        expected_files = (
            {file_id: checksum}
            if file_id is not None
            else {
                persisted.file_id: output_checksum,
                reference.file_id: reference.checksum,
            }
        )
        aliases = [
            FileBackedStepText.model_validate(alias)
            for alias in build_completed_step_input_payload(result.output)[
                "material_aliases"
            ]
        ]
        assert len(result.output.materials) == len(aliases) == len(expected_files)
        assert {alias.file_id: alias.checksum for alias in aliases} == expected_files
        if file_id is None:
            assert assistant.get_response.await_args.kwargs[
                "prompt_override"
            ].startswith("Raw: " + text + "\nOutput: " + expected)
    if prefix:
        section_step = replace(
            next_step,
            input_config={"text_processing": {"mode": "process_each_section"}},
        )
        with pytest.raises(
            TypedIOValidationException,
            match="Section processing requires exactly one file-backed material",
        ) as caught:
            await executor._resolve_step_input(
                step=section_step,
                run=run,
                context={},
                prior_results=[previous],
                state=state,
            )
        assert caught.value.code == "typed_io_invalid_input_source_combination"
    assert files[reference.file_id].blob == text.encode("utf-8")
    assert executor.file_service.save_generated_file.await_count == (2 if prefix else 1)


async def test_reused_and_fresh_transcript_artifacts_persist_the_same_inline_text(
    spool_contract, user
):
    text = "åäö" * 800
    prefix = "Notes: "
    expected = prefix + text
    payloads = []
    for transcript, binding, writes in (
        (expected, "{{step_input.text}}", 1),
        (text, prefix + "{{step_input.text}}", 2),
    ):
        executor, _, run, files, _ = _case(user, transcript, spool_contract)
        step = _runtime_step(
            input_type="audio",
            output_mode="transcribe_only",
            input_bindings={"question": binding},
        )
        output = (
            await executor._execute_step(
                step=step,
                run=run,
                state=_state(),
                attempt_no=1,
                version_metadata=_metadata(executor),
            )
        ).output
        payload = build_output_payload(output)
        persisted = interpret_step_text(payload)
        assert files[persisted.file_id].blob == expected.encode("utf-8")
        assert executor.file_service.save_generated_file.await_count == writes
        payloads.append(payload)

    assert payloads[0]["text"].encode("utf-8") == payloads[1]["text"].encode("utf-8")
    expected_inline = expected.encode("utf-8")[:2048].decode("utf-8", errors="ignore")
    for payload in payloads:
        assert payload["text"] == expected_inline
        assert payload["text_overflow"]["inline_text_bytes"] == len(
            expected_inline.encode("utf-8")
        )
        assert payload["text_overflow"]["full_text_bytes"] == len(
            expected.encode("utf-8")
        )


def _assert_bounded_text(value, cap):
    if isinstance(value, str):
        assert len(value.encode("utf-8")) <= cap
    elif isinstance(value, dict):
        for child in value.values():
            _assert_bounded_text(child, cap)
    elif isinstance(value, list):
        for child in value:
            _assert_bounded_text(child, cap)


@pytest.mark.parametrize(
    "binding",
    [
        None,
        "{{transkribering}}",
        "{{flow_input.transkribering}}",
        "{{flow_input}}",
        "{{flow.input}}",
    ],
)
async def test_next_step_reads_complete_spilled_transcript(
    spool_contract, user, binding
):
    text = ("Complete transcript åäö.\n" * 200).strip()
    executor, repo, run, _, assistant = _case(user, text, spool_contract)
    step = _runtime_step(input_type="audio", output_mode="transcribe_only")
    output = (
        await executor._execute_step(
            step=step,
            run=run,
            state=_state(),
            attempt_no=3,
            version_metadata=_metadata(executor),
        )
    ).output
    payload = build_output_payload(output)
    previous = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text=payload["text"],
        text_overflow=payload["text_overflow"],
    ).model_copy(update={"step_id": step.step_id, "current_attempt_no": 3})
    state = _state()
    state.prior_results = [previous]
    state.completed_by_order = {1: previous}
    repo.list_step_input_file_ids.return_value = []
    next_step = _runtime_step(
        step_order=2,
        input_source="previous_step",
        input_bindings={"question": binding} if binding else None,
    )
    result = await executor._execute_step(
        step=next_step, run=run, state=state, attempt_no=1
    )
    if binding in {"{{flow_input}}", "{{flow.input}}"}:
        assert result.output.input_text == "transkribering: " + text
    else:
        assert result.output.input_text == text
    assert (
        assistant.get_response.await_args.kwargs["question"] == result.output.input_text
    )
    assert len(result.output.materials) == 1
    executor.file_service.save_generated_file.assert_awaited_once()


@pytest.mark.parametrize("binding", [None, "{{transkribering}}"])
async def test_transcript_and_previous_step_select_one_section_material(user, binding):
    from eneo.flows.domain.step_output import (
        ResolvedStepMaterial,
        build_step_material_aliases,
    )
    from tests.unittests.flows.test_text_sections import _case as section_case

    executor, _, assistant, run, state, step, text, file, questions, _ = section_case(
        user, prompt="Current section: {{transkribering}}"
    )
    source = state.prior_results[0]
    run.input_payload_json = {
        "transkribering": build_step_material_aliases(
            materials=(
                ResolvedStepMaterial(
                    source_step_id=source.step_id,
                    source_attempt_no=source.current_attempt_no,
                    file_id=file.id,
                    checksum=file.checksum,
                    byte_size=len(text.encode()),
                    text=text,
                ),
            ),
            max_inline_bytes=2048,
        )[0].model_dump(mode="json")
    }
    step = replace(step, input_bindings={"question": binding} if binding else None)
    result = await executor._execute_step(step=step, run=run, state=state, attempt_no=1)
    manifest = SectionManifest.model_validate(
        result.output.output_payload_extensions["section_manifest"]
    )
    sections = manifest.resplit(text)
    assert len(sections) > 1
    assert len(manifest.sources) == len(result.output.materials) == 1
    assert tuple(questions) == sections
    for section, call in zip(
        sections, assistant.get_response.await_args_list, strict=True
    ):
        assert call.kwargs["prompt_override"].startswith("Current section: " + section)
        assert text not in call.kwargs["prompt_override"]
    executor.file_service.get_file_content.assert_awaited_once()


async def test_failed_transcript_attempt_keeps_only_bounded_inputs(
    spool_contract, user
):
    text = ("Long transcript for a failed completion.\n" * 200).strip()
    executor, repo, run, _, assistant = _case(user, text, spool_contract)
    executor._process_typed_output = AsyncMock(
        side_effect=TypedIOValidationException(
            "Completion rejected", code="typed_io_contract_violation"
        )
    )
    step = _runtime_step(input_type="audio")
    state = _state()
    with pytest.raises(
        TypedIOValidationException, match="Completion rejected"
    ) as caught:
        await executor._execute_step(
            step=step,
            run=run,
            state=state,
            attempt_no=2,
            version_metadata=_metadata(executor),
        )
    failed_input = caught.value.input_payload_json
    activated = repo.activate_step_attempt.await_args.kwargs[
        "attempt_input"
    ].to_payload()
    for record in (failed_input, activated, run.input_payload_json):
        _assert_bounded_text(record, executor.max_inline_text_bytes)
        assert text not in json.dumps(record, ensure_ascii=False)
    reference = FileBackedStepText.model_validate(failed_input["runtime_input"]["text"])
    assert reference.source_attempt_no == 2
    executor.file_service.save_generated_file.assert_awaited_once()
    claimed = _completed_step_result(
        run_id=run.id,
        flow_id=run.flow_id,
        tenant_id=run.tenant_id,
        step_order=1,
        text="",
    ).model_copy(
        update={"step_id": step.step_id, "current_attempt_no": 2, "status": "running"}
    )
    await executor._handle_typed_step_failure(
        run_id=run.id,
        tenant_id=run.tenant_id,
        step=step,
        attempt_no=2,
        claimed=claimed,
        typed_exc=caught.value,
        failed_input_payload=failed_input,
        state=state,
    )
    saved = repo.save_step_result.await_args.args[1]
    terminal = repo.finish_attempt.await_args.kwargs["attempt_input"].to_payload()
    assert saved.input_payload_json["runtime_input"]["text"] == reference.model_dump(
        mode="json"
    )
    for record in (saved.model_dump(mode="json"), terminal):
        _assert_bounded_text(record, executor.max_inline_text_bytes)
        assert text not in json.dumps(record, ensure_ascii=False)


@pytest.mark.parametrize("oversized", [False, True])
async def test_spilled_transcript_is_durable_before_input_binding_failure(
    spool_contract, user, oversized
):
    text = "Long transcript.\n" * (200 if oversized else 2)
    executor, repo, run, files, _ = _case(user, text, spool_contract)
    step = _runtime_step(
        input_type="audio", input_bindings={"question": "{{missing_variable}}"}
    )

    async def commit():
        reference = FileBackedStepText.model_validate(
            run.input_payload_json["transkribering"]
        )
        assert files[reference.file_id].blob == text.strip().encode("utf-8")
        assert repo.update_input_payload.await_count == 1

    executor.session.commit.side_effect = commit
    with pytest.raises(TypedIOValidationException):
        await executor._execute_step(
            step=step,
            run=run,
            state=_state(),
            attempt_no=1,
            version_metadata=_metadata(executor),
        )
    repo.activate_step_attempt.assert_not_awaited()
    assert executor.session.commit.await_count == int(oversized)
