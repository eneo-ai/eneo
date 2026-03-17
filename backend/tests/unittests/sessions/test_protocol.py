from datetime import datetime, timedelta
from uuid import uuid4

from intric.sessions.session import SessionInDB
from intric.sessions.session import SessionMetadataPublic
from intric.sessions.session_protocol import (
    to_session_metadata_paginated_response,
    to_sessions_paginated_response,
)


def test_no_limit():
    base_datetime = datetime.now()
    test_sessions = [
        SessionInDB(
            id=uuid4(),
            name=f"test-{i}",
            user_id=uuid4(),
            created_at=base_datetime - timedelta(days=i),
        )
        for i in range(10)
    ]
    response = to_sessions_paginated_response(
        sessions=test_sessions, total_count=len(test_sessions)
    )
    assert len(response.items) == len(test_sessions)


def test_pagination_forward_limit():
    base_datetime = datetime.now()
    test_sessions = [
        SessionInDB(
            id=uuid4(),
            name=f"test-{i}",
            user_id=uuid4(),
            created_at=base_datetime - timedelta(days=i),
        )
        for i in range(6)
    ]
    limit = 5
    response = to_sessions_paginated_response(
        sessions=test_sessions,
        limit=limit,
        total_count=len(test_sessions),
    )
    assert len(response.items) == limit
    assert response.next_cursor == test_sessions[limit].created_at
    assert response.previous_cursor is None


def test_pagination_backward_limit():
    base_datetime = datetime.now()
    test_sessions = [
        SessionInDB(
            id=uuid4(),
            name=f"test-{i}",
            user_id=uuid4(),
            created_at=base_datetime - timedelta(days=i),
        )
        for i in range(6)
    ]

    limit = 5
    response = to_sessions_paginated_response(
        sessions=test_sessions,
        total_count=len(test_sessions),
        limit=limit,
        previous=True,
    )
    assert len(response.items) == limit
    assert (
        response.previous_cursor == test_sessions[len(test_sessions) - limit].created_at
    )
    assert response.next_cursor is None


def test_limit_matches_session_count():
    base_datetime = datetime.now()
    test_sessions = [
        SessionInDB(
            id=uuid4(),
            name=f"test-{i}",
            user_id=uuid4(),
            created_at=base_datetime - timedelta(days=i),
        )
        for i in range(10)
    ]

    limit = len(test_sessions)
    response = to_sessions_paginated_response(
        sessions=test_sessions,
        total_count=len(test_sessions),
        limit=limit,
    )
    assert len(response.items) == limit
    assert response.next_cursor is None


def test_metadata_pagination_forward_limit():
    base_datetime = datetime.now()
    test_sessions = [
        SessionMetadataPublic(
            id=uuid4(),
            name=f"test-{i}",
            created_at=base_datetime - timedelta(days=i),
            updated_at=base_datetime - timedelta(days=i),
        )
        for i in range(6)
    ]
    limit = 5
    response = to_session_metadata_paginated_response(
        sessions=test_sessions,
        limit=limit,
        total_count=len(test_sessions),
    )
    assert len(response.items) == limit
    assert response.next_cursor == test_sessions[limit].created_at
