"""The lock a transcript save takes on its file row.

A question placeholder references the file from its own connection while the
ask's ambient transaction still holds this lock, so the lock must leave the
row's key shareable: ``FOR NO KEY UPDATE``, never plain ``FOR UPDATE``.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from eneo.files import file_repo
from eneo.files.file_repo import FileRepository
from eneo.main.exceptions import NotFoundException


async def test_transcript_save_lock_leaves_the_file_key_shareable(monkeypatch):
    monkeypatch.setattr(
        file_repo, "file_icon_legacy_is_cleaned", AsyncMock(return_value=True)
    )
    session = MagicMock()
    session.scalar = AsyncMock(return_value=None)

    with pytest.raises(NotFoundException):
        await FileRepository(session).get_by_id_for_update(uuid4())

    statement = session.scalar.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert sql.rstrip().endswith("FOR NO KEY UPDATE")
