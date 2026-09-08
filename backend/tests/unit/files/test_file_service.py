"""File persistence keeps its read-back inside the write transaction, and the
original-download selection serves what ``original_available`` promises."""

from contextlib import asynccontextmanager
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from eneo.files import file_service as module
from eneo.files.file_models import FileContentVariant, FileType
from eneo.files.file_repo import FileContentReferenceRecord
from eneo.files.file_service import FileOriginalNotFoundError, FileService
from eneo.object_content.content import ContentAccessClass


def _service_with_explicit_transactions() -> tuple[FileService, dict[str, bool]]:
    """A service on a session with autobegin off, as outside a request scope."""
    state = {"in_transaction": False}
    session = MagicMock()
    session.in_transaction.side_effect = lambda: state["in_transaction"]

    @asynccontextmanager
    async def begin():
        state["in_transaction"] = True
        try:
            yield
        finally:
            state["in_transaction"] = False

    session.begin = begin
    service = FileService.__new__(FileService)
    service.user = SimpleNamespace(id=uuid4())
    service.repo = SimpleNamespace(session=session)
    return service, state


async def test_generated_image_is_read_back_inside_the_write_transaction(monkeypatch):
    service, state = _service_with_explicit_transactions()
    file_id = uuid4()
    seen: list[bool] = []

    async def get_file_by_id(requested):
        seen.append(state["in_transaction"])
        assert requested == file_id
        return SimpleNamespace(model_dump=lambda: {"id": file_id})

    monkeypatch.setattr(
        service, "_persist_prepared_file", AsyncMock(return_value=file_id)
    )
    monkeypatch.setattr(service, "get_file_by_id", get_file_by_id)
    monkeypatch.setattr(module, "File", lambda **fields: SimpleNamespace(**fields))

    saved = await service.save_image_from_bytes(
        b"img", name="a.png", mimetype="image/png"
    )

    assert seen == [True]
    assert saved.id == file_id and saved.blob == b"img"
    assert state["in_transaction"] is False


def _reference(variant):
    return FileContentReferenceRecord(
        file_id=uuid4(),
        content_id=uuid4(),
        variant=FileContentVariant(variant),
        ordinal=0,
        page_number=None,
        width=None,
        height=None,
        duration_ms=None,
        sha256=sha256(b"x").digest(),
        size_bytes=1,
        media_type="image/png",
        access_class=ContentAccessClass.PRIVATE_RESOURCE,
    )


class TestOriginalContent:
    """The original-download route serves what ``original_available`` promises."""

    def test_generated_artifact_is_an_image_original(self):
        artifact = _reference("generated_artifact")
        assert FileService._original_content([artifact], FileType.IMAGE) is artifact

    def test_stored_original_wins_over_the_artifact(self):
        original, artifact = _reference("original"), _reference("generated_artifact")
        assert (
            FileService._original_content([artifact, original], FileType.IMAGE)
            is original
        )

    def test_text_file_without_original_is_not_served(self):
        with pytest.raises(FileOriginalNotFoundError):
            FileService._original_content([_reference("extracted_text")], FileType.TEXT)
