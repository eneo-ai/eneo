"""Statements of the atomic reclamation of one file family.

A family is a root file and every file derived from it (`files.parent_file_id`).
It is reclaimed in one transaction: its size is counted within a cap (bounded
counts), every member is locked and the family enumerated again under the
locks, checked afresh for another owner and listed in the manifest,
and the members are deleted deepest first through the shared file reference
guard (a file's content references go with its row). Nothing about a family is
carried from one transaction to the next.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from eneo.data_retention.infrastructure.retention_sql import uuid_in
from eneo.database.tables.files_table import Files
from eneo.database.tables.flow_tables import (
    FlowLiveTranscripts,
    FlowRunStepInputFiles,
    FlowRunStepResultFiles,
    FlowRuntimeUploadedFiles,
)
from eneo.database.tables.object_content_table import FileContentReferences
from eneo.flows.infrastructure.flow_run_deletion_repo import run_file_roots
from eneo.flows.infrastructure.flow_run_history_purge_repo import (
    flow_file_reference_exists,
)

T = TypeVar("T")

# Derived files nest one or two levels; the bound only guards a corrupt cycle.
# A family that nests deeper is never released or deleted: it is paused with
# family_depth_exceeded.
_MAX_FAMILY_DEPTH = 32

# Edges inside a family are not outside owners: the child edge always, and for
# the root also its discovery anchor, which the reclamation removes.
_INTERNAL_EDGES = frozenset({Files.__tablename__})
# An abandoned upload: its binding and the live transcripts bound to it.
UPLOAD_ANCHOR_EDGES = _INTERNAL_EDGES | {
    FlowRuntimeUploadedFiles.__tablename__,
    FlowLiveTranscripts.__tablename__,
}


@dataclass(frozen=True, slots=True)
class FamilyBlock:
    """A member another owner references, or an incomplete family traversal."""

    file_id: UUID
    is_root: bool
    depth_exceeded: bool = False


@dataclass(frozen=True, slots=True)
class Bounded(Generic[T]):
    """A retrieval cut at its limit: the rows examined, and the items unless
    there were more than the limit (or the family changed)."""

    items: list[T] | None
    examined: int


@dataclass(frozen=True, slots=True)
class FamilyMember:
    file_id: UUID
    depth: int


class FamilyChangedUnderLock(RuntimeError):
    """A locked, checked member could not be deleted; nothing of it commits."""


def _family(root_id: UUID) -> sa.CTE:
    family = (
        sa.select(Files.id.label("file_id"), sa.literal(0).label("depth"))
        .where(Files.id == root_id)
        .cte("file_family", recursive=True)
    )
    child = aliased(Files)
    return family.union_all(
        sa.select(child.id, family.c.depth + 1).where(
            child.parent_file_id == family.c.file_id,
            family.c.depth < _MAX_FAMILY_DEPTH,
        )
    )


class FlowFileFamilyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_run_family(self, run_id: UUID) -> UUID | FamilyBlock | None:
        """Settle a linked ancestor before any of its linked descendants.

        A shared family stays physical after its own links are removed. Choosing
        its descendant first would reclaim part of that kept family or record
        its manifest twice. The bounded lineage walk chooses the highest linked
        ancestor. An incomplete ancestor walk pauses before any release, since
        a linked owner may lie beyond its traversal bound.
        """
        first = run_file_roots(run_id).limit(1).subquery()
        lineage = (
            sa.select(
                Files.id.label("file_id"),
                Files.parent_file_id,
                sa.literal(0).label("depth"),
            )
            .join(first, first.c.file_id == Files.id)
            .cte("run_file_lineage", recursive=True)
        )
        parent = aliased(Files)
        lineage = lineage.union_all(
            sa.select(parent.id, parent.parent_file_id, lineage.c.depth + 1).where(
                parent.id == lineage.c.parent_file_id,
                lineage.c.depth < _MAX_FAMILY_DEPTH,
            )
        )
        root = (
            sa.select(lineage.c.file_id)
            .where(
                sa.or_(
                    *(
                        sa.select(sa.literal(1))
                        .select_from(table)
                        .where(
                            table.flow_run_id == run_id,
                            table.file_id == lineage.c.file_id,
                        )
                        .exists()
                        for table in (FlowRunStepInputFiles, FlowRunStepResultFiles)
                    )
                )
            )
            .order_by(lineage.c.depth.desc(), lineage.c.file_id)
            .limit(1)
            .scalar_subquery()
        )
        incomplete = (
            sa.select(sa.literal(1))
            .select_from(lineage)
            .where(
                lineage.c.depth == _MAX_FAMILY_DEPTH,
                lineage.c.parent_file_id.is_not(None),
            )
            .exists()
        )
        selected = (
            await self.session.execute(
                sa.select(root.label("root"), incomplete.label("incomplete"))
            )
        ).one()
        if selected.root is None:
            return None
        if selected.incomplete:
            return FamilyBlock(
                file_id=selected.root, is_root=False, depth_exceeded=True
            )
        return selected.root

    async def _bounded_count(self, stmt: sa.Select[tuple[UUID]], limit: int) -> int:
        """How many rows `stmt` yields, examining at most `limit` of them."""
        if limit <= 0:
            return 0
        limited = stmt.limit(limit).subquery()
        return int(
            await self.session.scalar(sa.select(sa.func.count()).select_from(limited))
            or 0
        )

    async def count_members(self, root_id: UUID, *, limit: int) -> int:
        family = _family(root_id)
        return await self._bounded_count(sa.select(family.c.file_id), limit)

    async def count_references(self, root_id: UUID, *, limit: int) -> int:
        family = _family(root_id)
        return await self._bounded_count(
            sa.select(FileContentReferences.file_id).join(
                family, family.c.file_id == FileContentReferences.file_id
            ),
            limit,
        )

    async def count_run_links(self, root_id: UUID, *, run_id: UUID, limit: int) -> int:
        """Bound this run's input/result links, including repeated uses of a file."""
        family = _family(root_id)
        links = sa.union_all(
            *(
                sa.select(table.file_id)
                .join(family, family.c.file_id == table.file_id)
                .where(table.flow_run_id == run_id)
                for table in (FlowRunStepInputFiles, FlowRunStepResultFiles)
            )
        ).subquery()
        return await self._bounded_count(sa.select(links.c.file_id), limit)

    async def count_bound_transcripts(self, root_id: UUID, *, limit: int) -> int:
        return await self._bounded_count(
            sa.select(FlowLiveTranscripts.id).where(
                FlowLiveTranscripts.bound_file_id == root_id
            ),
            limit,
        )

    async def lock_members(self, root_id: UUID, *, limit: int) -> Bounded[FamilyMember]:
        """Lock the members (id order, skipping rows another transaction holds)
        and enumerate the family again under those locks.

        Nothing is enumerated or locked beyond `limit` members (one sentinel
        row tells that there are more). `items` is None when the family is
        larger than that, a member is held elsewhere, or the family changed in
        between; it then waits for another pass. A locked member gains neither
        a new owner nor a new child until this transaction ends.
        """

        async def enumerate_family() -> dict[UUID, int]:
            family = _family(root_id)
            rows = await self.session.execute(
                sa.select(family.c.file_id, family.c.depth).limit(limit + 1)
            )
            return {file_id: depth for file_id, depth in rows.tuples()}

        members = await enumerate_family()
        examined = len(members)
        if examined > limit:
            return Bounded(items=None, examined=examined)
        locked = set(
            await self.session.scalars(
                sa.select(Files.id)
                .where(uuid_in(Files.id, list(members)))
                .order_by(Files.id)
                .with_for_update(of=Files, skip_locked=True)
            )
        )
        if locked != set(members):
            return Bounded(items=None, examined=examined)
        again = await enumerate_family()
        examined += len(again)
        if again != members:
            return Bounded(items=None, examined=examined)
        return Bounded(
            items=[
                FamilyMember(file_id=file_id, depth=depth)
                for file_id, depth in members.items()
            ],
            examined=examined,
        )

    async def count_all_bound_transcripts(self, root_id: UUID, *, limit: int) -> int:
        """The root's bound live transcripts, counted up to limit + 1."""
        return await self.count_bound_transcripts(root_id, limit=limit + 1)

    async def outside_owner(
        self,
        root_id: UUID,
        members: Sequence[FamilyMember],
        *,
        root_anchor_edges: frozenset[str],
    ) -> FamilyBlock | None:
        """A fresh check of every member for another owner, the root first; the
        root's own discovery anchor does not count."""
        depth = {member.file_id: member.depth for member in members}
        referenced = list(
            await self.session.scalars(
                sa.select(Files.id)
                .where(
                    uuid_in(Files.id, list(depth)),
                    sa.case(
                        (
                            Files.id == root_id,
                            sa.or_(
                                # A selected descendant belongs to a parent
                                # outside this unit; keep its derived subtree.
                                Files.parent_file_id.is_not(None),
                                flow_file_reference_exists(excluding=root_anchor_edges),
                            ),
                        ),
                        else_=flow_file_reference_exists(excluding=_INTERNAL_EDGES),
                    ),
                )
                .order_by(Files.id)
            )
        )
        if not referenced:
            return None
        first = min(referenced, key=lambda file_id: (depth[file_id], file_id))
        return FamilyBlock(file_id=first, is_root=first == root_id)

    async def too_deep(self, root_id: UUID) -> FamilyBlock | None:
        """A member at the depth bound that still has a child: the family nests
        deeper than it can be enumerated."""
        family = _family(root_id)
        child = aliased(Files)
        member = await self.session.scalar(
            sa.select(family.c.file_id)
            .where(
                family.c.depth == _MAX_FAMILY_DEPTH,
                sa.select(sa.literal(1))
                .select_from(child)
                .where(child.parent_file_id == family.c.file_id)
                .exists(),
            )
            .limit(1)
        )
        if member is None:
            return None
        return FamilyBlock(file_id=member, is_root=False, depth_exceeded=True)

    async def manifest(
        self, members: Sequence[FamilyMember], *, limit: int
    ) -> Bounded[tuple[UUID, UUID]]:
        """Every (file, content) pair of the locked members in reference key
        order; `items` is None when there are more than `limit`."""
        reference = FileContentReferences
        rows = list(
            (
                await self.session.execute(
                    sa.select(reference.file_id, reference.content_id)
                    .where(
                        uuid_in(
                            reference.file_id, [member.file_id for member in members]
                        )
                    )
                    .order_by(reference.file_id, reference.variant, reference.ordinal)
                    .limit(limit + 1)
                )
            ).tuples()
        )
        if len(rows) > limit:
            return Bounded(items=None, examined=len(rows))
        return Bounded(items=rows, examined=len(rows))

    async def delete_members(self, members: Sequence[FamilyMember]) -> int:
        """Delete the locked, checked members deepest first through the shared
        guard; a file's content references go with its row.

        Every member was checked under its lock in this transaction, so the
        guard refusing one means an owner appeared that the lock should have
        kept out: the transaction is failed rather than leaving a partly
        reclaimed family.
        """
        deleted = 0
        for depth in sorted({member.depth for member in members}, reverse=True):
            level = [member.file_id for member in members if member.depth == depth]
            gone = set(
                await self.session.scalars(
                    sa.delete(Files)
                    .where(
                        uuid_in(Files.id, level), sa.not_(flow_file_reference_exists())
                    )
                    .returning(Files.id)
                )
            )
            if gone != set(level):
                raise FamilyChangedUnderLock(sorted(set(level) - gone)[0])
            deleted += len(gone)
        return deleted
