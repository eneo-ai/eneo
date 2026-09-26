import eneo.database.tables  # noqa: F401  (registers every table)
from eneo.database.tables.base_class import Base
from eneo.database.tables.icons_table import Icons
from eneo.database.tables.object_content_table import IconContentReferences
from eneo.icons.icon_repo import ICON_USER_COLUMNS


def test_icon_deletion_checks_every_column_that_uses_an_icon() -> None:
    # A column that references icons and is missing here would let deleting
    # one resource delete an icon another resource still shows.
    referencing_columns = {
        (foreign_key.parent.table.name, foreign_key.parent.name)
        for table in Base.metadata.tables.values()
        if table is not IconContentReferences.__table__
        for foreign_key in table.foreign_keys
        if foreign_key.column.table is Icons.__table__
    }

    assert referencing_columns == {
        (column.table.name, column.name) for column in ICON_USER_COLUMNS
    }
