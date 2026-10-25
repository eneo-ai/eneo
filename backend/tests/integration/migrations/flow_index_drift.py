"""Compare the ORM-declared indexes of the flows-owned tables with the database.

Alembic's autogenerate cannot run over this metadata (the builder tables form a
foreign-key cycle), so the migration round trips compare the declared shape with
the reflected one here.
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa

import eneo.database.tables  # noqa: F401
from eneo.database.tables import flow_tables
from eneo.database.tables.base_class import Base


def flow_owned_tables() -> list[sa.Table]:
    return [
        cls.__table__
        for cls in vars(flow_tables).values()
        if isinstance(cls, type)
        and cls.__module__ == flow_tables.__name__
        and issubclass(cls, Base)
        and hasattr(cls, "__table__")
    ]


def ddl_text(ddl: str) -> str:
    """Comparable form of an index definition: ORM CreateIndex vs pg_indexes.indexdef."""
    text = ddl.lower().replace("public.", "").replace(" using btree", "")
    return "".join(ch for ch in text if ch not in ' ()"\n;')


def _normalized(parts: list[str]) -> list[str]:
    # Reflection reports the sort direction in dialect options, not in the column.
    return [part.lower().replace(" ", "").removesuffix("desc") for part in parts]


def index_drift(
    engine: sa.Engine, *, introduced_later: Iterable[str] = ()
) -> dict[str, str]:
    """ORM-declared indexes of the flows-owned tables the database lacks or defines differently.

    The ORM declares head. A suite that holds the database at an older revision
    names the indexes later revisions add in ``introduced_later``: each must be
    ORM-declared and absent from the database, and is otherwise not compared.
    """
    later = frozenset(introduced_later)
    tables = flow_owned_tables()
    declared = {index.name for table in tables for index in table.indexes}
    assert later <= declared, f"not ORM-declared: {sorted(later - declared)}"
    inspector = sa.inspect(engine)
    drift: dict[str, str] = {}
    for table in tables:
        # A table a later revision adds is checked by that revision's own test.
        if not inspector.has_table(table.name):
            continue
        reflected = {
            index["name"]: index for index in inspector.get_indexes(table.name)
        }
        for index in table.indexes:
            actual = reflected.get(index.name)
            if index.name in later:
                if actual is not None:
                    drift[index.name] = "present before its revision"
                continue
            if actual is None:
                drift[index.name] = "missing"
                continue
            declared_columns = [
                expression.name
                if isinstance(expression, sa.Column)
                else str(expression)
                for expression in index.expressions
            ]
            actual_columns = actual.get("expressions") or actual["column_names"]
            declared_where = index.dialect_options["postgresql"]["where"]
            if _normalized(declared_columns) != _normalized(actual_columns):
                drift[index.name] = f"columns {actual_columns}"
            elif bool(index.unique) != bool(actual["unique"]):
                drift[index.name] = "uniqueness"
            elif (declared_where is None) != (
                "postgresql_where" not in actual["dialect_options"]
            ):
                drift[index.name] = "partial predicate"
            elif list(index.dialect_options["postgresql"]["include"] or []) != list(
                actual.get("include_columns") or []
            ):
                drift[index.name] = "include columns"
    return drift
