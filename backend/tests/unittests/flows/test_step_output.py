from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.flows.domain.step_output import (
    FileBackedStepText,
    InlineStepText,
    RejectedOutput,
    StepOutputMetadataError,
    build_rejected_output_payload,
    interpret_rejected_output,
    interpret_step_text,
    sample_rejected_output,
)


@pytest.mark.parametrize(
    "updates,message",
    [
        ({"inline_text_bytes": 1}, "preview size does not match"),
        ({"full_text_bytes": 2}, "preview must be smaller"),
        ({"source_step_id": uuid4()}, "both step and attempt"),
        ({"source_attempt_no": 1}, "both step and attempt"),
    ],
)
def test_file_backed_alias_rejects_incoherent_preview_or_source(updates, message):
    payload = {
        "preview": "å",
        "file_id": uuid4(),
        "inline_text_bytes": 2,
        "full_text_bytes": 3,
    }
    assert FileBackedStepText.model_validate(payload).preview == "å"
    with pytest.raises(ValidationError, match=message):
        FileBackedStepText.model_validate({**payload, **updates})


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", RejectedOutput("", False)), ("aåö", RejectedOutput("aå", True))],
)
def test_rejected_output_is_bounded_evidence_not_step_text(
    text: str, expected: RejectedOutput
) -> None:
    payload = build_rejected_output_payload(text, max_inline_bytes=4)
    assert interpret_rejected_output(payload) == expected
    assert interpret_rejected_output(None) is None
    assert interpret_rejected_output({"text": "completed"}) is None
    with pytest.raises(StepOutputMetadataError):
        interpret_step_text(payload)


def test_interpret_step_text_accepts_complete_inline_text() -> None:
    assert interpret_step_text({"text": "Complete text"}) == InlineStepText(
        text="Complete text"
    )


@pytest.mark.parametrize("unit", ["å猫🙂", '\\"\n\x00'])
def test_rejection_samples_bound_utf8_and_json_escaping(unit: str) -> None:
    text = unit * 16384
    output = sample_rejected_output(text, max_inline_bytes=1024)
    assert output is not None
    payload = output.to_payload()
    assert len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) <= 1024
    assert output.evidence is not None
    assert output.text and text.startswith(output.text)
    assert output.evidence.tail and text.endswith(output.evidence.tail)
    assert output.evidence.observed_bytes == len(text.encode("utf-8"))
    assert output.evidence.sha256 == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert output.evidence.sampling_status == "sampled"
    assert interpret_rejected_output(payload) == output


def test_interpret_step_text_accepts_one_overflow_file_and_bounded_preview() -> None:
    file_id = uuid4()

    assert interpret_step_text(
        {
            "text": "Bounded preview",
            "text_overflow": {
                "generated_file_ids": [str(file_id)],
                "inline_text_bytes": 15,
                "full_text_bytes": 30,
            },
        }
    ) == FileBackedStepText(
        preview="Bounded preview",
        file_id=file_id,
        inline_text_bytes=15,
        full_text_bytes=30,
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"text": 123},
        {"text": "preview", "text_overflow": None},
        {"text": "preview", "text_overflow": []},
        {"text": "preview", "text_overflow": {}},
        {
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": [],
                "inline_text_bytes": 7,
                "full_text_bytes": 8,
            },
        },
        {
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": [str(uuid4()), str(uuid4())],
                "inline_text_bytes": 7,
                "full_text_bytes": 8,
            },
        },
        {
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": [str(uuid4())] * 2,
                "inline_text_bytes": 7,
                "full_text_bytes": 8,
            },
        },
        {
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": ["not-a-uuid"],
                "inline_text_bytes": 7,
                "full_text_bytes": 8,
            },
        },
        {
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": [uuid4()],
                "inline_text_bytes": 7,
                "full_text_bytes": 8,
            },
        },
        {
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": [str(uuid4())],
                "inline_text_bytes": True,
                "full_text_bytes": 8,
            },
        },
        {
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": [str(uuid4())],
                "inline_text_bytes": 6,
                "full_text_bytes": 8,
            },
        },
        {
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": [str(uuid4())],
                "inline_text_bytes": 7,
                "full_text_bytes": 7,
            },
        },
        {
            "text": "preview",
            "text_overflow": {
                "generated_file_ids": [str(uuid4())],
                "inline_text_bytes": 7,
                "full_text_bytes": 8,
                "unexpected": "compatibility",
            },
        },
    ],
)
def test_interpret_step_text_rejects_malformed_persisted_metadata(
    payload: dict[str, object],
) -> None:
    with pytest.raises(StepOutputMetadataError):
        interpret_step_text(payload)
