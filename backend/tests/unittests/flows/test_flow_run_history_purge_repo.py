from __future__ import annotations

import intric.database.tables  # noqa: F401
from intric.database.tables.base_class import Base
from intric.database.tables.files_table import Files
from intric.flows.infrastructure.flow_run_history_purge_repo import (
    FLOW_RUN_HISTORY_PURGE_FILE_REFERENCE_TABLE_NAMES,
)


def test_flow_run_history_purge_file_reference_guard_covers_files_foreign_keys() -> (
    None
):
    referencing_tables = frozenset(
        table.name
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name == Files.__tablename__
        and foreign_key.column.name == "id"
    )

    assert FLOW_RUN_HISTORY_PURGE_FILE_REFERENCE_TABLE_NAMES == referencing_tables
