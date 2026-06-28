from datetime import datetime, timedelta, timezone
from uuid import uuid4

from eneo.questions.question import Question, ToolCallInfo
from eneo.questions.question_protocol import to_question_public
from eneo.sessions.session import SessionInDB, SessionMetadataPublic
from eneo.sessions.session_protocol import (
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


def test_question_public_omits_persisted_tool_result():
    now = datetime.now(timezone.utc)
    question = Question(
        id=uuid4(),
        created_at=now,
        updated_at=now,
        question="Question",
        answer="Answer",
        num_tokens_question=1,
        num_tokens_answer=1,
        tenant_id=uuid4(),
        session_id=uuid4(),
        tool_calls=[
            ToolCallInfo(
                server_name="server",
                tool_name="tool",
                tool_call_id="call_1",
                result="large upstream payload",
                mcp_tool_name="server__tool",
            )
        ],
    )

    public = to_question_public(question)

    assert len(public.tool_calls) == 1
    assert public.tool_calls[0].result is None
    assert question.tool_calls is not None
    assert question.tool_calls[0].result == "large upstream payload"
