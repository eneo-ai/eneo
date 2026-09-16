from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.domain.step_output import (
    FileBackedStepText,
    InlineStepText,
    RejectedOutput,
    StepOutputMetadataError,
    build_rejected_output_payload,
    interpret_rejected_output,
    interpret_step_text,
)


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
