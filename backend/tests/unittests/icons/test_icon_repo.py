import eneo.database.tables  # noqa: F401  (registers tables, as in alembic/env.py)
from eneo.database.tables.base_class import Base
from eneo.icons.icon_repo import ICON_REFERENCES


def test_every_foreign_key_to_an_icon_keeps_it_from_deletion() -> None:
    referencing = {
        (fk.parent.table.name, fk.parent.name)
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name == "icons"
    }

    # Content references belong to the icon itself and cascade with it.
    assert referencing - {("icon_content_references", "icon_id")} == {
        (column.table.name, column.name) for column in ICON_REFERENCES
    }


def test_every_icon_reference_is_indexed() -> None:
    # Each delete looks every reference up, as does the ON DELETE SET NULL cascade.
    unindexed = {
        (column.table.name, column.name)
        for column in ICON_REFERENCES
        if not any(
            next(iter(index.columns)).name == column.name
            for index in column.table.indexes
        )
    }

    assert unindexed == set()
