"""The home of a File: the one space it belongs in.

A File is reached through what it is attached to, and that can change. Its
home does not: it is set once, shared by the whole family (the root File and
the Files derived from it), and never emptied. What a space requires of its
content can then be asked of the File itself, wherever it is read.

This module is the only writer of ``files.home_space_id``. Code that creates
or attaches a File passes its context here; it never writes the column.

A File without a home is a draft (uploaded, not used anywhere yet) or a File
from before homes existed. An empty home never means "may be deleted".
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.selectable import Select

from eneo.database.affected_rows import affected_row_count
from eneo.database.tables.app_table import AppRuns, AppRunsFiles, Apps, AppsFiles
from eneo.database.tables.assistant_table import Assistants, AssistantsFiles
from eneo.database.tables.files_table import Files
from eneo.database.tables.questions_table import Questions, QuestionsFiles
from eneo.database.tables.service_table import Services
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.spaces_table import Spaces
from eneo.files.file_usage import FILE_USAGE_COLUMNS, FileUsageRepository


class FileHomeError(Exception):
    """A File cannot be given, or keep, the home that was asked for."""

    code = "file_home_error"


class FileHomeConflictError(FileHomeError):
    """The File already lives in another space."""

    code = "file_home_conflict"


class FileInUseElsewhereError(FileHomeError):
    """The File is used outside the space, or by more than what is moving."""

    code = "file_in_use_elsewhere"


class FileHomeSpaceNotFoundError(FileHomeError):
    """The space is not one of the File's organisation."""

    code = "file_home_space_not_found"


class FileHomeUnresolved(StrEnum):
    """Why the use of a File does not say which space it belongs in."""

    SEVERAL_SPACES = "several_spaces"
    NO_SPACE = "no_space"


@dataclass(frozen=True, slots=True)
class FileHomeFill:
    """What one batch of filling in homes did in one space."""

    # Families that got the space as their home.
    placed: int
    # Roots of families used here that could not be placed, and why. They keep
    # their ids and stay without a home; nothing is split or copied.
    unresolved: dict[UUID, FileHomeUnresolved]
    # Where the next batch continues; ``None`` when the space is done.
    next_after: UUID | None


class FileUsePathUndeclaredError(RuntimeError):
    """A table keeps Files in use without saying which space that use is in."""


@dataclass(frozen=True, slots=True)
class FileFamilyUse:
    """Where a File family is in use."""

    space_ids: frozenset[UUID]
    # Uses that lead to no space, such as a conversation whose assistant is
    # gone. The family cannot be placed by its use while there is one.
    unplaced: int = 0

    @property
    def in_use(self) -> bool:
        return bool(self.space_ids) or self.unplaced > 0

    def only_in(self, space_id: UUID) -> bool:
        return self.unplaced == 0 and self.space_ids <= {space_id}


def _uses_with_their_space() -> dict[tuple[str, str], Select[Any]]:
    """For each column that keeps a File in use: the File and the space of that use."""
    session_assistant = aliased(Assistants)
    session_service = aliased(Services)
    question_service = aliased(Services)
    return {
        ("assistants_files", "file_id"): sa.select(
            AssistantsFiles.file_id.label("file_id"),
            Assistants.space_id.label("space_id"),
        ).join(Assistants, Assistants.id == AssistantsFiles.assistant_id),
        ("apps_files", "file_id"): sa.select(
            AppsFiles.file_id.label("file_id"),
            Apps.space_id.label("space_id"),
        ).join(Apps, Apps.id == AppsFiles.app_id),
        ("app_runs_files", "file_id"): sa.select(
            AppRunsFiles.file_id.label("file_id"),
            Apps.space_id.label("space_id"),
        )
        .join(AppRuns, AppRuns.id == AppRunsFiles.app_run_id)
        .join(Apps, Apps.id == AppRuns.app_id),
        # A question is asked in a conversation with an assistant or a
        # service, or of a service directly.
        ("questions_files", "file_id"): sa.select(
            QuestionsFiles.file_id.label("file_id"),
            sa.func.coalesce(
                session_assistant.space_id,
                session_service.space_id,
                question_service.space_id,
            ).label("space_id"),
        )
        .join(Questions, Questions.id == QuestionsFiles.question_id)
        .outerjoin(Sessions, Sessions.id == Questions.session_id)
        .outerjoin(session_assistant, session_assistant.id == Sessions.assistant_id)
        .outerjoin(session_service, session_service.id == Sessions.service_id)
        .outerjoin(question_service, question_service.id == Questions.service_id),
    }


def space_of_question(question_id: UUID) -> Select[Any]:
    """The space a question is asked in: that of its conversation's assistant
    or service, or of the service it was asked of directly. Empty when the
    question leads to no space. The same path ``questions_files`` is read by."""
    session_assistant = aliased(Assistants)
    session_service = aliased(Services)
    question_service = aliased(Services)
    return (
        sa.select(
            sa.func.coalesce(
                session_assistant.space_id,
                session_service.space_id,
                question_service.space_id,
            )
        )
        .select_from(Questions)
        .outerjoin(Sessions, Sessions.id == Questions.session_id)
        .outerjoin(session_assistant, session_assistant.id == Sessions.assistant_id)
        .outerjoin(session_service, session_service.id == Sessions.service_id)
        .outerjoin(question_service, question_service.id == Questions.service_id)
        .where(Questions.id == question_id)
    )


_USES_WITH_THEIR_SPACE = _uses_with_their_space()
_DECLARED_USES = {(column.table.name, column.name) for _, column in FILE_USAGE_COLUMNS}
if _DECLARED_USES != set(_USES_WITH_THEIR_SPACE):
    # A new way to keep a File in use must also say where that use is, or the
    # home code would not see it and could move or remove a File still in use.
    raise FileUsePathUndeclaredError(
        "Every column that keeps a File in use needs a path to its space in "
        f"eneo.files.file_home: {sorted(_DECLARED_USES ^ set(_USES_WITH_THEIR_SPACE))}"
    )


def _ids(
    name: str, value: Sequence[UUID] | None = None
) -> sa.BindParameter[Sequence[UUID]]:
    return sa.bindparam(name, value=value, type_=ARRAY(PostgreSQLUUID(as_uuid=True)))


def _uses_in_space(space_id: UUID, *, of_files: Select[Any]) -> dict[str, sa.Delete]:
    """Per table, the statement that removes the uses some Files have in one space."""
    assistants = sa.select(Assistants.id).where(Assistants.space_id == space_id)
    apps = sa.select(Apps.id).where(Apps.space_id == space_id)
    services = sa.select(Services.id).where(Services.space_id == space_id)
    runs = sa.select(AppRuns.id).where(AppRuns.app_id.in_(apps))
    conversations = sa.select(Sessions.id).where(
        sa.or_(Sessions.assistant_id.in_(assistants), Sessions.service_id.in_(services))
    )
    questions = sa.select(Questions.id).where(
        sa.or_(
            Questions.session_id.in_(conversations),
            Questions.service_id.in_(services),
        )
    )
    return {
        "assistants_files": sa.delete(AssistantsFiles).where(
            AssistantsFiles.file_id.in_(of_files),
            AssistantsFiles.assistant_id.in_(assistants),
        ),
        "apps_files": sa.delete(AppsFiles).where(
            AppsFiles.file_id.in_(of_files), AppsFiles.app_id.in_(apps)
        ),
        "app_runs_files": sa.delete(AppRunsFiles).where(
            AppRunsFiles.file_id.in_(of_files), AppRunsFiles.app_run_id.in_(runs)
        ),
        "questions_files": sa.delete(QuestionsFiles).where(
            QuestionsFiles.file_id.in_(of_files),
            QuestionsFiles.question_id.in_(questions),
        ),
    }


_RELEASED_WITH_A_SPACE = set(_uses_in_space(UUID(int=0), of_files=sa.select(Files.id)))
_TABLES_WITH_USES = {table for table, _ in _DECLARED_USES}
if _RELEASED_WITH_A_SPACE != _TABLES_WITH_USES:
    raise FileUsePathUndeclaredError(
        "Deleting a space must release every kind of File use: "
        f"{sorted(_RELEASED_WITH_A_SPACE ^ _TABLES_WITH_USES)}"
    )


class FileHomes:
    """Set, take, inherit, check and move the home of File families."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._usage = FileUsageRepository(session)

    # --- reading ---------------------------------------------------------

    async def homes_of(self, file_ids: Iterable[UUID]) -> dict[UUID, UUID | None]:
        """The home of each File that exists; ``None`` for one without a home."""
        ids = sorted(set(file_ids))
        if not ids:
            return {}
        rows = await self._session.execute(
            sa.select(Files.id, Files.home_space_id).where(
                Files.id == sa.any_(_ids("file_ids", ids))
            )
        )
        return {file_id: home for file_id, home in rows.tuples()}

    async def require_no_other_home(
        self, file_ids: Iterable[UUID], *, space_id: UUID
    ) -> None:
        """Refuse Files that live in another space than ``space_id``."""
        homes = await self.homes_of(file_ids)
        elsewhere = sorted(
            file_id
            for file_id, home in homes.items()
            if home is not None and home != space_id
        )
        if elsewhere:
            raise FileHomeConflictError(
                f"{len(elsewhere)} file(s) belong to another space and cannot be "
                "used in this one."
            )

    async def use_of_families(
        self, root_of: dict[UUID, UUID]
    ) -> dict[UUID, FileFamilyUse]:
        """Where each family is in use, given every member mapped to its root.

        Pass the result of ``FileUsageRepository.lock_families`` when the
        answer decides a write.
        """
        if not root_of:
            return {}
        uses = sa.union_all(*_USES_WITH_THEIR_SPACE.values()).subquery("file_uses")
        rows = await self._session.execute(
            sa.select(uses.c.file_id, uses.c.space_id).where(
                uses.c.file_id == sa.any_(_ids("member_ids", sorted(root_of)))
            )
        )
        spaces: dict[UUID, set[UUID]] = {root: set() for root in root_of.values()}
        unplaced: dict[UUID, int] = dict.fromkeys(root_of.values(), 0)
        for file_id, space_id in rows.tuples():
            root_id = root_of[file_id]
            if space_id is None:
                unplaced[root_id] += 1
            else:
                spaces[root_id].add(space_id)
        return {
            root_id: FileFamilyUse(
                space_ids=frozenset(spaces[root_id]), unplaced=unplaced[root_id]
            )
            for root_id in spaces
        }

    # --- writing ---------------------------------------------------------

    async def set_home(self, file_id: UUID, *, space_id: UUID, tenant_id: UUID) -> None:
        """Give a File's family its home at the moment the File is created.

        Nothing happens when the family already lives in the space. A family
        that lives in another space keeps its home and the call is refused.
        """
        await self._require_space(space_id, tenant_id=tenant_id)
        root_of = await self._lock_family_of(file_id, tenant_id=tenant_id)
        await self._write_home(root_of, space_id=space_id)

    async def take(self, file_id: UUID, *, space_id: UUID, tenant_id: UUID) -> None:
        """Give one File its home when it is attached in a space; see ``attach``."""
        await self._require_space(space_id, tenant_id=tenant_id)
        await self.attach([file_id], space_id=space_id)

    async def attach(self, file_ids: Iterable[UUID], *, space_id: UUID) -> None:
        """Place the Files that are being attached to something in a space.

        Call it in the transaction that writes the attachment.

        - A File that lives in the space is fine as it is.
        - A draft takes the space as its home.
        - A File without a home that is already in use is taken only by the
          space where all its uses are, so another space cannot claim it
          before the fill-in reaches it.
        - A File that lives in another space is refused. No copy is made:
          upload the file again for the other space.

        The space is locked first and the families after it, in id order,
        which is the order a deleted space and the fill-in take them in. When
        two spaces take the same draft at once, one gets it and the other is
        refused. A space therefore never ends up holding a File that lives
        elsewhere, or one without a home, once this has committed.
        """
        ids = sorted(set(file_ids))
        if not ids:
            return
        tenant_id = await self._session.scalar(
            sa.select(Spaces.tenant_id)
            .where(Spaces.id == space_id)
            .with_for_update(read=True, key_share=True)
        )
        if tenant_id is None:
            raise FileHomeSpaceNotFoundError("The space does not exist.")
        roots = await self._roots_of(ids)
        if set(roots) != set(ids):
            raise FileHomeError("The file does not exist.")
        root_of = await self._usage.lock_families(set(roots.values()))
        rows = (
            await self._session.execute(
                sa.select(Files.id, Files.tenant_id, Files.home_space_id).where(
                    Files.id == sa.any_(_ids("members", sorted(root_of)))
                )
            )
        ).all()
        if any(row.tenant_id != tenant_id for row in rows):
            raise FileHomeError("The file does not exist.")
        homes_of_root: dict[UUID, set[UUID | None]] = {}
        for row in rows:
            homes_of_root.setdefault(root_of[row.id], set()).add(row.home_space_id)
        elsewhere = sorted(
            root for root, homes in homes_of_root.items() if homes - {None, space_id}
        )
        if elsewhere:
            raise FileHomeConflictError(
                f"{len(elsewhere)} file(s) belong to another space and cannot be "
                "used in this one. Upload them again for this space."
            )
        to_place = {root for root, homes in homes_of_root.items() if None in homes}
        if not to_place:
            return
        placing = {member: root for member, root in root_of.items() if root in to_place}
        # A family that has no home at all is a draft or a File from before
        # homes existed; where it is used decides whether this space may take it.
        unplaced = {
            member: root
            for member, root in placing.items()
            if homes_of_root[root] == {None}
        }
        use = await self.use_of_families(unplaced)
        claimed = sorted(
            root for root, family_use in use.items() if not family_use.only_in(space_id)
        )
        if claimed:
            raise FileInUseElsewhereError(
                f"{len(claimed)} file(s) are already used outside this space and "
                "cannot be attached here. Upload them again for this space."
            )
        await self._session.execute(
            sa.update(Files)
            .where(
                Files.id == sa.any_(_ids("placing", sorted(placing))),
                Files.home_space_id.is_(None),
            )
            .values(home_space_id=space_id)
        )

    async def fill_in_space(
        self, space_id: UUID, *, after: UUID | None = None, limit: int = 500
    ) -> FileHomeFill:
        """Give the Files from before homes existed their home, one batch.

        A family that is used in this space and nowhere else gets the space
        as its home. A family that is also used in another space, or whose
        use leads to no space, is left without a home and reported as
        unresolved: an administrator decides about it, and no id changes.
        Drafts are not touched; they are not in use anywhere.

        Safe to stop and run again: a family that has its home is not a
        candidate any more. ``after`` continues where the batch before ended.
        """
        tenant_id = await self._session.scalar(
            sa.select(Spaces.tenant_id)
            .where(Spaces.id == space_id)
            .with_for_update(read=True, key_share=True)
        )
        if tenant_id is None:
            return FileHomeFill(placed=0, unresolved={}, next_after=None)
        uses = sa.union_all(*_USES_WITH_THEIR_SPACE.values()).subquery("file_uses")
        candidates = (
            sa.select(uses.c.file_id)
            .join(Files, Files.id == uses.c.file_id)
            .where(
                uses.c.space_id == space_id,
                Files.home_space_id.is_(None),
                Files.tenant_id == tenant_id,
            )
            .distinct()
            .order_by(uses.c.file_id)
            .limit(limit)
        )
        if after is not None:
            candidates = candidates.where(uses.c.file_id > after)
        used_here = (await self._session.scalars(candidates)).all()
        if not used_here:
            return FileHomeFill(placed=0, unresolved={}, next_after=None)

        root_ids = set((await self._roots_of(used_here)).values())
        root_of = await self._usage.lock_families(root_ids)
        # Read under the locks: a family another batch placed meanwhile, or
        # one that got its home through an attach, is left as it is.
        without_home = set(
            (
                await self._session.scalars(
                    sa.select(Files.id).where(
                        Files.id
                        == sa.any_(_ids("roots", sorted(set(root_of.values())))),
                        Files.home_space_id.is_(None),
                    )
                )
            ).all()
        )
        candidates_of = {
            member: root for member, root in root_of.items() if root in without_home
        }
        use = await self.use_of_families(candidates_of)
        placing: dict[UUID, UUID] = {}
        unresolved: dict[UUID, FileHomeUnresolved] = {}
        for root_id, family_use in use.items():
            if family_use.only_in(space_id):
                continue
            unresolved[root_id] = (
                FileHomeUnresolved.NO_SPACE
                if family_use.unplaced
                else FileHomeUnresolved.SEVERAL_SPACES
            )
        for member, root_id in candidates_of.items():
            if root_id not in unresolved:
                placing[member] = root_id
        if placing:
            await self._session.execute(
                sa.update(Files)
                .where(
                    Files.id == sa.any_(_ids("members", sorted(placing))),
                    Files.home_space_id.is_(None),
                )
                .values(home_space_id=space_id)
            )
        return FileHomeFill(
            placed=len(set(placing.values())),
            unresolved=unresolved,
            next_after=used_here[-1] if len(used_here) == limit else None,
        )

    async def inherit(self, file_id: UUID, *, from_file_id: UUID) -> None:
        """Give a new File the home of the File it was made from.

        For a File derived from another, and for a new version of a document,
        which is a File of its own from then on.
        """
        source = aliased(Files)
        await self._session.execute(
            sa.update(Files)
            .where(
                Files.id == file_id,
                Files.home_space_id.is_(None),
                source.id == from_file_id,
                source.tenant_id == Files.tenant_id,
                source.home_space_id.is_not(None),
            )
            .values(home_space_id=source.home_space_id)
        )

    async def remove_with_space(self, space_id: UUID) -> int:
        """Remove the Files that live in a space that is being deleted.

        Call it in the transaction that deletes the space, before the space
        row goes. In this order: the space is locked, so no File gets it as
        its home meanwhile; the uses those Files have in the space are
        removed; each family is locked and its use checked again; the unused
        families are removed. A family still used somewhere else stops the
        deletion: a home is never emptied, and removing the File would break
        what uses it.

        A File without a home is left alone, also one that was used only in
        this space: an empty home never means "may be deleted". The cleanup
        of unused Files takes it later, as before.
        """
        tenant_id = await self._session.scalar(
            sa.select(Spaces.tenant_id).where(Spaces.id == space_id).with_for_update()
        )
        if tenant_id is None:
            return 0
        living_here = sa.select(Files.id).where(Files.home_space_id == space_id)
        if not await self._session.scalar(sa.select(living_here.exists())):
            return 0
        for release in _uses_in_space(space_id, of_files=living_here).values():
            await self._session.execute(release)

        roots = (
            await self._session.scalars(
                sa.select(Files.id)
                .where(
                    Files.home_space_id == space_id,
                    Files.tenant_id == tenant_id,
                    Files.parent_file_id.is_(None),
                )
                .order_by(Files.id)
            )
        ).all()
        deleted = 0
        if roots:
            unused = await self._usage.lock_unused_root_families(roots)
            if len(unused) != len(roots):
                raise FileInUseElsewhereError(
                    f"{len(roots) - len(unused)} file(s) that belong to the space "
                    "are still used elsewhere. Remove those uses first."
                )
            result = await self._session.execute(
                sa.delete(Files).where(Files.id == sa.any_(_ids("unused", unused)))
            )
            deleted = affected_row_count(result)
        if await self._session.scalar(sa.select(living_here.exists())):
            raise FileInUseElsewhereError(
                "Some files that belong to the space could not be removed."
            )
        return deleted

    async def move_with_assistant(
        self,
        assistant_id: UUID,
        *,
        source_space_id: UUID,
        target_space_id: UUID,
        tenant_id: UUID,
    ) -> int:
        """Move the home of the Files an assistant takes along to another space.

        The families that live in the source space and are used by the
        assistant or its conversations move. A family that something else
        uses too cannot follow, and cannot be left behind either while the
        assistant still uses it, so the move is refused. No copy is made.
        """
        await self._require_space(target_space_id, tenant_id=tenant_id)
        attached = sa.select(AssistantsFiles.file_id.label("file_id")).where(
            AssistantsFiles.assistant_id == assistant_id
        )
        asked = (
            sa.select(QuestionsFiles.file_id.label("file_id"))
            .join(Questions, Questions.id == QuestionsFiles.question_id)
            .join(Sessions, Sessions.id == Questions.session_id)
            .where(Sessions.assistant_id == assistant_id)
        )
        used_by_assistant = sorted(
            (await self._session.scalars(sa.union(attached, asked))).all()
        )
        if not used_by_assistant:
            return 0
        root_ids = set((await self._roots_of(used_by_assistant)).values())
        root_of = await self._usage.lock_families(root_ids)
        living_in_source = set(
            (
                await self._session.scalars(
                    sa.select(Files.id).where(
                        Files.id
                        == sa.any_(_ids("roots", sorted(set(root_of.values())))),
                        Files.home_space_id == source_space_id,
                        Files.tenant_id == tenant_id,
                    )
                )
            ).all()
        )
        moving = {
            member: root for member, root in root_of.items() if root in living_in_source
        }
        if not moving:
            return 0
        # Counted under the family locks, so an attach that committed while
        # the families were being locked is seen.
        own_uses = await self._count_assistant_uses(moving, assistant_id)
        all_uses = await self._count_all_uses(moving)
        shared = sorted(
            root for root in set(moving.values()) if all_uses[root] != own_uses[root]
        )
        if shared:
            raise FileInUseElsewhereError(
                f"{len(shared)} file(s) of the assistant are also used by "
                "something else in the space. Remove those uses, or the files "
                "from the assistant, before moving it."
            )
        result = await self._session.execute(
            sa.update(Files)
            .where(Files.id == sa.any_(_ids("moving", sorted(moving))))
            .values(home_space_id=target_space_id)
        )
        return affected_row_count(result)

    # --- helpers ---------------------------------------------------------

    async def _count_all_uses(self, root_of: dict[UUID, UUID]) -> dict[UUID, int]:
        uses = sa.union_all(*_USES_WITH_THEIR_SPACE.values()).subquery("file_uses")
        rows = await self._session.execute(
            sa.select(uses.c.file_id, sa.func.count())
            .where(uses.c.file_id == sa.any_(_ids("member_ids", sorted(root_of))))
            .group_by(uses.c.file_id)
        )
        counts: dict[UUID, int] = dict.fromkeys(root_of.values(), 0)
        for file_id, count in rows.tuples():
            counts[root_of[file_id]] += count
        return counts

    async def _count_assistant_uses(
        self, root_of: dict[UUID, UUID], assistant_id: UUID
    ) -> dict[UUID, int]:
        """The uses of each family by one assistant and its conversations."""
        members = _ids("member_ids", sorted(root_of))
        attached = sa.select(AssistantsFiles.file_id.label("file_id")).where(
            AssistantsFiles.assistant_id == assistant_id,
            AssistantsFiles.file_id == sa.any_(members),
        )
        asked = (
            sa.select(QuestionsFiles.file_id.label("file_id"))
            .join(Questions, Questions.id == QuestionsFiles.question_id)
            .join(Sessions, Sessions.id == Questions.session_id)
            .where(
                Sessions.assistant_id == assistant_id,
                QuestionsFiles.file_id == sa.any_(members),
            )
        )
        own = sa.union_all(attached, asked).subquery("assistant_uses")
        rows = await self._session.execute(
            sa.select(own.c.file_id, sa.func.count()).group_by(own.c.file_id)
        )
        counts: dict[UUID, int] = dict.fromkeys(root_of.values(), 0)
        for file_id, count in rows.tuples():
            counts[root_of[file_id]] += count
        return counts

    async def _lock_family_of(
        self, file_id: UUID, *, tenant_id: UUID
    ) -> dict[UUID, UUID]:
        roots = await self._roots_of([file_id])
        root_id = roots.get(file_id)
        if root_id is None:
            raise FileHomeError("The file does not exist.")
        root_of = await self._usage.lock_families([root_id])
        tenants = set(
            (
                await self._session.scalars(
                    sa.select(Files.tenant_id).where(
                        Files.id == sa.any_(_ids("members", sorted(root_of)))
                    )
                )
            ).all()
        )
        if tenants != {tenant_id}:
            raise FileHomeError("The file does not exist.")
        return root_of

    async def _roots_of(self, file_ids: Sequence[UUID]) -> dict[UUID, UUID]:
        """Each File mapped to the root of its family."""
        up = (
            sa.select(
                Files.id.label("start_id"),
                Files.id.label("id"),
                Files.parent_file_id.label("parent_file_id"),
            )
            .where(Files.id == sa.any_(_ids("start_ids", sorted(set(file_ids)))))
            .cte("file_ancestors", recursive=True)
        )
        up = up.union_all(
            sa.select(up.c.start_id, Files.id, Files.parent_file_id).join(
                up, Files.id == up.c.parent_file_id
            )
        )
        rows = await self._session.execute(
            sa.select(up.c.start_id, up.c.id).where(up.c.parent_file_id.is_(None))
        )
        return {start_id: root_id for start_id, root_id in rows.tuples()}

    async def _homes_of_members(self, root_of: dict[UUID, UUID]) -> set[UUID | None]:
        return set(
            (
                await self._session.scalars(
                    sa.select(Files.home_space_id).where(
                        Files.id == sa.any_(_ids("members", sorted(root_of)))
                    )
                )
            ).all()
        )

    async def _write_home(self, root_of: dict[UUID, UUID], *, space_id: UUID) -> None:
        homes = await self._homes_of_members(root_of)
        if homes - {None, space_id}:
            raise FileHomeConflictError(
                "The file belongs to another space and cannot be used in this one."
            )
        if None not in homes:
            return
        await self._session.execute(
            sa.update(Files)
            .where(
                Files.id == sa.any_(_ids("members", sorted(root_of))),
                Files.home_space_id.is_(None),
            )
            .values(home_space_id=space_id)
        )

    async def _require_space(self, space_id: UUID, *, tenant_id: UUID) -> None:
        """The space exists in the organisation and stays until this commits.

        Deleting a space locks its row first, so a home is never written for
        a space that is on its way out: one of the two waits for the other.
        """
        found = await self._session.scalar(
            sa.select(Spaces.id)
            .where(Spaces.id == space_id, Spaces.tenant_id == tenant_id)
            .with_for_update(read=True, key_share=True)
        )
        if found is None:
            raise FileHomeSpaceNotFoundError("The space does not exist.")
