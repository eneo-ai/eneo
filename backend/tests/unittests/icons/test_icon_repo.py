from sqlalchemy.dialects import postgresql

import eneo.database.tables  # noqa: F401  (registers tables, as in alembic/env.py)
from eneo.database.tables.base_class import Base
from eneo.icons.icon_repo import (
    ICON_REFERENCE_COLUMNS,
    ICON_REFERENCE_DOCUMENTS,
    ICON_REFERENCES,
)


def test_every_foreign_key_to_an_icon_keeps_it_from_deletion() -> None:
    referencing = {
        (fk.parent.table.name, fk.parent.name)
        for table in Base.metadata.tables.values()
        for fk in table.foreign_keys
        if fk.column.table.name == "icons"
    }

    # Content references belong to the icon itself and cascade with it.
    assert referencing - {("icon_content_references", "icon_id")} == {
        (column.table.name, column.name) for column in ICON_REFERENCE_COLUMNS
    }


def test_every_icon_reference_column_is_indexed() -> None:
    # Each delete looks every reference up, as does the ON DELETE SET NULL cascade.
    unindexed = {
        (column.table.name, column.name)
        for column in ICON_REFERENCE_COLUMNS
        if not any(
            next(iter(index.columns)).name == column.name
            for index in column.table.indexes
        )
    }

    assert unindexed == set()


def test_every_persona_document_counts_as_an_icon_reference() -> None:
    # Widgets and templates keep the avatar id inside JSONB; the draft and the
    # published release of a template are separate documents. Rendering
    # differs between literal-bind styles, so only the shape is pinned here;
    # the integration suite runs the real query.
    rendered = [
        str(
            reference.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        for reference in ICON_REFERENCE_DOCUMENTS
    ]

    assert all(
        sql.startswith("CAST(") and sql.endswith("AS UUID)") and "avatar_icon_id" in sql
        for sql in rendered
    )
    assert [sql.split(" ")[0].removeprefix("CAST(") for sql in rendered] == [
        "widgets.persona",
        "widget_templates.persona",
        "(widget_templates.published['persona'])",
    ]
    assert ICON_REFERENCES == (*ICON_REFERENCE_COLUMNS, *ICON_REFERENCE_DOCUMENTS)
