"""Every link table that points at ``files`` must count as File usage.

``FILE_USAGE_COLUMNS`` fences user-initiated deletion and the unused-file
cleanup alike. A new link table that is missing from it would not keep its
Files alive: the daily sweep would treat them as unused and delete them. This
test fails as soon as a foreign key to ``files.id`` appears without a usage
kind, so the author of the new table has to decide on purpose.
"""

from __future__ import annotations

import eneo.database.tables  # noqa: F401  # registers every table on the metadata
from eneo.database.tables.base_class import Base
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import FileContentReferences
from eneo.files.file_usage import FILE_USAGE_COLUMNS

# Foreign keys to ``files.id`` that do not mean "this File is in use": a derived
# File belongs to its root's family, and content references are released with
# the File.
STRUCTURAL_COLUMNS = (Files.parent_file_id, FileContentReferences.file_id)


def _qualified(column) -> str:
    return f"{column.table.name}.{column.name}"


def test_every_foreign_key_to_files_is_usage_or_structural() -> None:
    files_table = Files.__table__
    referencing = {
        _qualified(foreign_key.parent)
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
        if foreign_key.column.table is files_table
    }
    usage = {_qualified(column.property.columns[0]) for _, column in FILE_USAGE_COLUMNS}
    structural = {
        _qualified(column.property.columns[0]) for column in STRUCTURAL_COLUMNS
    }

    assert usage.isdisjoint(structural)
    assert referencing - structural == usage, (
        "A foreign key to files.id is not counted as File usage. Add it to "
        "FILE_USAGE_COLUMNS (and FileUsageKind) or, if it never keeps a File in "
        "use, to STRUCTURAL_COLUMNS in this test."
    )


def test_usage_columns_have_distinct_kinds() -> None:
    kinds = [kind for kind, _ in FILE_USAGE_COLUMNS]
    assert len(kinds) == len(set(kinds))
