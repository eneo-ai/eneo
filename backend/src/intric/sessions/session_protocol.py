from datetime import datetime

from intric.main.models import CursorPaginatedResponse
from intric.questions.question_protocol import to_question_public
from intric.sessions.session import (
    SessionFeedback,
    SessionInDB,
    SessionMetadataPublic,
    SessionPublic,
)


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
        feedback=feedback
    )


def to_session_metadata_public(session: SessionInDB):
    return SessionMetadataPublic(**session.model_dump())


def to_sessions_paginated_response(
    sessions: list[SessionInDB],
    total_count: int,
    limit: int | None = None,
    cursor: datetime = None,
    previous: bool = False,
):
    # If no limit is provided, return all session data.
    if limit is None:
        sessions_public = [to_session_metadata_public(session) for session in sessions]
        return CursorPaginatedResponse(items=sessions_public, total_count=total_count)

    # Handling pagination going forward (getting newer sessions).
    if not previous:
        # Check if more sessions are available than the specified limit.
        if len(sessions) > limit:
            # Exclude the last session from the current page and prepare public metadata.
            sessions_public = [
                to_session_metadata_public(session) for session in sessions[:-1]
            ]
            # Return paginated response with updated cursors for the next page.
            return CursorPaginatedResponse(
                items=sessions_public,
                total_count=total_count,
                previous_cursor=cursor,
                next_cursor=sessions[limit].created_at,
                limit=limit,
            )
        # If sessions length is within the limit, prepare and return the data without a next cursor.
        sessions_public = [to_session_metadata_public(session) for session in sessions]
        return CursorPaginatedResponse(
            items=sessions_public,
            total_count=total_count,
            previous_cursor=cursor,
            limit=limit,
        )
    # Handling pagination going backward (getting older sessions).
    else:
        # Check if there are more sessions than the limit, indicating more pages exist.
        if len(sessions) > limit:
            # Start from the second item,
            # since first item is a cursor to previous page.
            sessions_public = [
                to_session_metadata_public(session) for session in sessions[1:]
            ]
            # Return paginated response with updated cursors for the previous page.
            return CursorPaginatedResponse(
                items=sessions_public,
                total_count=total_count,
                next_cursor=cursor,
                previous_cursor=sessions[1].created_at,
                limit=limit,
            )

        # If the session count fits within the limit, return all sessions.
        sessions_public = [to_session_metadata_public(session) for session in sessions]
        return CursorPaginatedResponse(
            items=sessions_public,
            total_count=total_count,
            next_cursor=cursor,
            limit=limit,
        )


def to_session_metadata_paginated_response(
    sessions: list[SessionMetadataPublic],
    total_count: int,
    limit: int | None = None,
    cursor: datetime = None,
    previous: bool = False,
):
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
