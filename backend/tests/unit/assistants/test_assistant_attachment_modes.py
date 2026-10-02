"""Per-attachment inlining mode on the Assistant entity.

Each persistent attachment is either placed in the prompt (default) or marked
"open with tool", in which case the model gets a signed reference URL instead
of the text. The mode lives next to the attachment list and must never outlive
the attachment it describes.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import eneo.files.file_reference as file_reference_mod
from eneo.ai_models.completion_models.completion_model import ModelKwargs
from eneo.assistants.assistant import Assistant
from eneo.files.file_models import FileType
from eneo.main.exceptions import BadRequestException


def _attachment(*, stored: bool = True):
    return MagicMock(
        id=uuid4(),
        file_type=FileType.TEXT,
        mimetype="text/plain",
        size=1,
        original_available=stored,
        parent_file_id=None,
    )


def _assistant(attachments, modes=None):
    return Assistant(
        id=None,
        user=MagicMock(),
        name="a",
        space_id=uuid4(),
        prompt=None,
        completion_model=None,
        completion_model_kwargs=ModelKwargs(),
        logging_enabled=False,
        websites=[],
        collections=[],
        attachments=attachments,
        attachment_inline_text=modes,
        published=False,
    )


def _model(*, tools: bool = True):
    return SimpleNamespace(supports_tool_calling=tools)


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


def test_missing_mode_means_inlined():
    kontoplan = _attachment()
    assistant = _assistant([kontoplan])

    assert assistant.attachment_inline_text == {}
    assert assistant.url_only_attachment_ids(_model()) == set()


def test_open_with_tool_attachment_is_url_only_for_tool_capable_model():
    kontoplan, guide = _attachment(), _attachment()
    assistant = _assistant([kontoplan, guide], {kontoplan.id: False})

    assert assistant.url_only_attachment_ids(_model()) == {kontoplan.id}


def test_model_without_tool_calling_inlines_everything():
    kontoplan = _attachment()
    assistant = _assistant([kontoplan], {kontoplan.id: False})

    assert assistant.url_only_attachment_ids(_model(tools=False)) == set()


def test_attachment_without_stored_original_inlines_despite_mode():
    legacy = _attachment(stored=False)
    assistant = _assistant([legacy], {legacy.id: False})

    assert assistant.url_only_attachment_ids(_model()) == set()


def test_replacing_attachments_drops_modes_of_removed_files():
    kontoplan, guide = _attachment(), _attachment()
    assistant = _assistant([kontoplan, guide], {kontoplan.id: False, guide.id: True})

    assistant.attachments = [guide]

    assert assistant.attachment_inline_text == {guide.id: True}


def test_update_replaces_modes_for_the_new_attachment_set():
    kontoplan, guide = _attachment(), _attachment()
    assistant = _assistant([kontoplan], {kontoplan.id: False})

    assistant.update(
        attachments=[kontoplan, guide],
        attachment_inline_text={kontoplan.id: True, guide.id: False},
    )

    assert assistant.attachment_inline_text == {kontoplan.id: True, guide.id: False}


def test_mode_for_unattached_file_is_rejected():
    kontoplan = _attachment()
    assistant = _assistant([kontoplan])

    with pytest.raises(BadRequestException):
        assistant.set_attachment_inline_text({uuid4(): False})
