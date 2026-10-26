"""File usage is declared on the foreign key and derived from the metadata.

A link table says what its ``files.id`` column means where the column is
defined (``file_usage(kind)`` or ``file_usage(None)``). ``file_usage`` derives
the usage columns from that, so nothing has to be registered elsewhere, and a
column without a declaration fails on import rather than making its Files look
unused to the daily cleanup.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID

from eneo.database.tables.files_table import file_usage
from eneo.files.file_models import FileUsageKind
from eneo.files.file_usage import (
    FILE_CASCADE_COLUMNS,
    FILE_USAGE_COLUMNS,
    FileCascadeIdentityError,
    FileUsageUndeclaredError,
    collect_file_reference_columns,
)


def test_every_declared_usage_column_is_derived_in_kind_order() -> None:
    assert [
        (kind, f"{column.table.name}.{column.name}")
        for kind, column in FILE_USAGE_COLUMNS
    ] == [
        (FileUsageKind.CHAT_ATTACHMENT, "questions_files.file_id"),
        (FileUsageKind.ASSISTANT_ATTACHMENT, "assistants_files.file_id"),
        (FileUsageKind.APP_ATTACHMENT, "apps_files.file_id"),
        (FileUsageKind.APP_RUN_INPUT, "app_runs_files.file_id"),
    ]


def _metadata_with_link(
    info: dict[str, object] | None, *, primary_key: bool = True
) -> tuple[sa.MetaData, sa.Table]:
    metadata = sa.MetaData()
    files = sa.Table(
        "files",
        metadata,
        sa.Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
    )
    sa.Table(
        "links",
        metadata,
        sa.Column(
            "file_id",
            PostgreSQLUUID(as_uuid=True),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            primary_key=primary_key,
            info=info or {},
        ),
    )
    return metadata, files


def test_undeclared_foreign_key_to_files_fails() -> None:
    metadata, files = _metadata_with_link(None)

    with pytest.raises(FileUsageUndeclaredError, match="links.file_id"):
        collect_file_reference_columns(metadata, files)


def test_a_cascade_without_row_identity_fails_before_cleanup() -> None:
    """Mutant: a keyless dependency becomes an unbounded lock join."""
    metadata, files = _metadata_with_link(file_usage(None), primary_key=False)
    with pytest.raises(FileCascadeIdentityError, match="primary key"):
        collect_file_reference_columns(metadata, files)


def test_declared_usage_is_counted_and_structural_is_not() -> None:
    metadata, files = _metadata_with_link(file_usage(FileUsageKind.APP_RUN_INPUT))
    [(kind, column)] = collect_file_reference_columns(metadata, files).usage
    assert kind is FileUsageKind.APP_RUN_INPUT
    assert column.table.name == "links"

    metadata, files = _metadata_with_link(file_usage(None))
    references = collect_file_reference_columns(metadata, files)
    assert references.usage == ()
    # Mutant: a newly declared CASCADE dependency is omitted from the family cap.
    assert [column.table.name for column in references.cascades] == ["links"]
    assert [(column.table.name, column.name) for column in FILE_CASCADE_COLUMNS] == [
        ("file_content_references", "file_id")
    ]


def test_only_foreign_keys_to_files_are_considered() -> None:
    metadata = sa.MetaData()
    files = sa.Table(
        "files",
        metadata,
        sa.Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
    )
    other = sa.Table(
        "other",
        metadata,
        sa.Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
    )
    sa.Table(
        "links",
        metadata,
        sa.Column(
            "other_id",
            PostgreSQLUUID(as_uuid=True),
            sa.ForeignKey(other.c.id),
            primary_key=True,
        ),
    )
    assert collect_file_reference_columns(metadata, files).usage == ()


def test_a_composite_key_declares_usage_on_its_file_column_only() -> None:
    """Mutant: treating every column of a (file_id, tenant_id) key as a reference
    to Files, which would demand a declaration on the tenant column."""
    metadata = sa.MetaData()
    files = sa.Table(
        "files",
        metadata,
        sa.Column("id", PostgreSQLUUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", PostgreSQLUUID(as_uuid=True), nullable=False),
        sa.UniqueConstraint("id", "tenant_id"),
    )
    links = sa.Table(
        "links",
        metadata,
        sa.Column(
            "file_id",
            PostgreSQLUUID(as_uuid=True),
            primary_key=True,
            info=file_usage(FileUsageKind.APP_RUN_INPUT),
        ),
        sa.Column("tenant_id", PostgreSQLUUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["file_id", "tenant_id"], ["files.id", "files.tenant_id"]
        ),
    )
    columns = collect_file_reference_columns(metadata, files)
    assert columns.usage == ((FileUsageKind.APP_RUN_INPUT, links.c.file_id),)
    assert columns.cascades == ()
