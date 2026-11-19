from datetime import datetime
from typing import TypeVar

from eneo.main.models import CursorPaginatedResponse
from eneo.questions.question_protocol import to_question_public
from eneo.sessions.session import (
    SessionFeedback,
    SessionInDB,
    SessionMetadataPublic,
    SessionPublic,
    SourcedSessionPublic,
)
from eneo.sessions.session_source import source_of

_Metadata = TypeVar("_Metadata", bound=SessionMetadataPublic)


def to_session_public(session: SessionInDB):
    if session.feedback_value is not None:
        feedback = SessionFeedback(
            value=session.feedback_value, text=session.feedback_text
        )
    else:
        feedback = None

    return SessionPublic(
        **session.model_dump(),
        messages=[to_question_public(question) for question in session.questions],
        feedback=feedback,
    )


def to_sourced_session_public(session: SessionInDB) -> SourcedSessionPublic:
    """``to_session_public`` with the conversation's source."""
    return SourcedSessionPublic(
        **dict(to_session_public(session)),
        source=source_of(
            user_id=session.user_id,
            api_key_id=session.api_key_id,
            widget_id=session.widget_id,
        ),
    )


def to_session_metadata_paginated_response(
    sessions: list[_Metadata],
    total_count: int,
    limit: int | None = None,
    cursor: datetime | None = None,
    previous: bool = False,
) -> CursorPaginatedResponse[_Metadata]:
    if limit is None:
        return CursorPaginatedResponse(items=sessions, total_count=total_count)

    if not previous:
        if len(sessions) > limit:
            return CursorPaginatedResponse(
                items=sessions[:-1],
                total_count=total_count,
                previous_cursor=cursor,
                next_cursor=sessions[limit].created_at,
                limit=limit,
            )
        return CursorPaginatedResponse(
            items=sessions,
            total_count=total_count,
            previous_cursor=cursor,
            limit=limit,
        )
    else:
        if len(sessions) > limit:
            return CursorPaginatedResponse(
                items=sessions[1:],
                total_count=total_count,
                next_cursor=cursor,
                previous_cursor=sessions[1].created_at,
                limit=limit,
            )

        return CursorPaginatedResponse(
            items=sessions,
            total_count=total_count,
            next_cursor=cursor,
            limit=limit,
        )
