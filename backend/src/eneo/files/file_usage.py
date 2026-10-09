from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from importlib import import_module
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.sql.selectable import Select

from eneo.database.tables.base_class import Base
from eneo.database.tables.files_table import FILE_USAGE_INFO_KEY, Files
from eneo.files.file_models import FileUsageKind


class FileUsageUndeclaredError(RuntimeError):
    """A column references ``files.id`` without declaring ``file_usage(...)``."""


def collect_file_usage_columns(
    metadata: sa.MetaData, files_table: sa.Table
) -> tuple[tuple[FileUsageKind, sa.Column[UUID]], ...]:
    """Find every column that keeps a File in use, from the table metadata.

    Each foreign key to ``files.id`` carries its meaning in the column ``info``
    (``file_usage(kind)`` or ``file_usage(None)``), so a link table added later
    is counted as usage from the start, and one without a declaration fails
    here rather than making its Files look unused. Ordered by ``FileUsageKind``.
    """
    found: list[tuple[FileUsageKind, sa.Column[UUID]]] = []
    for table in metadata.tables.values():
        for foreign_key in table.foreign_keys:
            if foreign_key.column.table is not files_table:
                continue
            column = foreign_key.parent
            if FILE_USAGE_INFO_KEY not in column.info:
                raise FileUsageUndeclaredError(
                    f"{table.name}.{column.name} references {files_table.name}.id "
                    "without file_usage(...): declare whether it keeps the File in use"
                )
            kind = column.info[FILE_USAGE_INFO_KEY]
            if kind is not None:
                found.append((FileUsageKind(kind), column))
    order = {kind: index for index, kind in enumerate(FileUsageKind)}
    found.sort(key=lambda item: (order[item[0]], item[1].table.name))
    return tuple(found)


# Every table module must be registered on the metadata before scanning it.
import_module("eneo.database.tables")
FILE_USAGE_COLUMNS = collect_file_usage_columns(
    cast(sa.MetaData, Base.metadata),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]  # SQLAlchemy declarative metadata
    cast(sa.Table, Files.__table__),  # pyright: ignore[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType]  # SQLAlchemy declarative table
)


class FileFamilyTenantMismatchError(RuntimeError):
    """A derived File points across the root File's tenant boundary."""


@dataclass(frozen=True, slots=True)
class FileUsageCount:
    kind: FileUsageKind
    count: int


class FileUsageRepository:
    """Derive usage that fences File deletion by users and by unused-file cleanup.

    User and tenant offboarding intentionally keep their database-owned cascade
    behavior. Advisory previews use a recursive CTE, while deletion locks base
    File rows level by level because PostgreSQL 13 does not propagate an outer
    ``FOR UPDATE`` through a recursive CTE.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_family(
        self,
        *,
        root_file_id: UUID,
        tenant_id: UUID,
    ) -> list[UUID]:
        family = (
            sa.select(Files.id, Files.parent_file_id, Files.tenant_id)
            .where(Files.id == root_file_id)
            .cte("file_family", recursive=True)
        )
        descendants = sa.select(
            Files.id,
            Files.parent_file_id,
            Files.tenant_id,
        ).join(family, Files.parent_file_id == family.c.id)
        family = family.union(descendants)

        rows = (
            await self._session.execute(
                sa.select(family.c.id, family.c.tenant_id).order_by(family.c.id)
            )
        ).all()
        self._require_tenant(
            (row.tenant_id for row in rows),
            tenant_id=tenant_id,
        )
        return [row.id for row in rows]

    async def lock_family(
        self,
        *,
        root_file_id: UUID,
        tenant_id: UUID,
    ) -> list[UUID]:
        root = (
            await self._session.execute(
                sa.select(Files.id, Files.tenant_id)
                .where(Files.id == root_file_id)
                .with_for_update(of=Files)
            )
        ).one_or_none()
        if root is None:
            return []
        self._require_tenant([root.tenant_id], tenant_id=tenant_id)

        family_ids = [root.id]
        visited = {root.id}
        frontier = [root.id]
        while frontier:
            rows = (
                await self._session.execute(
                    sa.select(Files.id, Files.tenant_id)
                    .where(Files.parent_file_id.in_(frontier))
                    .order_by(Files.id)
                    .with_for_update(of=Files)
                )
            ).all()
            self._require_tenant(
                (row.tenant_id for row in rows),
                tenant_id=tenant_id,
            )
            frontier = [row.id for row in rows if row.id not in visited]
            visited.update(frontier)
            family_ids.extend(frontier)

        return family_ids

    async def list_unreferenced_roots(
        self,
        *,
        after: UUID | None,
        older_than: timedelta,
        limit: int,
    ) -> list[UUID]:
        """Page root Files that no usage table links to directly, by id.

        This is an index-only prefilter: a derived File can still keep its
        root in use, so callers pass the page to ``lock_unused_root_families``
        before deleting anything. ``older_than`` protects uploads that are
        not attached yet.
        """
        query = (
            sa.select(Files.id)
            .where(
                Files.parent_file_id.is_(None),
                Files.created_at < sa.func.now() - older_than,
                *(
                    ~sa.exists().where(file_id_column == Files.id)
                    for _, file_id_column in FILE_USAGE_COLUMNS
                ),
            )
            .order_by(Files.id)
            .limit(limit)
        )
        if after is not None:
            query = query.where(Files.id > after)
        return list((await self._session.scalars(query)).all())

    async def lock_unused_root_families(
        self,
        candidate_file_ids: Iterable[UUID],
    ) -> list[UUID]:
        """Lock candidate root Files and return those whose family has no usage.

        Callers pass the Files that deleted records used, or a page from
        ``list_unreferenced_roots``. Derived candidates are skipped, since they
        belong to their root's family. A family that still has any product usage, or that
        crosses a tenant boundary, is left intact. Rows are locked root first
        and then level by level, matching ``lock_family``, so a concurrent
        attach either commits first and is seen here or waits for the delete.
        """
        candidates = sorted(set(candidate_file_ids))
        if not candidates:
            return []

        roots = (
            await self._session.execute(
                sa.select(Files.id, Files.tenant_id)
                .where(
                    Files.id == sa.any_(self._file_ids_parameter("candidate_ids")),
                    Files.parent_file_id.is_(None),
                )
                .order_by(Files.id)
                .with_for_update(of=Files),
                {"candidate_ids": candidates},
            )
        ).all()
        root_tenant = {row.id: row.tenant_id for row in roots}
        root_of = {root_id: root_id for root_id in root_tenant}
        kept: set[UUID] = set()

        frontier: list[UUID] = list(root_tenant)
        while frontier:
            rows = (
                await self._session.execute(
                    sa.select(Files.id, Files.parent_file_id, Files.tenant_id)
                    .where(
                        Files.parent_file_id
                        == sa.any_(self._file_ids_parameter("frontier_ids"))
                    )
                    .order_by(Files.id)
                    .with_for_update(of=Files),
                    {"frontier_ids": frontier},
                )
            ).all()
            frontier = []
            for row in rows:
                if row.id in root_of:
                    continue
                root_id = root_of[row.parent_file_id]
                root_of[row.id] = root_id
                if row.tenant_id != root_tenant[root_id]:
                    kept.add(root_id)
                frontier.append(row.id)

        used_ids = (
            await self._session.scalars(
                sa.select(self._usage_union("family_ids").c.file_id).distinct(),
                {"family_ids": list(root_of)},
            )
        ).all()
        kept.update(root_of[file_id] for file_id in used_ids)
        return [root_id for root_id in root_tenant if root_id not in kept]

    async def count_product_usage(
        self,
        file_ids: list[UUID],
    ) -> list[FileUsageCount]:
        if not file_ids:
            return []

        usage = self._usage_union("file_usage_ids")
        rows = (
            await self._session.execute(
                sa.select(
                    usage.c.kind,
                    sa.func.count().label("usage_count"),
                )
                .group_by(usage.c.kind)
                .order_by(usage.c.kind),
                {"file_usage_ids": file_ids},
            )
        ).all()
        return [
            FileUsageCount(
                kind=FileUsageKind(row.kind),
                count=row.usage_count,
            )
            for row in rows
        ]

    @classmethod
    def _usage_union(cls, parameter_name: str) -> sa.Subquery:
        file_ids_parameter = cls._file_ids_parameter(parameter_name)
        return sa.union_all(
            *(
                cls._usage_select(kind, file_id_column, file_ids_parameter)
                for kind, file_id_column in FILE_USAGE_COLUMNS
            )
        ).subquery("file_product_usage")

    @staticmethod
    def _file_ids_parameter(name: str) -> BindParameter[Sequence[UUID]]:
        return sa.bindparam(name, type_=ARRAY(PostgreSQLUUID(as_uuid=True)))

    @staticmethod
    def _usage_select(
        kind: FileUsageKind,
        file_id_column: sa.Column[UUID],
        file_ids_parameter: BindParameter[Sequence[UUID]],
    ) -> Select[tuple[str, UUID]]:
        return sa.select(
            sa.literal(kind.value).label("kind"),
            file_id_column.label("file_id"),
        ).where(file_id_column == sa.any_(file_ids_parameter))

    @staticmethod
    def _require_tenant(
        tenant_ids: Iterable[UUID],
        *,
        tenant_id: UUID,
    ) -> None:
        if any(row_tenant_id != tenant_id for row_tenant_id in tenant_ids):
            raise FileFamilyTenantMismatchError(
                "Derived File family crosses a tenant boundary."
            )
