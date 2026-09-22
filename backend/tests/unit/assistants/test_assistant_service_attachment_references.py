"""URL-only persistent attachments through the assistant service.

An attachment marked "open with tool" is sent as a signed reference URL, so
its text and rendered pages must stay out of every context counter and the
loopback files server must attach for it, exactly as for URL-only uploads.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

import eneo.files.file_reference as file_reference_mod
from eneo.assistants.assistant_service import AssistantService
from eneo.files.file_models import FileType


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


def _file(file_type=FileType.TEXT, *, parent_file_id=None, name="kontoplan.xlsx"):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        file_type=file_type,
        original_available=True,
        parent_file_id=parent_file_id,
        text="a" * 10,
        blob=None,
        size=10,
        mimetype="text/plain",
    )


def _model(*, vision=True):
    return SimpleNamespace(vision=vision, supports_tool_calling=True)


def _assistant(attachments, url_only):
    return SimpleNamespace(
        attachments=attachments,
        inline_file_text=True,
        url_only_attachment_ids=lambda model: set(url_only),
    )


@pytest.mark.asyncio
async def test_prompt_files_drop_pages_rendered_from_url_only_attachments():
    kontoplan, guide = _file(), _file(name="guide.pdf")
    kontoplan_page = _file(FileType.IMAGE, parent_file_id=kontoplan.id)
    guide_page = _file(FileType.IMAGE, parent_file_id=guide.id)
    service = MagicMock()
    service.file_service.with_derived_images = AsyncMock(
        return_value=[kontoplan, guide, kontoplan_page, guide_page]
    )

    result = await AssistantService._completion_prompt_files_for_model(
        service,
        persistent_attachments=[kontoplan, guide],
        completion_model=_model(),
        url_only_ids={kontoplan.id},
    )

    # The URL-only document itself stays (the send path mints its reference);
    # only its rendered pages are withheld.
    assert result == [kontoplan, guide, guide_page]


@pytest.mark.asyncio
async def test_message_fit_guard_ignores_url_only_attachments(monkeypatch):
    kontoplan, guide = _file(), _file(name="guide.pdf")
    counted = {}

    def fake_assert(**kwargs):
        counted["files"] = kwargs["files"]

    monkeypatch.setattr(
        "eneo.assistants.assistant_service.assert_prompt_and_files_fit_context",
        fake_assert,
    )
    service = MagicMock()
    service._completion_prompt_files_for_model = AsyncMock(
        return_value=[kontoplan, guide]
    )
    service.file_service.with_derived_images = AsyncMock(side_effect=lambda f: f)

    await AssistantService._assert_message_attachments_fit(
        service,
        assistant=_assistant([kontoplan, guide], {kontoplan.id}),
        model=SimpleNamespace(max_input_tokens=1000, name="gpt-4o", vision=False),
        prompt_text="",
        files=[],
        validate_persistent_baseline=True,
    )

    assert counted["files"] == [guide]
    service._completion_prompt_files_for_model.assert_awaited_once()
    assert service._completion_prompt_files_for_model.await_args.kwargs[
        "url_only_ids"
    ] == {kontoplan.id}


@pytest.mark.asyncio
async def test_completion_file_inputs_pass_url_only_attachments_to_pruning():
    kontoplan = _file()
    service = MagicMock()
    service._completion_prompt_files_for_model = AsyncMock(return_value=[kontoplan])
    service._attach_history_derivatives = AsyncMock()
    service.file_service.with_derived_images = AsyncMock(return_value=[])

    result = await AssistantService._build_completion_file_inputs(
        service,
        files=[],
        session=SimpleNamespace(questions=[]),
        assistant=_assistant([kontoplan], {kontoplan.id}),
        completion_model=_model(),
    )

    assert result.completion_prompt_files == [kontoplan]
    assert service._completion_prompt_files_for_model.await_args.kwargs[
        "url_only_ids"
    ] == {kontoplan.id}
