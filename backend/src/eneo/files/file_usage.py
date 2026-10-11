from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from importlib import import_module
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import BindParameter
from sqlalchemy.sql.selectable import Select

from eneo.database.tables.files_table import FILE_USAGE_INFO_KEY, Files
from eneo.files.file_models import FileUsageKind
from eneo.files.file_retention import FileRetentionReason, FileRetentionResult


class FileUsageUndeclaredError(RuntimeError):
    """A column references ``files.id`` without declaring ``file_usage(...)``."""


class FileCascadeIdentityError(RuntimeError):
    """A direct cascade cannot identify each bounded candidate to lock it."""


@dataclass(frozen=True, slots=True)
class FileReferenceColumns:
    usage: tuple[tuple[FileUsageKind, sa.Column[UUID]], ...]
    cascades: tuple[sa.Column[UUID], ...]


def collect_file_reference_columns(
    metadata: sa.MetaData, files_table: sa.Table
) -> FileReferenceColumns:
    """Derive usage and direct cascade dependencies from the FK declarations.

    Each foreign key to ``files.id`` carries its meaning in the column ``info``
    (``file_usage(kind)`` or ``file_usage(None)``), so a link table added later
    is counted as usage from the start, and one without a declaration fails
    here rather than making its Files look unused. Non-usage cascade rows count
    toward the deletion budget; child Files are counted by family traversal.
    """
    found: list[tuple[FileUsageKind, sa.Column[UUID]]] = []
    cascades: list[sa.Column[UUID]] = []
    for table in metadata.tables.values():
        for foreign_key in table.foreign_keys:
            # Only the column that references ``files.id`` carries a meaning; a
            # composite key may also reference ``files.tenant_id`` for row-level
            # safety without being a second reference to the File.
            if foreign_key.column is not files_table.c.id:
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
            elif foreign_key.ondelete == "CASCADE" and not (
                table is files_table and column.name == "parent_file_id"
            ):
                if not table.primary_key:
                    raise FileCascadeIdentityError(
                        f"{table.name} needs a primary key for bounded file cascade locking"
                    )
                cascades.append(column)
    order = {kind: index for index, kind in enumerate(FileUsageKind)}
    found.sort(key=lambda item: (order[item[0]], item[1].table.name))
    cascades.sort(key=lambda column: (column.table.name, column.name))
    return FileReferenceColumns(usage=tuple(found), cascades=tuple(cascades))


# Every table module must be registered on the metadata before scanning it.
import_module("eneo.database.tables")
_FILES_TABLE = sa.inspect(Files, raiseerr=True).local_table
if not isinstance(_FILES_TABLE, sa.Table):
    raise TypeError("Files must map directly to a SQL table.")
_FILE_REFERENCES = collect_file_reference_columns(_FILES_TABLE.metadata, _FILES_TABLE)
FILE_USAGE_COLUMNS = _FILE_REFERENCES.usage
FILE_CASCADE_COLUMNS = _FILE_REFERENCES.cascades


class FileFamilyTenantMismatchError(RuntimeError):
    """A derived File points across the root File's tenant boundary."""


@dataclass(frozen=True, slots=True)
class FileUsageCount:
    kind: FileUsageKind
    count: int


@dataclass(frozen=True, slots=True)
class _FamilyFile:
    id: UUID
    parent_file_id: UUID | None
    tenant_id: UUID
    locked: bool = True


class FileFamilyChangedUnderLockError(RuntimeError):
    """A proved family changed despite its locks; its transaction must roll back."""


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
        root = await self._lock_root(root_file_id)
        if root is None:
            return []
        self._require_tenant([root.tenant_id], tenant_id=tenant_id)

        family_ids = [root.id]
        visited = {root.id}
        frontier = [root.id]
        while frontier:
            rows = await self._lock_children(frontier)
            self._require_tenant(
                (row.tenant_id for row in rows),
                tenant_id=tenant_id,
            )
            frontier = [row.id for row in rows if row.id not in visited]
            visited.update(frontier)
            family_ids.extend(frontier)

        return family_ids

    async def _lock_files(
        self,
        query: Select[tuple[UUID, UUID | None, UUID]],
        *,
        skip_locked: bool,
    ) -> list[_FamilyFile]:
        if not skip_locked:
            rows = (
                await self._session.execute(query.with_for_update(of=Files))
            ).tuples()
            return [_FamilyFile(*row) for row in rows]
        # Preserve every bounded candidate, including a skipped lock. Filling
        # holes with later rows would hide a family member from the proof.
        window = query.cte("family_candidates").prefix_with("MATERIALIZED")
        locked = (
            sa.select(Files.id.label("locked_id"))
            .where(
                Files.id == window.c.id,
                Files.parent_file_id.is_not_distinct_from(window.c.parent_file_id),
            )
            .with_for_update(of=Files, skip_locked=True)
            .correlate(window)
            .lateral("locked_family_member")
        )
        rows = (
            await self._session.execute(
                sa.select(
                    window.c.id,
                    window.c.parent_file_id,
                    window.c.tenant_id,
                    locked.c.locked_id.is_not(None),
                ).select_from(window.outerjoin(locked, sa.true()))
            )
        ).tuples()
        return [_FamilyFile(*row) for row in rows]

    async def _lock_root(
        self, root_file_id: UUID, *, skip_locked: bool = False
    ) -> _FamilyFile | None:
        rows = await self._lock_files(
            sa.select(Files.id, Files.parent_file_id, Files.tenant_id).where(
                Files.id == root_file_id
            ),
            skip_locked=skip_locked,
        )
        return rows[0] if rows else None

    async def _lock_children(
        self,
        parent_ids: Sequence[UUID],
        *,
        limit: int | None = None,
        skip_locked: bool = False,
    ) -> list[_FamilyFile]:
        query = (
            sa.select(Files.id, Files.parent_file_id, Files.tenant_id)
            .where(
                Files.parent_file_id
                == sa.any_(self._file_ids_parameter("parents", parent_ids))
            )
            .order_by(Files.id)
        )
        if limit is not None:
            query = query.limit(limit)
        return await self._lock_files(query, skip_locked=skip_locked)

    @staticmethod
    def _product_usage_exists(
        file_id: sa.ColumnElement[UUID] = Files.id.expression,
    ) -> sa.ColumnElement[bool]:
        return sa.or_(
            *(sa.exists().where(column == file_id) for _, column in FILE_USAGE_COLUMNS)
        )

    @staticmethod
    def _aged_root(older_than: timedelta) -> sa.ColumnElement[bool]:
        return sa.and_(
            Files.parent_file_id.is_(None),
            Files.created_at < sa.func.now() - older_than,
        )

    @classmethod
    def unreferenced_roots_statement(
        cls, older_than: timedelta
    ) -> Select[tuple[datetime, UUID]]:
        """Preview prefilter only; a derived member can still keep a root in use."""
        return sa.select(Files.created_at, Files.id).where(
            cls._aged_root(older_than), ~cls._product_usage_exists()
        )

    async def next_retention_root(
        self,
        *,
        after: tuple[datetime, UUID] | None,
        older_than: timedelta,
    ) -> tuple[datetime, UUID, bool] | None:
        """The next aged root by keyset, with its own direct usage, unlocked.

        One root per read, so every root read is charged by the caller.
        Referenced roots are returned too: skipping them in the query could scan
        an unbounded tail without recording a cursor or consuming the budget.
        The usage flag is a prefilter only; ``delete_unused_root`` decides under
        its locks, including uses of derived Files.
        """
        query = sa.select(Files.created_at, Files.id).where(self._aged_root(older_than))
        if after is not None:
            query = query.where(
                sa.tuple_(Files.created_at, Files.id)
                > sa.tuple_(sa.literal(after[0]), sa.literal(after[1]))
            )
        # Pick the root first, then probe its usage: in the same select list the
        # planner hashes every usage table instead of probing for one row.
        root = (
            query.order_by(Files.created_at, Files.id)
            .limit(1)
            .subquery("next_retention_root")
        )
        row = (
            (
                await self._session.execute(
                    sa.select(
                        root.c.created_at,
                        root.c.id,
                        self._product_usage_exists(root.c.id),
                    )
                )
            )
            .tuples()
            .first()
        )
        if row is None:
            return None
        at, identifier, in_use = row
        return at, identifier, in_use

    async def delete_unused_root(
        self,
        root_file_id: UUID,
        *,
        max_rows: int,
        max_files: int,
        max_family_rows: int,
        older_than: timedelta | None = None,
    ) -> FileRetentionResult:
        """Prove and release a bounded family in the caller's transaction.

        Root-first locks prevent children or uses being attached behind the
        traversal. Each member costs one lock/read, one fresh ownership check
        and one cascade deletion; each direct dependency costs a locked read
        and a cascade deletion. Counts and sentinels are paid even on refusal.
        Manual deletion uses the same locks and usage rule without this cap.
        """
        if min(max_rows, max_files) < 0 or max_family_rows <= 0:
            raise ValueError(
                "File retention allowances must be nonnegative and cap positive."
            )
        used = 0
        tenant_id: UUID | None = None

        def stopped(reason: FileRetentionReason) -> FileRetentionResult:
            return FileRetentionResult(
                rows=used,
                files=0,
                deleted_roots=0,
                deleted_members=0,
                deleted_references=0,
                tenant_id=tenant_id,
                reason=reason,
            )

        def cannot_fit(minimum_rows: int) -> FileRetentionResult:
            return stopped(
                FileRetentionReason.FAMILY_EXCEEDS_BUDGET
                if minimum_rows > max_family_rows
                else FileRetentionReason.INSUFFICIENT_BUDGET
            )

        if max_rows == 0 or max_files == 0:
            return stopped(FileRetentionReason.INSUFFICIENT_BUDGET)
        root = await self._lock_root(root_file_id, skip_locked=True)
        used += 1
        if root is None:
            return stopped(FileRetentionReason.MISSING)
        tenant_id = root.tenant_id
        if not root.locked:
            return stopped(FileRetentionReason.LOCKED)
        if root.parent_file_id is not None:
            return stopped(FileRetentionReason.NOT_ROOT)

        allowance = min(max_rows, max_family_rows)
        member_limit = min(allowance // 3, max_files)
        if member_limit == 0:
            return cannot_fit(3)
        members = [root.id]
        frontier = [root.id]
        while frontier:
            children = await self._lock_children(
                frontier, limit=member_limit - len(members) + 1, skip_locked=True
            )
            used += len(children)
            if any(not child.locked for child in children):
                return stopped(FileRetentionReason.LOCKED)
            if len(members) + len(children) > member_limit:
                return cannot_fit(3 * (len(members) + len(children)))
            members.extend(child.id for child in children)
            frontier = [child.id for child in children]

        # A late attachment that committed before the member lock is visible in
        # this fresh statement; one that starts after it must wait for commit.
        old_enough = (
            sa.true()
            if older_than is None
            else Files.created_at < sa.func.now() - older_than
        )
        fresh = (
            (
                await self._session.execute(
                    sa.select(
                        Files.id,
                        Files.parent_file_id,
                        Files.tenant_id,
                        self._product_usage_exists(),
                        old_enough,
                    ).where(Files.id == sa.any_(self._file_ids_parameter("members"))),
                    {"members": members},
                )
            )
            .tuples()
            .all()
        )
        used += len(fresh)
        if {row[0] for row in fresh} != set(members):
            raise FileFamilyChangedUnderLockError("A locked family member disappeared.")
        if any(row[2] != tenant_id for row in fresh):
            return stopped(FileRetentionReason.TENANT_MISMATCH)
        for identifier, parent, _, in_use, aged in fresh:
            if identifier == root_file_id:
                if parent is not None:
                    return stopped(FileRetentionReason.NOT_ROOT)
                if not aged:
                    return stopped(FileRetentionReason.NOT_OLD_ENOUGH)
            if in_use:
                return stopped(FileRetentionReason.IN_USE)

        reference_limit = (allowance - 3 * len(members)) // 2
        references = 0
        for column in FILE_CASCADE_COLUMNS:
            dependency_locks = await self._lock_cascade_rows(
                column, members, limit=reference_limit - references + 1
            )
            used += len(dependency_locks)
            references += len(dependency_locks)
            if not all(dependency_locks):
                return stopped(FileRetentionReason.LOCKED)
            if references > reference_limit:
                return cannot_fit(3 * len(members) + 2 * references)
        total_rows = 3 * len(members) + 2 * references
        deleted = await self._session.scalar(
            sa.delete(Files).where(Files.id == root_file_id).returning(Files.id)
        )
        if deleted != root_file_id:
            raise FileFamilyChangedUnderLockError(
                "The proved family root was not deleted."
            )
        return FileRetentionResult(
            rows=total_rows,
            files=len(members),
            deleted_roots=1,
            deleted_members=len(members),
            deleted_references=references,
            tenant_id=tenant_id,
            reason=FileRetentionReason.DELETED,
        )

    async def _lock_cascade_rows(
        self, column: sa.Column[UUID], members: Sequence[UUID], *, limit: int
    ) -> list[bool]:
        keys = tuple(column.table.primary_key)
        window = (
            sa.select(*keys)
            .where(column == sa.any_(self._file_ids_parameter("members", members)))
            .order_by(*keys)
            .limit(limit)
            .cte("file_dependency_candidates")
            .prefix_with("MATERIALIZED")
        )
        locked = (
            sa.select(column.label("file_id"))
            .where(*(key == window.c[key.name] for key in keys))
            .where(column == sa.any_(self._file_ids_parameter("members", members)))
            .with_for_update(of=column.table, skip_locked=True)
            .correlate(window)
            .lateral("locked_file_dependency")
        )
        return list(
            await self._session.scalars(
                sa.select(locked.c.file_id.is_not(None)).select_from(
                    window.outerjoin(locked, sa.true())
                )
            )
        )

    async def list_unreferenced_roots(
        self,
        *,
        after: UUID | None,
        older_than: timedelta,
        limit: int,
    ) -> list[UUID]:
        """Page root Files that no usage table links to directly, by id.

        This is a discovery prefilter: a derived File can still keep its
        root in use, so callers pass the page to ``lock_unused_root_families``
        before deleting anything. ``older_than`` protects uploads that are
        not attached yet.
        """
        query = (
            self.unreferenced_roots_statement(older_than)
            .with_only_columns(Files.id)
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
            rows = await self._lock_children(frontier)
            frontier = []
            for row in rows:
                if row.id in root_of:
                    continue
                if row.parent_file_id is None:
                    raise FileFamilyChangedUnderLockError(
                        "A selected child lost its parent."
                    )
                root_id = root_of[row.parent_file_id]
                root_of[row.id] = root_id
                if row.tenant_id != root_tenant[root_id]:
                    kept.add(root_id)
                frontier.append(row.id)

        used_ids = (
            await self._session.scalars(
                sa.select(Files.id).where(
                    Files.id == sa.any_(self._file_ids_parameter("family_ids")),
                    self._product_usage_exists(),
                ),
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
    def _file_ids_parameter(
        name: str, value: Sequence[UUID] | None = None
    ) -> BindParameter[Sequence[UUID]]:
        return sa.bindparam(
            name, value=value, type_=ARRAY(PostgreSQLUUID(as_uuid=True))
        )

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
