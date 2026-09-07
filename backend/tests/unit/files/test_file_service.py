"""File persistence keeps its read-back inside the write transaction."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from eneo.files import file_service as module
from eneo.files.file_service import FileService


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
