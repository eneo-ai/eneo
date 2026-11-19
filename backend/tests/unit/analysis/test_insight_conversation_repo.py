"""The insights conversation list's cursor (paging itself runs against a
database in ``tests/integration/analysis/test_insight_chat_router.py``)."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from eneo.analysis.insight_conversation_repo import decode_cursor, encode_cursor
from eneo.main.exceptions import BadRequestException

SESSION_ID = UUID("11111111-1111-1111-1111-111111111111")


def test_cursor_round_trips_the_position_after_a_listed_conversation():
    created_at = datetime(2026, 11, 1, 10, 0, 0, 123456, tzinfo=timezone.utc)
    session_id = uuid4()

    assert decode_cursor(encode_cursor(created_at, session_id)) == (
        created_at,
        session_id,
    )


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "not a cursor",
        "2026-11-01T10:00:00Z",
        f"2026-11-01T10:00:00_{SESSION_ID}",
        f"yesterday_{SESSION_ID}",
        "2026-11-01T10:00:00+00:00_not-a-uuid",
    ],
)
def test_a_cursor_the_list_did_not_give_is_refused(cursor: str):
    with pytest.raises(BadRequestException):
        decode_cursor(cursor)
