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
from typing import Any, cast
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

    def __init__(self, message: str, *, details: dict[str, object] | None = None):
        super().__init__(message)
        # What stands in the way, for a client to show. Sent with the refusal.
        self.details = details or {}


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


class FileHomeChangedError(FileHomeError):
    """What the File is being attached to moved to another space meanwhile."""

    code = "file_home_changed"


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


def space_of_conversation(
    *, session_id: UUID | None, service_id: UUID | None
) -> Select[Any]:
    """The space a question will be asked in, before the question exists:
    that of the conversation's assistant or service, or of the service it is
    asked of directly. The same order ``space_of_question`` reads it in."""
    places: list[sa.ScalarSelect[Any]] = []
    if session_id is not None:
        assistant = aliased(Assistants)
        service = aliased(Services)
        places.append(
            sa.select(sa.func.coalesce(assistant.space_id, service.space_id))
            .select_from(Sessions)
            .outerjoin(assistant, assistant.id == Sessions.assistant_id)
            .outerjoin(service, service.id == Sessions.service_id)
            .where(Sessions.id == session_id)
            .scalar_subquery()
        )
    if service_id is not None:
        places.append(
            sa.select(Services.space_id)
            .where(Services.id == service_id)
            .scalar_subquery()
        )
    if not places:
        return sa.select(sa.null())
    return sa.select(sa.func.coalesce(*places, sa.null()))


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


@dataclass(frozen=True, slots=True)
class _OwnersInSpace:
    """What can keep a File in use inside one space, each as a select of ids.

    Built from the space outward, so each step follows an index: the fill-in
    asks this once per space and must not read every use of every File.
    """

    assistants: Select[Any]
    apps: Select[Any]
    runs: Select[Any]
    questions: Select[Any]


def _owners_in_space(space_id: UUID) -> _OwnersInSpace:
    assistants = sa.select(Assistants.id).where(Assistants.space_id == space_id)
    apps = sa.select(Apps.id).where(Apps.space_id == space_id)
    services = sa.select(Services.id).where(Services.space_id == space_id)
    conversations = sa.union(
        sa.select(Sessions.id).where(Sessions.assistant_id.in_(assistants)),
        sa.select(Sessions.id).where(Sessions.service_id.in_(services)),
    ).subquery("conversations_in_space")
    questions = sa.union(
        sa.select(Questions.id).where(
            Questions.session_id.in_(sa.select(conversations.c.id))
        ),
        sa.select(Questions.id).where(Questions.service_id.in_(services)),
    ).subquery("questions_in_space")
    return _OwnersInSpace(
        assistants=assistants,
        apps=apps,
        runs=sa.select(AppRuns.id).where(AppRuns.app_id.in_(apps)),
        questions=sa.select(questions.c.id),
    )


def _files_used_in_space(space_id: UUID) -> sa.Subquery:
    """Every File with a use that an assistant, app, run or question of the
    space holds, in ``file_id``. A File used through a conversation whose
    assistant is elsewhere may be among them; where a family is really in use
    is decided by ``use_of_families``."""
    owners = _owners_in_space(space_id)
    return sa.union_all(
        sa.select(AssistantsFiles.file_id.label("file_id")).where(
            AssistantsFiles.assistant_id.in_(owners.assistants)
        ),
        sa.select(AppsFiles.file_id.label("file_id")).where(
            AppsFiles.app_id.in_(owners.apps)
        ),
        sa.select(AppRunsFiles.file_id.label("file_id")).where(
            AppRunsFiles.app_run_id.in_(owners.runs)
        ),
        sa.select(QuestionsFiles.file_id.label("file_id")).where(
            QuestionsFiles.question_id.in_(owners.questions)
        ),
    ).subquery("files_used_in_space")


def _uses_in_space(space_id: UUID, *, of_files: Select[Any]) -> dict[str, sa.Delete]:
    """Per table, the statement that removes the uses some Files have in one space."""
    owners = _owners_in_space(space_id)
    return {
        "assistants_files": sa.delete(AssistantsFiles).where(
            AssistantsFiles.file_id.in_(of_files),
            AssistantsFiles.assistant_id.in_(owners.assistants),
        ),
        "apps_files": sa.delete(AppsFiles).where(
            AppsFiles.file_id.in_(of_files), AppsFiles.app_id.in_(owners.apps)
        ),
        "app_runs_files": sa.delete(AppRunsFiles).where(
            AppRunsFiles.file_id.in_(of_files),
            AppRunsFiles.app_run_id.in_(owners.runs),
        ),
        "questions_files": sa.delete(QuestionsFiles).where(
            QuestionsFiles.file_id.in_(of_files),
            QuestionsFiles.question_id.in_(owners.questions),
        ),
    }


_RELEASED_WITH_A_SPACE = set(_uses_in_space(UUID(int=0), of_files=sa.select(Files.id)))
_TABLES_WITH_USES = {table for table, _ in _DECLARED_USES}
if _RELEASED_WITH_A_SPACE != _TABLES_WITH_USES:
    raise FileUsePathUndeclaredError(
        "Deleting a space must release every kind of File use: "
        f"{sorted(_RELEASED_WITH_A_SPACE ^ _TABLES_WITH_USES)}"
    )


def _in_words(blockers: dict[str, object]) -> str:
    """One line naming how many of each kind stand in the way."""
    counts = {
        "assistant": len(cast("list[object]", blockers["assistants"])),
        "app": len(cast("list[object]", blockers["apps"])),
        "service": len(cast("list[object]", blockers["services"])),
        "conversation of yours": len(cast("list[object]", blockers["conversations"])),
        "conversation of other people": cast(int, blockers["other_conversations"]),
        "use outside the space": cast(int, blockers["elsewhere"]),
    }
    plural = {
        "conversation of yours": "conversations of yours",
        "conversation of other people": "conversations of other people",
        "use outside the space": "uses outside the space",
    }
    parts = [
        f"{count} {kind if count == 1 else plural.get(kind, kind + 's')}"
        for kind, count in counts.items()
        if count
    ]
    return ", ".join(parts) or "another use"


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

    # --- holding the space ----------------------------------------------
    #
    # Whoever places or attaches a File takes the space before any other row
    # the same work will lock: the assistant, the app, the question, the File
    # itself. A deleted space and a moved assistant or service take the space
    # first too, so the two wait for each other. Taking it after another row
    # would let each hold what the other waits for.

    async def hold_space(self, space_id: UUID) -> None:
        """Keep a space where it is until this transaction ends."""
        held = await self._session.scalar(
            sa.select(Spaces.id)
            .where(Spaces.id == space_id)
            .with_for_update(read=True, key_share=True)
        )
        if held is None:
            raise FileHomeSpaceNotFoundError("The space does not exist.")

    async def hold_space_of_question(self, question_id: UUID) -> UUID | None:
        """Hold the space a question is asked in; ``None`` when it has none."""
        return await self._hold_settled(space_of_question(question_id))

    async def hold_space_of_conversation(
        self, *, session_id: UUID | None, service_id: UUID | None
    ) -> UUID | None:
        """Hold the space a question is about to be asked in."""
        return await self._hold_settled(
            space_of_conversation(session_id=session_id, service_id=service_id)
        )

    async def hold_home_of(self, file_id: UUID) -> UUID | None:
        """Hold the space a File lives in; ``None`` for one without a home."""
        return await self._hold_settled(
            sa.select(Files.home_space_id).where(Files.id == file_id)
        )

    async def _hold_settled(self, where_it_is: Select[Any]) -> UUID | None:
        """Hold the space ``where_it_is`` names, and know it still names it.

        The space is read, then locked, then read again: an assistant or a
        service that moved while this waited for the lock is seen, and the
        space it moved to is held instead.
        """
        for _attempt in range(3):
            space_id = await self._session.scalar(where_it_is)
            if space_id is None:
                return None
            held = await self._session.scalar(
                sa.select(Spaces.id)
                .where(Spaces.id == space_id)
                .with_for_update(read=True, key_share=True)
            )
            if held is not None and await self._session.scalar(where_it_is) == space_id:
                return space_id
        raise FileHomeChangedError(
            "What the file belongs to moved to another space meanwhile. Try again."
        )

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
        used = _files_used_in_space(space_id)
        candidates = (
            sa.select(used.c.file_id)
            .join(Files, Files.id == used.c.file_id)
            .where(Files.home_space_id.is_(None), Files.tenant_id == tenant_id)
            .distinct()
            .order_by(used.c.file_id)
            .limit(limit)
        )
        if after is not None:
            candidates = candidates.where(used.c.file_id > after)
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
                        Files.tenant_id == tenant_id,
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
        viewer_user_id: UUID | None = None,
    ) -> int:
        """Move the home of the Files an assistant takes along to another space.

        The families that live in the source space and are used by the
        assistant or its conversations move. A family that something else
        uses too cannot follow, and cannot be left behind either while the
        assistant still uses it, so the move is refused. No copy is made.

        The refusal says what else uses the Files. ``viewer_user_id`` is the
        person moving the assistant: their own conversations are named, other
        people's are only counted.
        """
        attached = sa.select(AssistantsFiles.file_id.label("file_id")).where(
            AssistantsFiles.assistant_id == assistant_id
        )
        asked = (
            sa.select(QuestionsFiles.file_id.label("file_id"))
            .join(Questions, Questions.id == QuestionsFiles.question_id)
            .join(Sessions, Sessions.id == Questions.session_id)
            .where(Sessions.assistant_id == assistant_id)
        )
        return await self._move_with(
            sa.union_all(attached, asked).subquery("moving_uses"),
            what="the assistant",
            not_the_moving=sa.and_(
                AssistantsFiles.assistant_id != assistant_id,
            ),
            not_asked_of_the_moving=Sessions.assistant_id.is_distinct_from(
                assistant_id
            ),
            source_space_id=source_space_id,
            target_space_id=target_space_id,
            tenant_id=tenant_id,
            viewer_user_id=viewer_user_id,
        )

    async def move_with_service(
        self,
        service_id: UUID,
        *,
        source_space_id: UUID,
        target_space_id: UUID,
        tenant_id: UUID,
        viewer_user_id: UUID | None = None,
    ) -> int:
        """Move the home of the Files a service takes along to another space.

        The same rule as for an assistant: the families that live in the
        source space and that only the service's questions use move, and one
        that something else uses too refuses the move.
        """
        asked = (
            sa.select(QuestionsFiles.file_id.label("file_id"))
            .join(Questions, Questions.id == QuestionsFiles.question_id)
            .outerjoin(Sessions, Sessions.id == Questions.session_id)
            .where(
                sa.or_(
                    Questions.service_id == service_id,
                    Sessions.service_id == service_id,
                )
            )
        )
        return await self._move_with(
            asked.subquery("moving_uses"),
            what="the service",
            not_the_moving=sa.true(),
            not_asked_of_the_moving=sa.and_(
                Questions.service_id.is_distinct_from(service_id),
                Sessions.service_id.is_distinct_from(service_id),
            ),
            source_space_id=source_space_id,
            target_space_id=target_space_id,
            tenant_id=tenant_id,
            viewer_user_id=viewer_user_id,
        )

    async def _move_with(
        self,
        own_uses: sa.Subquery,
        *,
        what: str,
        not_the_moving: sa.ColumnElement[bool],
        not_asked_of_the_moving: sa.ColumnElement[bool],
        source_space_id: UUID,
        target_space_id: UUID,
        tenant_id: UUID,
        viewer_user_id: UUID | None,
    ) -> int:
        """Move the homes of the families that only ``own_uses`` use.

        ``own_uses`` has one row per use, with the File in ``file_id``. The
        caller holds both spaces locked.
        """
        await self._require_space(target_space_id, tenant_id=tenant_id)
        used = sorted(
            (
                await self._session.scalars(sa.select(own_uses.c.file_id).distinct())
            ).all()
        )
        if not used:
            return 0
        root_ids = set((await self._roots_of(used)).values())
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
        own_rows = await self._session.execute(
            sa.select(own_uses.c.file_id, sa.func.count())
            .where(own_uses.c.file_id == sa.any_(_ids("member_ids", sorted(moving))))
            .group_by(own_uses.c.file_id)
        )
        own_count: dict[UUID, int] = dict.fromkeys(moving.values(), 0)
        for file_id, count in own_rows.tuples():
            own_count[moving[file_id]] += count
        all_count = await self._count_all_uses(moving)
        shared = sorted(
            root for root in set(moving.values()) if all_count[root] != own_count[root]
        )
        if shared:
            blockers = await self._what_else_uses(
                [member for member, root in moving.items() if root in shared],
                not_the_moving=not_the_moving,
                not_asked_of_the_moving=not_asked_of_the_moving,
                space_id=source_space_id,
                viewer_user_id=viewer_user_id,
            )
            raise FileInUseElsewhereError(
                f"{len(shared)} file(s) of {what} are also used by something "
                f"else: {_in_words(blockers)}. Remove those uses, or the files "
                f"from {what}, before moving it.",
                details={"files": len(shared), "blockers": blockers},
            )
        result = await self._session.execute(
            sa.update(Files)
            .where(Files.id == sa.any_(_ids("moving", sorted(moving))))
            .values(home_space_id=target_space_id)
        )
        return affected_row_count(result)

    async def _what_else_uses(
        self,
        member_ids: Sequence[UUID],
        *,
        not_the_moving: sa.ColumnElement[bool],
        not_asked_of_the_moving: sa.ColumnElement[bool],
        space_id: UUID,
        viewer_user_id: UUID | None,
    ) -> dict[str, object]:
        """What, besides the thing that is moving, uses some Files.

        Assistants, apps and services of the space are named: whoever may
        move something out of the space can see them. A conversation is named
        only to the person it belongs to; other people's are counted. A use
        outside the space is counted without saying where.
        """
        members = _ids("blocked_members", sorted(member_ids))
        elsewhere = 0

        async def named(statement: Select[Any]) -> list[dict[str, str]]:
            nonlocal elsewhere
            listed: list[dict[str, str]] = []
            for owner_id, name, owner_space_id in (
                await self._session.execute(statement.distinct())
            ).tuples():
                if owner_space_id == space_id:
                    listed.append({"id": str(owner_id), "name": name})
                else:
                    elsewhere += 1
            return sorted(listed, key=lambda owner: (owner["name"], owner["id"]))

        assistants = await named(
            sa.select(Assistants.id, Assistants.name, Assistants.space_id)
            .join(AssistantsFiles, AssistantsFiles.assistant_id == Assistants.id)
            .where(AssistantsFiles.file_id == sa.any_(members), not_the_moving)
        )
        attached_apps = (
            sa.select(Apps.id, Apps.name, Apps.space_id)
            .join(AppsFiles, AppsFiles.app_id == Apps.id)
            .where(AppsFiles.file_id == sa.any_(members))
        )
        run_apps = (
            sa.select(Apps.id, Apps.name, Apps.space_id)
            .join(AppRuns, AppRuns.app_id == Apps.id)
            .join(AppRunsFiles, AppRunsFiles.app_run_id == AppRuns.id)
            .where(AppRunsFiles.file_id == sa.any_(members))
        )
        apps = await named(
            sa.select(sa.union(attached_apps, run_apps).subquery("apps_using"))
        )

        with_assistant = aliased(Assistants)
        with_service = aliased(Services)
        asked_of = aliased(Services)
        # Outer joins: any of these may be empty, whatever the columns say.
        asked = cast(
            "list[tuple[Any, ...]]",
            (
                await self._session.execute(
                    sa.select(
                        Sessions.id,
                        Sessions.name,
                        Sessions.user_id,
                        sa.func.coalesce(with_assistant.name, with_service.name),
                        sa.func.coalesce(
                            with_assistant.space_id, with_service.space_id
                        ),
                        asked_of.id,
                        asked_of.name,
                        asked_of.space_id,
                    )
                    .select_from(QuestionsFiles)
                    .join(Questions, Questions.id == QuestionsFiles.question_id)
                    .outerjoin(Sessions, Sessions.id == Questions.session_id)
                    .outerjoin(
                        with_assistant, with_assistant.id == Sessions.assistant_id
                    )
                    .outerjoin(with_service, with_service.id == Sessions.service_id)
                    .outerjoin(asked_of, asked_of.id == Questions.service_id)
                    .where(
                        QuestionsFiles.file_id == sa.any_(members),
                        not_asked_of_the_moving,
                    )
                    .distinct()
                )
            ).all(),
        )
        own_conversations: dict[str, dict[str, str | None]] = {}
        other_conversations: set[UUID] = set()
        services: dict[str, dict[str, str]] = {}
        for (
            conversation_id,
            conversation_name,
            owner_id,
            with_name,
            conversation_space_id,
            service_id,
            service_name,
            service_space_id,
        ) in asked:
            if conversation_id is None:
                if service_id is not None and service_space_id == space_id:
                    services[str(service_id)] = {
                        "id": str(service_id),
                        "name": service_name,
                    }
                else:
                    elsewhere += 1
            elif conversation_space_id != space_id:
                elsewhere += 1
            elif viewer_user_id is not None and owner_id == viewer_user_id:
                own_conversations[str(conversation_id)] = {
                    "id": str(conversation_id),
                    "name": conversation_name,
                    "with": with_name,
                }
            else:
                other_conversations.add(conversation_id)
        return {
            "assistants": assistants,
            "apps": apps,
            "services": sorted(services.values(), key=lambda owner: owner["name"]),
            # The conversations of the person who is moving it.
            "conversations": sorted(
                own_conversations.values(),
                key=lambda one: (one["name"] or "", one["id"]),
            ),
            # Conversations that belong to other people: a number, nothing more.
            "other_conversations": len(other_conversations),
            # Uses that are not in this space.
            "elsewhere": elsewhere,
        }

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
