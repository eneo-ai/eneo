"""The one port for copies of another Eneo conversation's content.

A feature that stores content read from another conversation registers an
edge from its copy session to each source question before that content leaves
it. A copy whose source no longer exists is invalid: every content read refuses
it from the moment the source deletion commits, and the derived copies task
removes it. No deletion path writes to the edges.
"""

from collections.abc import Collection
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from eneo.database.database import sessionmanager
from eneo.database.tables.api_keys_v2_table import ApiKeysV2
from eneo.database.tables.questions_table import Questions
from eneo.database.tables.retention_tables import ContentDerivations
from eneo.database.tables.sessions_table import Sessions
from eneo.database.tables.users_table import Users

# Each feature that stores copies, as "module:function" of the function that
# returns copied content. A test proves that each one calls
# register_derivations; a new producer adds itself here.
KNOWN_COPY_PRODUCERS: tuple[str, ...] = ()


class DerivationRegistrationError(RuntimeError):
    """The edges are not known to be committed: return no copied content."""


class DerivedSourceRemovedError(Exception):
    """The caller's conversation holds a copy of content that was removed."""

    code = "derived_source_removed"

    def __init__(self) -> None:
        super().__init__(
            "This conversation holds content copied from a conversation that "
            "has been removed."
        )


def probe(*criteria: ColumnElement[bool]) -> ColumnElement[bool]:
    """EXISTS that stays one index probe per row it is evaluated for.

    OFFSET 0 is PostgreSQL's optimisation fence: without it the planner may
    flatten the check into a join or a hashed subplan that reads every
    question or session on each read, whatever the read's own size.
    """
    return (
        sa.select(sa.literal_column("1", sa.Integer))
        .where(*criteria)
        .offset(sa.literal_column("0", sa.Integer))
        .exists()
    )


def source_removed() -> ColumnElement[bool]:
    """The edge's source question no longer exists; question ids never return."""
    source = aliased(Questions)
    return ~probe(source.id == ContentDerivations.source_question_id)


def copy_session_valid(
    session_id: ColumnElement[UUID] | ColumnElement[UUID | None],
) -> ColumnElement[bool]:
    """True unless the session is a copy with an edge to a removed question.

    Read in the same statement as the content, so a source deletion that
    committed before the statement's snapshot makes the copy unreadable.
    """
    return ~probe(ContentDerivations.copy_session_id == session_id, source_removed())


async def is_removed_copy(session: AsyncSession, copy_session_id: UUID) -> bool:
    """Whether an existing session is a copy whose source was removed."""
    return bool(
        await session.scalar(
            sa.select(~copy_session_valid(Sessions.id.expression)).where(
                Sessions.id == copy_session_id
            )
        )
    )


async def register_derivations(
    *,
    tenant_id: UUID,
    copy_session_id: UUID,
    source_question_ids: Collection[UUID],
) -> None:
    """Record that the copy session holds content of these source questions.

    Runs in its own short transaction and returns only once it committed, so
    the producer may let the content go. The copy session must already be
    committed and belong to the tenant: it is held FOR KEY SHARE, so it cannot
    be deleted while its edges are written. Any failure, including an unknown
    commit outcome, raises DerivationRegistrationError; the producer then
    returns no copied content. A source removed before this commits leaves a
    dangling edge, which makes the copy invalid at once.
    """
    sources = sorted(set(source_question_ids))
    if not sources:
        return
    try:
        async with sessionmanager.session() as session, session.begin():
            held = await session.scalar(
                sa.select(Sessions.id)
                .outerjoin(Users, Sessions.user_id == Users.id)
                .outerjoin(ApiKeysV2, Sessions.api_key_id == ApiKeysV2.id)
                .where(
                    Sessions.id == copy_session_id,
                    sa.func.coalesce(Users.tenant_id, ApiKeysV2.tenant_id) == tenant_id,
                )
                .with_for_update(of=Sessions, key_share=True)
            )
            if held is None:
                raise DerivationRegistrationError(
                    "The copy session does not exist in this tenant."
                )
            await session.execute(
                insert(ContentDerivations)
                .values(
                    [
                        {
                            "tenant_id": tenant_id,
                            "copy_session_id": copy_session_id,
                            "source_question_id": source,
                        }
                        for source in sources
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_content_derivations_copy_source")
            )
    except DerivationRegistrationError:
        raise
    except Exception as error:
        raise DerivationRegistrationError(
            "The copy's sources could not be recorded."
        ) from error
