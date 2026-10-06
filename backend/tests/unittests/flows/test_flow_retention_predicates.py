from __future__ import annotations

import eneo.database.tables  # noqa: F401
from eneo.database.tables.base_class import Base
from eneo.database.tables.files_table import Files
from eneo.database.tables.object_content_table import FileContentReferences
from eneo.flows.infrastructure.flow_retention_predicates import (
    FLOW_FILE_REFERENCE_TABLE_NAMES,
)


def test_flow_file_reference_guard_covers_product_foreign_keys() -> None:
    product_reference_tables = frozenset(
        table.name
        for table in Base.metadata.tables.values()
        for foreign_key in table.foreign_keys
        if foreign_key.column.table.name == Files.__tablename__
        and foreign_key.column.name == "id"
        and table.name != FileContentReferences.__tablename__
    )

    assert FLOW_FILE_REFERENCE_TABLE_NAMES == product_reference_tables


def test_file_content_references_cascade_through_the_content_release_fence() -> None:
    file_foreign_key = next(
        foreign_key
        for foreign_key in FileContentReferences.__table__.foreign_keys
        if foreign_key.column.table.name == Files.__tablename__
    )

    assert file_foreign_key.ondelete == "CASCADE"
    assert FileContentReferences.__tablename__ not in FLOW_FILE_REFERENCE_TABLE_NAMES
