"""Public projection of persistent attachments.

The editor shows the "open with tool" control only for attachments a signed
reference URL can serve, and it needs each attachment's current mode.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

from eneo.assistants.api.assistant_assembler import AssistantAssembler
from eneo.files.file_models import File, FileType


def _file(*, file_type=FileType.TEXT, stored=True) -> File:
    now = datetime.now(timezone.utc)
    return File(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        name="kontoplan.xlsx",
        checksum="0",
        size=1,
        mimetype="text/plain",
        file_type=file_type,
        text="x",
        user_id=uuid4(),
        tenant_id=uuid4(),
        original_available=stored,
    )


def _assembler() -> AssistantAssembler:
    return AssistantAssembler(user=MagicMock(), prompt_assembler=MagicMock())


def test_attachment_carries_its_mode_and_reference_capability():
    tool_file, prompt_file = _file(), _file()
    assistant = SimpleNamespace(
        attachments=[tool_file, prompt_file],
        attachment_inline_text={tool_file.id: False},
    )

    projected = {item.id: item for item in _assembler()._get_attachments(assistant)}

    assert projected[tool_file.id].inline_text is False
    assert projected[tool_file.id].has_download_reference is True
    assert projected[prompt_file.id].inline_text is True
    assert projected[prompt_file.id].has_download_reference is True


def test_no_reference_capability_without_stored_original():
    legacy = _file(stored=False)
    assistant = SimpleNamespace(attachments=[legacy], attachment_inline_text={})

    (item,) = _assembler()._get_attachments(assistant)

    assert item.has_download_reference is False
    assert item.inline_text is True
