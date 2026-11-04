"""The visitor's turn preparation and attachments marked "open with tool"."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import eneo.assistants.assistant_service as assistant_service_mod
import eneo.files.file_reference as file_reference_mod
from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant
from eneo.assistants.assistant_service import AssistantService
from eneo.files.file_models import FileType
from eneo.main.exceptions import BadRequestException

MODEL = SimpleNamespace(
    supports_tool_calling=True, vision=False, max_input_tokens=8_000, name="gpt-4"
)


@pytest.fixture(autouse=True)
def _reference_base_url(monkeypatch):
    monkeypatch.setattr(
        file_reference_mod,
        "get_settings",
        lambda: SimpleNamespace(
            file_reference_base_url="http://host.docker.internal:8123",
            public_origin=None,
        ),
    )


def _attachment():
    return MagicMock(
        id=uuid4(),
        file_type=FileType.TEXT,
        mimetype="text/plain",
        size=1,
        text="Avgiften f\u00f6r bygglov \u00e4r 4 500 kronor.",
        original_available=True,
        parent_file_id=None,
    )


def _assistant(attachment, *, open_with_tool: bool):
    return Assistant(
        id=uuid4(),
        user=MagicMock(),
        name="a",
        space_id=uuid4(),
        prompt=None,
        completion_model=None,
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        websites=[],
        collections=[],
        attachments=[attachment],
        attachment_inline_text={attachment.id: not open_with_tool},
        published=False,
    )


def _service():
    service = AssistantService.__new__(AssistantService)
    service.file_service = MagicMock()  # type: ignore[assignment]
    service.file_service.with_derived_images = AsyncMock(
        side_effect=lambda files: files
    )
    return service


async def test_an_open_with_tool_attachment_inlines_for_a_visitor_when_it_fits(
    monkeypatch,
):
    attachment = _attachment()
    assistant = _assistant(attachment, open_with_tool=True)
    fit = MagicMock()
    monkeypatch.setattr(
        assistant_service_mod, "assert_prompt_and_files_fit_context", fit
    )

    await _service()._inline_attachments_for_visitor(assistant, MODEL, "Svara kort.")

    assert assistant.url_only_attachment_ids(MODEL) == set()
    # Judged as the completion will send it: the attachment inlined, with the prompt.
    assert fit.call_args.kwargs["files"] == [attachment]
    assert fit.call_args.kwargs["prompt_text"] == "Svara kort."
    assert fit.call_args.kwargs["max_input_tokens"] == 8_000


async def test_an_oversized_attachment_stays_a_link_rather_than_closing_the_widget(
    monkeypatch,
):
    attachment = _attachment()
    assistant = _assistant(attachment, open_with_tool=True)
    monkeypatch.setattr(
        assistant_service_mod,
        "assert_prompt_and_files_fit_context",
        MagicMock(side_effect=BadRequestException("too large")),
    )
    logger = MagicMock()
    monkeypatch.setattr(assistant_service_mod, "logger", logger)

    await _service()._inline_attachments_for_visitor(assistant, MODEL, "Svara kort.")

    assert assistant.url_only_attachment_ids(MODEL) == {attachment.id}
    logger.warning.assert_called_once()
    assert "would not fit" in logger.warning.call_args.args[0]


async def test_inlined_attachments_need_no_decision(monkeypatch):
    attachment = _attachment()
    assistant = _assistant(attachment, open_with_tool=False)
    fit = MagicMock()
    monkeypatch.setattr(
        assistant_service_mod, "assert_prompt_and_files_fit_context", fit
    )

    await _service()._inline_attachments_for_visitor(assistant, MODEL, "Svara kort.")

    fit.assert_not_called()
    assert assistant.url_only_attachment_ids(MODEL) == set()
