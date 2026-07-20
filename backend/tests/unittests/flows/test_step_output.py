from __future__ import annotations

from uuid import uuid4

import pytest

from eneo.flows.domain.step_output import (
    FileBackedStepText,
    InlineStepText,
    StepOutputMetadataError,
    interpret_step_text,
)


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
