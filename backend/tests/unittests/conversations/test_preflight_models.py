from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from eneo.conversations.conversation_models import PreflightRequest


def test_preflight_request_rejects_multiple_targets():
    """Exactly one of session/assistant/group_chat — multiple is rejected."""
    with pytest.raises(ValidationError):
        PreflightRequest(
            question="hi",
            session_id=uuid4(),
            assistant_id=uuid4(),
        )


def test_preflight_request_rejects_no_target():
    """At least one target is required."""
    with pytest.raises(ValidationError):
        PreflightRequest(question="hi")


def test_preflight_request_rejects_empty_input():
    """Empty question with no files is meaningless — must be rejected."""
    with pytest.raises(ValidationError):
        PreflightRequest(assistant_id=uuid4())


def test_preflight_request_accepts_question_only():
    """A non-empty question alone is enough."""
    req = PreflightRequest(question="hi", assistant_id=uuid4())
    assert req.question == "hi"
    assert req.file_ids == []


def test_preflight_request_accepts_files_only():
    """Files without a question are also OK (e.g. user is about to write)."""
    file_id = uuid4()
    req = PreflightRequest(assistant_id=uuid4(), file_ids=[file_id])
    assert req.question == ""
    assert req.file_ids == [file_id]


def test_preflight_request_rejects_too_many_files():
    """The 50-file cap bounds preflight DB + tokenization work."""
    with pytest.raises(ValidationError):
        PreflightRequest(
            question="x",
            assistant_id=uuid4(),
            file_ids=[uuid4() for _ in range(51)],
        )
