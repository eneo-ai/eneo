from __future__ import annotations

from uuid import UUID

from sqlalchemy.dialects import postgresql

from eneo.files.unused_file_cleanup import delete_roots_statement


def test_root_delete_binds_any_batch_size_as_one_array() -> None:
    root_ids = [UUID(int=value) for value in range(1, 40_001)]

    compiled = delete_roots_statement(root_ids).compile(dialect=postgresql.dialect())

    assert "files.id = ANY" in str(compiled)
    assert "RETURNING files.id" in str(compiled)
    assert set(compiled.params) == {"root_file_ids"}
    assert len(compiled.params["root_file_ids"]) == 40_000
