from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from eneo.spaces.api.space_models import (
    SpaceMember,
    SpaceMemberOversightJoin,
    SpaceRoleValue,
)
from eneo.spaces.space_factory import _oversight_join
from eneo.spaces.space_repo import SpaceRepository

JOINED_AT = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
REASON = "Ärende KS 2026/123 – kontroll av underlag"


def _member(*, joined: bool) -> SpaceMember:
    return SpaceMember(
        id=uuid4(),
        email=f"{uuid4().hex[:8]}@kommun.se",
        username=None,
        role=SpaceRoleValue.VIEWER,
        oversight_join=(
            SpaceMemberOversightJoin(joined_at=JOINED_AT, reason=REASON)
            if joined
            else None
        ),
    )


def _repo(session: AsyncMock) -> SpaceRepository:
    return SpaceRepository(
        session=session,
        user=MagicMock(),
        factory=MagicMock(),
        file_content_loader=MagicMock(),
        app_repo=None,
        assistant_repo=MagicMock(),
        completion_model_repo=MagicMock(),
        transcription_model_repo=MagicMock(),
        embedding_model_repo=MagicMock(),
        http_auth_encryption=MagicMock(),
    )


async def test_saving_members_keeps_the_oversight_join():
    # _set_members deletes and reinserts every row, so a marker missing from
    # the insert would vanish on the next ordinary space save.
    session = AsyncMock()
    joined, ordinary = _member(joined=True), _member(joined=False)

    await _repo(session)._set_members(
        SimpleNamespace(id=uuid4()), {joined.id: joined, ordinary.id: ordinary}
    )

    delete, insert = (call.args[0] for call in session.execute.call_args_list)
    assert delete.is_delete
    params = insert.compile(dialect=postgresql.dialect()).params
    assert params["user_id_m0"] == joined.id
    assert params["oversight_joined_at_m0"] == JOINED_AT
    assert params["oversight_join_reason_m0"] == REASON
    assert params["user_id_m1"] == ordinary.id
    assert params["oversight_joined_at_m1"] is None
    assert params["oversight_join_reason_m1"] is None


def test_the_factory_reads_the_oversight_join_from_the_row():
    marked = SimpleNamespace(
        oversight_joined_at=JOINED_AT, oversight_join_reason=REASON
    )
    unmarked = SimpleNamespace(oversight_joined_at=None, oversight_join_reason=None)

    assert _oversight_join(marked) == SpaceMemberOversightJoin(
        joined_at=JOINED_AT, reason=REASON
    )
    assert _oversight_join(unmarked) is None
